"""Local RAG Workspace.

Index your desktop files (docs, code, notes) and ask questions about them.
Uses local embeddings (sentence-transformers) or a simple TF-IDF fallback.
No data ever leaves your machine.
"""
import hashlib
import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

_LOGGER = logging.getLogger(__name__)
rag_bp = Blueprint("rag_workspace", __name__)

_RAG_STATE = {
    "indexed_files": 0,
    "total_chunks": 0,
    "last_index_time": None,
    "indexing": False,
    "queries": 0,
}
_RAG_LOCK = threading.Lock()
_INDEX_DIR = None
_INDEX_FILE = None
_DOCS_DIRS = []
_EMBEDDING_MODEL = None

# Simple TF-IDF in-memory index fallback
_INDEX = {
    "documents": [],      # [{id, path, filename, content_snippet, chunks: [{id, text, embedding?}]}]
    "vocab": {},          # word -> idf score
    "doc_freqs": {},      # word -> number of docs containing it
    "total_docs": 0,
}
_ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".rst", ".csv", ".log", ".xml", ".sql", ".sh", ".bat", ".ps1",
    ".java", ".cpp", ".h", ".c", ".cs", ".go", ".rb", ".php", ".rs",
}
_MAX_FILE_SIZE = 1024 * 1024  # 1MB
_MAX_CHUNK_SIZE = 500  # words per chunk


def _debug_failure(context, exc):
    _LOGGER.debug("rag_workspace %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _tokenize(text):
    """Simple word tokenizer."""
    return re.findall(r'\b[a-zA-Z0-9_\-.]{2,}\b', text.lower())


def _compute_idf(docs):
    """Compute IDF for all terms in corpus."""
    doc_freqs = Counter()
    total_docs = len(docs)
    for doc in docs:
        words = set(_tokenize(doc.get("content", "")))
        for w in words:
            doc_freqs[w] += 1
    idf = {}
    for word, freq in doc_freqs.items():
        idf[word] = max(0.1, (total_docs - freq + 0.5) / (freq + 0.5) + 1.0)
    return idf, doc_freqs, total_docs


def _chunk_text(text, filename=""):
    """Split text into overlapping chunks."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), _MAX_CHUNK_SIZE // 2):
        chunk_words = words[i:i + _MAX_CHUNK_SIZE]
        if len(chunk_words) < 10:
            continue
        chunk_text = " ".join(chunk_words)
        chunk_id = hashlib.md5(f"{filename}:{i}".encode()).hexdigest()[:12]
        chunks.append({"id": chunk_id, "text": chunk_text, "offset": i})
    return chunks


def _index_directory(path):
    """Recursively index a directory."""
    path = Path(path).resolve()
    if not path.exists() or not path.is_dir():
        return 0
    # Only allow indexing under user-controlled directories
    allowed_roots = [Path.home()]
    try:
        from shared import COAGENT_DIR
        allowed_roots.append(Path(str(COAGENT_DIR)).resolve())
    except (ImportError, AttributeError):
        pass
    if not any(path == root or str(path).startswith(str(root) + os.sep) for root in allowed_roots):
        _LOGGER.warning("rag_workspace: blocked indexing outside allowed roots: %s", path)
        return 0
    count = 0
    for filepath in path.rglob("*"):
        if filepath.is_symlink():
            continue
        if filepath.suffix.lower() not in _ALLOWED_EXTENSIONS:
            continue
        if filepath.stat().st_size > _MAX_FILE_SIZE:
            continue
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
            if len(text.strip()) < 20:
                continue
            rel_path = str(filepath.relative_to(path)) if path != filepath else filepath.name
            chunks = _chunk_text(text, str(filepath))
            doc = {
                "id": hashlib.md5(str(filepath).encode()).hexdigest()[:12],
                "path": str(filepath),
                "filename": filepath.name,
                "rel_path": rel_path,
                "ext": filepath.suffix,
                "size": filepath.stat().st_size,
                "content_snippet": text[:200],
                "chunks": chunks,
                "indexed_at": datetime.now().isoformat(),
            }
            with _RAG_LOCK:
                _INDEX["documents"].append(doc)
            count += 1
        except Exception as exc:
            _debug_failure(f"index {filepath}", exc)
    return count


def _rebuild_index():
    """Rebuild the full search index from all docs."""
    with _RAG_LOCK:
        all_texts = []
        for doc in _INDEX["documents"]:
            chunk_texts = [c["text"] for c in doc.get("chunks", [])]
            all_texts.append({"content": "\n".join(chunk_texts), "doc": doc})
        idf, doc_freqs, total = _compute_idf(all_texts)
        _INDEX["vocab"] = idf
        _INDEX["doc_freqs"] = dict(doc_freqs)
        _INDEX["total_docs"] = total
        _INDEX["total_chunks"] = sum(len(d.get("chunks", [])) for d in _INDEX["documents"])


def _search(query, top_k=10):
    """TF-IDF search over indexed chunks."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scores = {}  # chunk_id -> (score, chunk, doc)
    with _RAG_LOCK:
        vocab = dict(_INDEX["vocab"])
        documents = list(_INDEX["documents"])

    for doc in documents:
        for chunk in doc.get("chunks", []):
            chunk_tokens = _tokenize(chunk["text"])
            # Compute TF-IDF score
            score = 0
            for qt in query_tokens:
                if qt in vocab:
                    tf = chunk_tokens.count(qt) / max(1, len(chunk_tokens))
                    score += tf * vocab[qt]
            if score > 0:
                scores[chunk["id"]] = {
                    "score": round(score, 4),
                    "chunk": chunk,
                    "doc": {
                        "id": doc["id"],
                        "filename": doc["filename"],
                        "path": doc["path"],
                        "rel_path": doc.get("rel_path", ""),
                        "ext": doc.get("ext", ""),
                    }
                }

    # Sort by score descending
    results = sorted(scores.values(), key=lambda x: -x["score"])[:top_k]
    return results


def _get_index_path():
    global _INDEX_FILE
    if _INDEX_FILE:
        return _INDEX_FILE
    try:
        from shared import COAGENT_DIR
        _INDEX_FILE = Path(str(COAGENT_DIR)) / "rag_index.json"
    except (ImportError, AttributeError):
        _INDEX_FILE = Path.home() / ".hermes" / "rag_index.json"
    _INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    return _INDEX_FILE


def _save_index():
    path = _get_index_path()
    try:
        with _RAG_LOCK:
            data = {
                "documents": _INDEX["documents"],
                "total_chunks": _INDEX.get("total_chunks", 0),
                "indexed_at": _RAG_STATE["last_index_time"],
            }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        _debug_failure("save_index", exc)


def _load_index():
    path = _get_index_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            with _RAG_LOCK:
                _INDEX["documents"] = data.get("documents", [])
                _INDEX["total_chunks"] = data.get("total_chunks", 0)
                _RAG_STATE["last_index_time"] = data.get("indexed_at")
            _rebuild_index()
            _RAG_STATE["indexed_files"] = len(_INDEX["documents"])
            _RAG_STATE["total_chunks"] = _INDEX.get("total_chunks", 0)
            return True
        except Exception as exc:
            _debug_failure("load_index", exc)
    return False


@rag_bp.route("/rag/index", methods=["POST"])
def _rag_index():
    """Index a directory."""
    body = request.get_json(force=True, silent=True) or {}
    path = body.get("path", "")
    if not path:
        return jsonify({"ok": False, "error": "missing 'path'"}), 400

    with _RAG_LOCK:
        if _RAG_STATE["indexing"]:
            return jsonify({"ok": False, "error": "already indexing"}), 409
        _RAG_STATE["indexing"] = True

    try:
        count = _index_directory(path)
        _rebuild_index()
        with _RAG_LOCK:
            _RAG_STATE["indexed_files"] = len(_INDEX["documents"])
            _RAG_STATE["total_chunks"] = _INDEX.get("total_chunks", 0)
            _RAG_STATE["last_index_time"] = datetime.now().isoformat()
        _save_index()
        return jsonify({"ok": True, "indexed": count, "total": _RAG_STATE["indexed_files"],
                        "chunks": _RAG_STATE["total_chunks"]})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    finally:
        with _RAG_LOCK:
            _RAG_STATE["indexing"] = False


@rag_bp.route("/rag/query", methods=["POST"])
def _rag_query():
    """Ask a question about indexed content."""
    body = request.get_json(force=True, silent=True) or {}
    query = body.get("query", "")
    try:
        top_k = min(int(body.get("top_k", 10)), 50)
    except (TypeError, ValueError):
        top_k = 10
    if not query:
        return jsonify({"ok": False, "error": "missing 'query'"}), 400

    with _RAG_LOCK:
        _RAG_STATE["queries"] += 1

    # Load index if empty
    if not _INDEX["documents"]:
        _load_index()

    results = _search(query, top_k)
    return jsonify({
        "ok": True,
        "query": query,
        "results": results,
        "count": len(results),
        "total_indexed": _RAG_STATE["indexed_files"],
    })


@rag_bp.route("/rag/status", methods=["GET"])
def _rag_status():
    with _RAG_LOCK:
        return jsonify({
            "ok": True,
            "indexed_files": _RAG_STATE["indexed_files"],
            "total_chunks": _RAG_STATE["total_chunks"],
            "last_index_time": _RAG_STATE["last_index_time"],
            "indexing": _RAG_STATE["indexing"],
            "queries": _RAG_STATE["queries"],
        })


@rag_bp.route("/rag/directories", methods=["GET", "POST"])
def _rag_directories():
    if request.method == "GET":
        with _RAG_LOCK:
            dirs = list(_DOCS_DIRS)
        return jsonify({"ok": True, "directories": dirs})
    body = request.get_json(force=True, silent=True) or {}
    path = body.get("path", "")
    if path:
        with _RAG_LOCK:
            _DOCS_DIRS.append(path)
            dirs = list(_DOCS_DIRS)
        return jsonify({"ok": True, "directories": dirs})
    return jsonify({"ok": False, "error": "missing 'path'"}), 400


@rag_bp.route("/rag/clear", methods=["DELETE"])
def _rag_clear():
    with _RAG_LOCK:
        _INDEX["documents"] = []
        _INDEX["vocab"] = {}
        _INDEX["doc_freqs"] = {}
        _INDEX["total_docs"] = 0
        _INDEX["total_chunks"] = 0
        _RAG_STATE["indexed_files"] = 0
        _RAG_STATE["total_chunks"] = 0
        _RAG_STATE["last_index_time"] = None
    _save_index()
    # Also delete the index file
    try:
        _get_index_path().unlink(missing_ok=True)
    except Exception:
        pass
    return jsonify({"ok": True, "cleared": True})


def register_routes(app, state, require_auth):
    # Apply auth guard to all RAG routes
    @rag_bp.before_request
    @require_auth
    def _rag_auth_guard():
        pass  # require_auth handles the actual check

    app.register_blueprint(rag_bp)
    _load_index()
    _LOGGER.info("RAG Workspace routes registered (loaded %d files)",
                 _RAG_STATE["indexed_files"])
