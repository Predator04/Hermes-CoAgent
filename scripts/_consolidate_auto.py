#!/usr/bin/env python3
"""
Consolidate 78 routes_auto_*.py files into a single routes_auto.py generic /auto router.

Strategy (behavior-preserving):
  - FEATURE_INFO + _find_tool() + /info + /ping  ->  one generic framework
    driven by a TOOLS registry (metadata + exe + candidate paths).
  - Bespoke action handlers (the 272 non-info/ping routes) -> relocated verbatim,
    namespace-prefixed (per-tool) to avoid collisions.
  - Module-level helpers/constants referenced transitively -> relocated, prefix-renamed.
  - Normalize latent bug: _log("label", msg) [2-arg, shared._log takes 1] -> _log(f"[label] {msg}").

Output: routes_auto.py  (overwrites any existing file with that name)
Also prints a manifest of every registered endpoint for verification.
"""
import ast, glob, json, os, re, sys, datetime

OUT = "routes_auto.py"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def parse(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    return src, ast.parse(src)

def top_level_defs(tree):
    """name -> node for top-level Assign targets / AnnAssign / FunctionDef."""
    defs = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defs[t.id] = node
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                defs[node.target.id] = node
    return defs

def find_feature_info(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "FEATURE_INFO":
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return {}
    return {}

def find_exe_candidates(tree):
    exe, candidates = None, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            is_which = (isinstance(f, ast.Attribute) and f.attr == "which") or \
                       (isinstance(f, ast.Name) and f.id == "which")
            if is_which and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    exe = node.args[0].value
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "candidates":
                    try:
                        candidates = ast.literal_eval(node.value)
                    except Exception:
                        pass
    return exe, candidates

def route_functions(tree):
    reg = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "register_routes":
            reg = node
            break
    if reg is None:
        return []
    routes = []
    for node in reg.body:
        if isinstance(node, ast.FunctionDef):
            path, methods = None, ["GET"]
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) \
                        and dec.func.attr == "route":
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        path = dec.args[0].value
                    for kw in dec.keywords:
                        if kw.arg == "methods":
                            try:
                                methods = ast.literal_eval(kw.value)
                            except Exception:
                                methods = ["GET"]
            if path:
                routes.append((path, methods, node))
    return routes

def collect_refs(node, module_names, found):
    for c in ast.walk(node):
        if isinstance(c, ast.Name) and c.id in module_names and c.id not in found:
            found.add(c.id)

def transitive_refs(route_nodes, module_defs):
    """All module-level names referenced (transitively) by the bespoke actions."""
    # exclude framework-handled names from relocation entirely
    used = set()
    for _p, _m, node in route_nodes:
        collect_refs(node, set(module_defs), used)
    queue = list(used)
    seen = set(used)
    while queue:
        name = queue.pop()
        n = module_defs[name]
        if isinstance(n, ast.FunctionDef):
            for c in ast.walk(n):
                if isinstance(c, ast.Name) and c.id in module_defs and c.id not in seen:
                    seen.add(c.id); queue.append(c.id)
        elif isinstance(n, ast.Assign):
            for c in ast.walk(n.value):
                if isinstance(c, ast.Name) and c.id in module_defs and c.id not in seen:
                    seen.add(c.id); queue.append(c.id)
        elif isinstance(n, ast.AnnAssign) and n.value:
            for c in ast.walk(n.value):
                if isinstance(c, ast.Name) and c.id in module_defs and c.id not in seen:
                    seen.add(c.id); queue.append(c.id)
    return seen


class Renamer(ast.NodeTransformer):
    def __init__(self, tool, rename_map):
        self.tool = tool
        self.rename_map = rename_map
    def visit_FunctionDef(self, node):
        if node.name in self.rename_map:
            node.name = self.rename_map[node.name]
        self.generic_visit(node)
        return node
    def visit_AsyncFunctionDef(self, node):
        if node.name in self.rename_map:
            node.name = self.rename_map[node.name]
        self.generic_visit(node)
        return node
    def visit_Global(self, node):
        node.names = [self.rename_map.get(n, n) for n in node.names]
        return node
    def visit_Nonlocal(self, node):
        node.names = [self.rename_map.get(n, n) for n in node.names]
        return node
    def visit_Name(self, node):
        if node.id == "FEATURE_INFO":
            sub = ast.Subscript(
                value=ast.Name(id="TOOLS", ctx=ast.Load()),
                slice=ast.Constant(value=self.tool), ctx=ast.Load())
            return sub
        if node.id in self.rename_map:
            return ast.Name(id=self.rename_map[node.id], ctx=node.ctx)
        return node
    def visit_Call(self, node):
        node = self.generic_visit(node)
        f = node.func
        if isinstance(f, ast.Name):
            # _find_tool() / _find_<tool>() -> _find_tool("tool")
            if f.id == "_find_tool" or f.id == "_find_" + self.tool:
                return ast.Call(
                    func=ast.Name(id="_find_tool", ctx=ast.Load()),
                    args=[ast.Constant(value=self.tool)], keywords=[])
            # _log("label", msg)  ->  _log(f"[label] {msg}")
            if f.id == "_log" and len(node.args) == 2:
                a, b = node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    joined = ast.JoinedStr(values=[
                        ast.Constant(value="[" + a.value + "] "),
                        ast.FormattedValue(value=b, conversion=-1, format_spec=None),
                    ])
                else:
                    joined = ast.JoinedStr(values=[
                        ast.Constant(value="["),
                        ast.FormattedValue(value=a, conversion=-1, format_spec=None),
                        ast.Constant(value="] "),
                        ast.FormattedValue(value=b, conversion=-1, format_spec=None),
                    ])
                return ast.Call(func=ast.Name(id="_log", ctx=ast.Load()),
                                args=[joined], keywords=[])
        return node


def strip_decorators(fn):
    fn = ast.fix_missing_locations(fn)
    fn.decorator_list = []
    return fn


def collect_import_lines(files):
    """Union of module-level import statements across all source files (deduped)."""
    lines = set()
    for f in files:
        src = open(f, encoding="utf-8").read()
        for line in src.split("\n"):
            if line.startswith("import ") or line.startswith("from "):
                lines.add(line.strip())
    return sorted(lines)


def _import_binds(line):
    """Set of top-level names an import line binds (None if undeterminable, e.g. star import)."""
    line = line.strip()
    if line.startswith("import "):
        names = set()
        for p in line[len("import "):].split(","):
            p = p.strip()
            if " as " in p:
                names.add(p.split(" as ")[1].strip())
            else:
                names.add(p.split(".")[0].strip())
        return names
    if line.startswith("from "):
        m = re.match(r"from\s+[\w.]+\s+import\s+(.+)", line)
        if not m:
            return set()
        names = set()
        for p in m.group(1).split(","):
            p = p.strip()
            if p == "*":
                return None
            names.add(p.split(" as ")[1].strip() if " as " in p else p.strip())
        return names
    return set()


def _used_names_in_code(code):
    """Load-context names referenced in a code snippet (AST-based; excludes import/assign bindings)."""
    names = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
    return names


def filter_imports(import_lines, relocated):
    """Keep only imports whose bound names are actually referenced by relocated code."""
    used = set()
    for _kind, _tool, code in relocated:
        used.update(_used_names_in_code(code))
    result = []
    for line in import_lines:
        binds = _import_binds(line)
        if binds is None or (binds & used):
            result.append(line)
    return result


def merge_imports(import_lines):
    """Merge `from X import ...` lines by module to avoid redefinition noise."""
    simple, from_map = [], {}
    for line in import_lines:
        m = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", line)
        if m:
            mod = m.group(1)
            names = {p.strip() for p in m.group(2).split(",")}
            from_map.setdefault(mod, set()).update(names)
        else:
            simple.append(line)
    result = sorted(simple)
    for mod in sorted(from_map):
        result.append(f"from {mod} import {', '.join(sorted(from_map[mod]))}")
    return result


def _local_names(fn):
    names = set()
    for a in fn.args.args + fn.args.kwonlyargs + getattr(fn.args, "posonlyargs", []):
        names.add(a.arg)
    if fn.args.vararg:
        names.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        names.add(fn.args.kwarg.arg)
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


class StateRewriter(ast.NodeTransformer):
    """Rewrite free-variable `state` (the register_routes param) -> module _STATE."""
    def __init__(self, local_names):
        self.local = local_names
    def visit_Name(self, node):
        if node.id == "state" and isinstance(node.ctx, ast.Load) and "state" not in self.local:
            return ast.Name(id="_STATE", ctx=ast.Load())
        return node


def main():
    files = sorted(glob.glob("routes_auto_*.py"))
    tools = [f[len("routes_auto_"):-len(".py")] for f in files]

    registry = {}          # tool -> metadata dict (for TOOLS)
    relocated = []         # list of (kind, tool, code_str) kind in {const, helper, action}
    endpoint_specs = []    # list of (path, methods, func_name) for bespoke actions
    problems = []

    for tool, path in zip(tools, files):
        src, tree = parse(path)
        defs = top_level_defs(tree)
        fi = find_feature_info(tree)
        exe, candidates = find_exe_candidates(tree)
        routes = route_functions(tree)

        meta = dict(fi) if isinstance(fi, dict) else {}
        meta["exe"] = exe or tool
        if candidates:
            meta["candidates"] = candidates
        registry[tool] = meta

        # classify routes
        info_ping = []
        bespoke = []
        for p, m, node in routes:
            if p == f"/auto/{tool}/info" or p == f"/auto/{tool}/ping":
                info_ping.append((p, m, node))
            else:
                bespoke.append((p, m, node))

        # names to relocate = transitive module-level refs used by bespoke actions,
        # minus FEATURE_INFO and the _find_* helper
        used = transitive_refs([(p, m, n) for p, m, n in bespoke], defs)
        relocate_names = set()
        for n in used:
            if n == "FEATURE_INFO":
                continue
            if n == "_find_tool" or n == "_find_" + tool:
                continue
            relocate_names.add(n)

        rename_map = {n: "_" + tool + "_" + n for n in relocate_names}
        renamer = Renamer(tool, rename_map)

        # relocate constants (Assign/AnnAssign)
        for n in relocate_names:
            node = defs[n]
            if isinstance(node, ast.Assign) or isinstance(node, ast.AnnAssign):
                newnode = renamer.visit(ast.fix_missing_locations(node))
                newnode = ast.fix_missing_locations(newnode)
                # ensure target renamed too
                code = ast.unparse(newnode)
                relocated.append(("const", tool, code))

        # relocate helper functions
        for n in relocate_names:
            node = defs[n]
            if isinstance(node, ast.FunctionDef):
                newnode = renamer.visit(ast.fix_missing_locations(node))
                newnode = StateRewriter(_local_names(newnode)).visit(newnode)
                newnode = ast.fix_missing_locations(newnode)
                code = ast.unparse(newnode)
                relocated.append(("helper", tool, code))

        # relocate bespoke action functions
        for p, m, node in bespoke:
            fn = strip_decorators(ast.fix_missing_locations(node))
            fn = renamer.visit(fn)
            fn = StateRewriter(_local_names(fn)).visit(fn)
            fn = ast.fix_missing_locations(fn)
            fn.name = "_h_" + tool + "_" + str(len(endpoint_specs))
            code = ast.unparse(fn)
            relocated.append(("action", tool, code))
            endpoint_specs.append((p, m, fn.name))

        # sanity: info/ping route count should be 2 (or 0 for weird files)
        if len(info_ping) != 2:
            problems.append(f"{tool}: expected 2 info/ping routes, got {len(info_ping)}")

    # ------------------------------------------------------------------
    # emit routes_auto.py
    # ------------------------------------------------------------------
    header = (
        "# Consolidated /auto tool router.\n"
        f"# Auto-generated from {len(tools)} routes_auto_*.py files by scripts/_consolidate_auto.py\n"
        f"# on {datetime.datetime.utcnow().isoformat()}Z.\n"
        "# Tool metadata lives in TOOLS; info/ping are generic; bespoke action\n"
        "# handlers are relocated below with per-tool namespace prefixes.\n"
    )
    imports = "\n".join(merge_imports(filter_imports(collect_import_lines(files), relocated))) + "\n\n"

    tools_block = "TOOLS = " + json.dumps(registry, indent=2, sort_keys=True) + "\n\n"

    skip_block = "_STATE = None\n\n"

    framework = (
        "\n\ndef _find_tool(tool):\n"
        "    meta = TOOLS.get(tool, {})\n"
        "    exe = shutil.which(meta.get(\"exe\", tool))\n"
        "    if exe:\n"
        "        return exe\n"
        "    for c in meta.get(\"candidates\", []):\n"
        "        if \"*\" in c:\n"
        "            m = glob.glob(c)\n"
        "            if m:\n"
        "                return m[0]\n"
        "        elif os.path.isfile(c):\n"
        "            return c\n"
        "    return None\n\n\n"
        "def _register_generic(app, require_auth, tool):\n"
        "    meta = TOOLS.get(tool, {})\n"
        "    def _info():\n"
        "        info = dict(meta)\n"
        "        exe = _find_tool(tool)\n"
        "        info[\"installed\"] = exe is not None\n"
        "        if exe:\n"
        "            info[\"path\"] = exe\n"
        "            try:\n"
        "                r = subprocess.run([exe, \"--version\"], capture_output=True, text=True, timeout=5)\n"
        "                info[\"version\"] = (r.stdout.strip() or r.stderr.strip()).split(\"\\n\")[0]\n"
        "            except Exception:\n"
        "                info[\"version\"] = \"unknown\"\n"
        "        return jsonify(info)\n"
        "    def _ping():\n"
        "        exe = _find_tool(tool)\n"
        "        return jsonify({\"status\": \"ok\" if exe else \"not_installed\",\n"
        "                         \"feature\": meta.get(\"repo\", tool), \"path\": exe})\n"
        "    app.add_url_rule(f\"/auto/{tool}/info\", endpoint=f\"_auto_{tool}_info\",\n"
        "                      view_func=require_auth(_info), methods=[\"GET\"])\n"
        "    app.add_url_rule(f\"/auto/{tool}/ping\", endpoint=f\"_auto_{tool}_ping\",\n"
        "                      view_func=require_auth(_ping), methods=[\"GET\"])\n\n"
    )

    # relocated code
    rel = "\n# ---- relocated module-level constants / helpers / action handlers ----\n"
    for kind, tool, code in relocated:
        rel += "\n" + code + "\n"

    # registration
    reg_lines = []
    reg_lines.append("\n\ndef register_routes(app, state, require_auth):\n")
    reg_lines.append("    global _STATE\n")
    reg_lines.append("    _STATE = state\n")
    reg_lines.append("    for _tool in TOOLS:\n")
    reg_lines.append("        _register_generic(app, require_auth, _tool)\n")
    reg_lines.append("    _ACTIONS = [\n")
    for p, m, fn in endpoint_specs:
        reg_lines.append(f"        ({p!r}, {m!r}, {fn}),\n")
    reg_lines.append("    ]\n")
    reg_lines.append("    for _path, _methods, _fn in _ACTIONS:\n")
    reg_lines.append("        app.add_url_rule(_path, endpoint=_fn.__name__, view_func=require_auth(_fn), methods=_methods)\n")

    body = header + imports + tools_block + skip_block + framework + rel + "".join(reg_lines)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(body)

    # manifest for verification
    manifest = {
        "tools": sorted(registry.keys()),
        "n_tools": len(registry),
        "n_bespoke_actions": len(endpoint_specs),
        "generic_endpoints": ["/auto/<tool>/info", "/auto/<tool>/ping"],
        "endpoints": [{"path": p, "methods": m} for p, m, _ in endpoint_specs],
        "problems": problems,
    }
    with open("scripts/_consolidate_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"tools: {len(registry)}")
    print(f"bespoke actions relocated: {len(endpoint_specs)}")
    print(f"relocated const/helper/action chunks: {len(relocated)}")
    print(f"problems: {len(problems)}")
    for p in problems:
        print("  !", p)
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")

if __name__ == "__main__":
    main()
