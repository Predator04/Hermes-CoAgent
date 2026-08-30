# Consolidated /auto tool router.
# Auto-generated from 78 routes_auto_*.py files by scripts/_consolidate_auto.py
# on 2026-08-18T07:46:58.536391Z.
# Tool metadata lives in TOOLS; info/ping are generic; bespoke action
# handlers are relocated below with per-tool namespace prefixes.
import ctypes
import glob
import hashlib
import ipaddress
import json
import json as json_lib
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from flask import jsonify, request
from pathlib import Path
from shared import COAGENT_DIR, _json_body, _log, _missing_field

TOOLS = {
  "aider": {
    "added": "2026-08-16",
    "command": "aider --yes --no-git --message \"<prompt>\"",
    "desc": "aider is AI pair programming in your terminal. It edits code in a local git repo using LLMs (OpenAI, Anthropic, DeepSeek, local models). Can run headlessly with --yes --message for fully automated code edits.",
    "exe": "aider",
    "install": {
      "pip": "pip install aider-install",
      "pipx": "pipx install aider-install",
      "uv": "uv tool install aider-install"
    },
    "repo": "Aider-AI/aider",
    "stars": 48267,
    "url": "https://github.com/Aider-AI/aider"
  },
  "apktool": {
    "added": "2026-06-30",
    "desc": "APK reverse engineering tool \u2014 decode resources to nearly original form, rebuild after modification",
    "exe": "apktool",
    "repo": "iBotPeaches/Apktool",
    "stars": 21000,
    "url": "https://github.com/iBotPeaches/Apktool"
  },
  "autohotkey": {
    "added": "2026-07-06",
    "command": "AutoHotkey64.exe / AutoHotkey32.exe",
    "desc": "AutoHotkey - macro-creation and automation-oriented scripting utility for Windows \u2014 run AHK scripts, compile, send keys, and control automation via AutoHotkey CLI",
    "exe": "ahk2exe",
    "repo": "AutoHotkey/AutoHotkey",
    "stars": 12693,
    "url": "https://github.com/AutoHotkey/AutoHotkey"
  },
  "bat": {
    "added": "2026-08-08",
    "candidates": [
      "C:\\Program Files\\bat\\bat.exe",
      "C:\\Program Files (x86)\\bat\\bat.exe"
    ],
    "command": "bat [OPTIONS] [FILE]",
    "desc": "bat is a cat clone with syntax highlighting, line numbers, Git integration, and paging. Supports hundreds of languages and ships with themes.",
    "exe": "bat",
    "install": {
      "choco": "choco install bat",
      "scoop": "scoop install bat",
      "winget": "winget install sharkdp.bat"
    },
    "repo": "sharkdp/bat",
    "stars": 60141,
    "url": "https://github.com/sharkdp/bat"
  },
  "bitsadmin": {
    "added": "2026-07-18",
    "command": "bitsadmin /<operation> [args]",
    "desc": "Built-in Windows BITS (Background Intelligent Transfer Service) administration \u2014 create and manage background download/upload jobs, list all jobs with status/progress, monitor transfer activity, suspend/resume/cancel/complete jobs, add files to jobs, set job priority, manage BITS cache and peer caching",
    "exe": "bitsadmin.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/bitsadmin"
  },
  "certutil": {
    "added": "2026-07-10",
    "command": "certutil <hashfile|-encode|-decode|-store|-cat|-viewstore|-dump|-verifystore|-repairstore>",
    "desc": "Built-in Windows Certificate Services utility \u2014 compute file hashes (MD5/SHA1/SHA256), encode/decode Base64, manage certificates and CRLs, dump certificate stores, generate certificate templates",
    "exe": "certutil.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/certutil"
  },
  "chkdsk": {
    "added": "2026-07-19",
    "command": "chkdsk <volume:> [/F] [/R] [/X]",
    "desc": "Built-in Windows Check Disk \u2014 verify file system integrity, repair disk errors, discover bad sectors, perform offline scans, manage scheduled scans for next boot",
    "exe": "chkdsk.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/chkdsk"
  },
  "choco": {
    "added": "2026-07-11",
    "command": "choco <install|search|upgrade|uninstall|list|info|pin|outdated>",
    "desc": "Chocolatey package manager for Windows \u2014 search, install, upgrade, uninstall, list, pin, and manage software packages from the command line and automate software management",
    "exe": "choco.exe",
    "repo": "chocolatey/choco",
    "stars": 11446,
    "url": "https://github.com/chocolatey/choco"
  },
  "cognee": {
    "added": "2026-06-30",
    "command": "cognee-cli recall",
    "desc": "Definitive data management for AI agents: memory, knowledge graphs, and RAG pipelines",
    "exe": "cognee-cli.exe",
    "repo": "topoteretes/cognee",
    "stars": 1800,
    "url": "https://github.com/topoteretes/cognee"
  },
  "copyq": {
    "added": "2026-07-05",
    "command": "copyq <subcommand>",
    "desc": "Clipboard manager with advanced features \u2014 manage clipboard history, copy/paste text, search, and scripting via copyq CLI",
    "exe": "copyq.exe",
    "repo": "hluk/CopyQ",
    "stars": 11956,
    "url": "https://github.com/hluk/CopyQ"
  },
  "defrag": {
    "added": "2026-07-21",
    "command": "defrag <volume> [/A | /D | /O | /L | /G | /B | /X | /K | /T] [/U] [/V] [/H] [/M]",
    "desc": "Built-in Windows disk optimization \u2014 analyze fragmentation, defrag HDDs, rettrim SSDs, tier optimize, boot optimize, consolidate free space, track progress, multi-volume parallel operation",
    "exe": "Defrag.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/defrag"
  },
  "delta": {
    "added": "2026-08-11",
    "command": "delta [--version] [--list-languages] [--list-themes] [file.diff]",
    "desc": "delta is a syntax-highlighting pager for git, diff, grep, and blame output. It formats diffs with side-by-side or line-by-line views, line numbers, syntax highlighting, and theme support. Use it to make code review output beautiful and readable.",
    "endpoints": {
      "/auto/delta/format": "POST \u2014 syntax-highlight a diff or text snippet",
      "/auto/delta/info": "Feature metadata, install status, version",
      "/auto/delta/languages": "GET \u2014 list supported languages for highlighting",
      "/auto/delta/ping": "Health check",
      "/auto/delta/themes": "GET \u2014 list available color themes"
    },
    "exe": "delta",
    "install": {
      "scoop": "scoop install delta",
      "winget": "winget install dandavison.delta"
    },
    "repo": "dandavison/delta",
    "stars": 31711,
    "url": "https://github.com/dandavison/delta"
  },
  "detect_it_easy": {
    "added": "2026-08-13",
    "command": "diec.exe [-j] [-d] [-u] [-r] [-i] <file-or-directory>",
    "desc": "Detect It Easy (DiE) is a powerful file type identification tool popular among malware analysts and reverse engineers. It identifies file format, compiler, packer/protector, and linker via combined signature + heuristic analysis. The console build 'diec' (batch mode) emits machine-readable JSON (-j), XML (-x), CSV (-c) or plain text. Use it to fingerprint binaries before deeper analysis.",
    "endpoints": {
      "/auto/detect_it_easy/detect": "POST \u2014 fingerprint a file or directory (json, deep, heuristic, recursive, info)",
      "/auto/detect_it_easy/info": "Feature metadata, install status, version",
      "/auto/detect_it_easy/ping": "Health check"
    },
    "exe": "detect_it_easy",
    "install": {
      "scoop": "scoop install detect-it-easy",
      "winget": "winget install horsicq.DIE-engine"
    },
    "repo": "horsicq/Detect-It-Easy",
    "stars": 11337,
    "url": "https://github.com/horsicq/Detect-It-Easy"
  },
  "difftastic": {
    "added": "2026-08-21",
    "command": "difft [--display {inline|side-by-side|json}] [--language <lang>] [--exit-code] <file1> <file2>",
    "desc": "Difftastic (difft) is a structural diff tool that understands syntax - it compares files by their parsed AST rather than raw lines, so renamed/reordered code blocks align correctly and output highlights whole syntactic units (strings, comments, function calls) instead of noisy line diffs. Emits ANSI-color output or machine-readable JSON (--display json) - ideal for code-review and self-improvement pipelines.",
    "endpoints": {
      "/auto/difftastic/diff": "POST - structural diff of two files or two inline strings (inline/side-by-side/json)",
      "/auto/difftastic/languages": "GET - list supported languages with their file extensions",
      "/auto/difftastic/info": "Feature metadata, install status, version",
      "/auto/difftastic/ping": "Health check"
    },
    "exe": "difft",
    "install": {
      "choco": "choco install difftastic",
      "scoop": "scoop install difftastic",
      "winget": "winget install Wilfred.difftastic"
    },
    "repo": "Wilfred/difftastic",
    "stars": 25805,
    "url": "https://github.com/Wilfred/difftastic"
  },
  "devika": {
    "added": "2026-06-30",
    "desc": "Agentic AI software engineer \u2014 understands human instructions, researches, codes, and builds software projects",
    "exe": "devika",
    "repo": "stitionai/devika",
    "stars": 19000,
    "url": "https://github.com/stitionai/devika"
  },
  "devtoys": {
    "added": "2026-07-22",
    "command": "DevToys.CLI.exe [tool] [options]",
    "desc": "A Swiss Army knife for developers. Bundle of tiny tools (base64, hash, JSON format, regex, lorem ipsum, etc.) for quick dev tasks.",
    "exe": "powershell.exe",
    "repo": "DevToys-app/DevToys",
    "stars": 31789,
    "tools": [
      "base64-encode",
      "base64-decode",
      "hash",
      "json-format",
      "html-encode",
      "html-decode",
      "url-encode",
      "url-decode",
      "jwt-decode",
      "uuid-generate",
      "lorem-ipsum",
      "regex"
    ],
    "url": "https://github.com/DevToys-app/DevToys"
  },
  "diskpart": {
    "added": "2026-07-19",
    "command": "diskpart /s <script>",
    "desc": "Built-in Windows Disk Partition Manager \u2014 list/create/delete/format partitions, assign drive letters, manage volumes, convert disk types (MBR/GPT), manage VHDs, clean disks, set active partitions",
    "exe": "diskpart.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/diskpart"
  },
  "dism": {
    "added": "2026-07-09",
    "command": "dism /online /<operation>",
    "desc": "Built-in Windows Deployment Imaging Service and Management \u2014 query/restore component health, manage Windows features and packages, scan/restore system image, manage CBS logs, enable/disable optional features",
    "exe": "Dism.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/dism-reference"
  },
  "doggo": {
    "added": "2026-08-19",
    "command": "doggo [flags] [TYPE ...] <domain> [@resolver]",
    "desc": "doggo is a modern, human-friendly command-line DNS client written in Go \u2014 a dig replacement with colorful tabular output and first-class JSON. Resolve A/AAAA/MX/TXT/CNAME/NS/SOA records, query a specific resolver with @server (UDP, TCP, or DoH/DoT/DoQ via https:// URLs), reverse lookups with --reverse, and machine-readable --json for scripting.",
    "exe": "doggo",
    "install": {
      "scoop": "scoop install doggo",
      "winget": "winget install doggo",
      "go": "go install github.com/mr-karan/doggo/cmd/doggo@latest"
    },
    "repo": "mr-karan/doggo",
    "stars": 4429,
    "url": "https://github.com/mr-karan/doggo"
  },
  "driverquery": {
    "added": "2026-07-21",
    "command": "driverquery [/FO TABLE|LIST|CSV] [/NH] [/SI] [/V] [/S system]",
    "desc": "Built-in Windows driver listing \u2014 enumerate all installed device/system drivers, display as TABLE/LIST/CSV, show signed driver info, verbose module details, query remote systems",
    "exe": "driverquery.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/driverquery"
  },
  "duf": {
    "added": "2026-08-20",
    "command": "duf --json [--all] [--only-fs <fs>] [--hide-fs <fs>] [--sort <col>]",
    "desc": "duf is a cross-platform 'df' alternative with a clean, colorized table and a machine-readable --json mode. It lists every mounted filesystem with device, mount point, filesystem type, total/used/free bytes and inode counts in one call \u2014 ideal for disk-space monitoring and low-space alerting from CoAgent.",
    "exe": "duf",
    "install": {
      "choco": "choco install duf",
      "scoop": "scoop install duf",
      "winget": "winget install muesli.duf"
    },
    "repo": "muesli/duf",
    "stars": 15264,
    "url": "https://github.com/muesli/duf"
  },
  "excel_mcp_server": {
    "added": "2026-07-04",
    "candidates": [
      "excel-mcp",
      "excel-mcp.exe",
      "excel-mcp-server",
      "excel_mcp_server"
    ],
    "command": "excel-mcp or uvx excel-mcp-server",
    "desc": "A Model Context Protocol server for Excel file manipulation",
    "exe": "excel_mcp_server",
    "repo": "haris-musa/excel-mcp-server",
    "stars": 3984,
    "url": "https://github.com/haris-musa/excel-mcp-server"
  },
  "eza": {
    "added": "2026-08-16",
    "command": "eza --long --git --icons [PATH]",
    "desc": "eza is a modern, maintained replacement for the 'ls' command. Written in Rust, it adds git-awareness, icons, colors, tree view, and machine-readable --json output \u2014 ideal for programmatic directory enumeration from CoAgent.",
    "exe": "eza",
    "install": {
      "scoop": "scoop install eza",
      "winget": "winget install eza-community.eza"
    },
    "repo": "eza-community/eza",
    "stars": 22950,
    "url": "https://github.com/eza-community/eza"
  },
  "fd": {
    "added": "2026-08-09",
    "command": "fd [PATTERN] [PATH]",
    "desc": "fd is a simple, fast and user-friendly alternative to the 'find' command. It respects .gitignore, uses smart case-sensitivity, and is blazingly fast. Written in Rust.",
    "exe": "fd",
    "install": {
      "choco": "choco install fd",
      "scoop": "scoop install fd",
      "winget": "winget install sharkdp.fd"
    },
    "repo": "sharkdp/fd",
    "stars": 44020,
    "url": "https://github.com/sharkdp/fd"
  },
  "ffmpeg": {
    "added": "2026-08-18",
    "candidates": [
      "C:\\ffmpeg\\bin\\ffmpeg.exe",
      "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
      "C:\\Program Files (x86)\\ffmpeg\\bin\\ffmpeg.exe"
    ],
    "command": "ffmpeg -i <input> [options] <output>",
    "desc": "FFmpeg is the universal media toolkit \u2014 decode/encode/transcode, mux/demux, stream, filter and play nearly any audio/video format. Powers media probing, transcoding, audio extraction, frame capture, and GIF creation for CoAgent's media/vision pipelines.",
    "exe": "ffmpeg",
    "install": {
      "scoop": "scoop install ffmpeg",
      "winget": "winget install Gyan.FFmpeg"
    },
    "repo": "FFmpeg/FFmpeg",
    "stars": 63418,
    "url": "https://github.com/FFmpeg/FFmpeg"
  },
  "fsutil": {
    "added": "2026-07-17",
    "command": "fsutil <fsinfo|file|volume|behavior|dirty|quota|repair|sparse|usn|hardlink|reparsepoint>",
    "desc": "Built-in Windows filesystem utility \u2014 query file info, disk geometry, volume info, NTFS file system, hard links, sparse files, file system statistics, disk quotas, and USN journal",
    "exe": "fsutil.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/fsutil"
  },
  "fzf": {
    "added": "2026-08-10",
    "command": "fzf [--filter PATTERN] [--height LINES] [--multi]",
    "desc": "fzf is a general-purpose command-line fuzzy finder. Filter anything \u2014 files, processes, command history, git branches \u2014 with interactive fuzzy matching. Supports --filter for non-interactive mode ideal for automation pipelines.",
    "endpoints": {
      "/auto/fzf/filter": "POST \u2014 fuzzy-filter a list of strings against a query",
      "/auto/fzf/info": "Feature metadata, install status, version",
      "/auto/fzf/ping": "Health check",
      "/auto/fzf/search": "POST \u2014 fuzzy-search a directory tree for matching files"
    },
    "exe": "fd",
    "install": {
      "scoop": "scoop install fzf",
      "winget": "winget install junegunn.fzf"
    },
    "repo": "junegunn/fzf",
    "stars": 82485,
    "url": "https://github.com/junegunn/fzf"
  },
  "ghidra": {
    "added": "2026-06-30",
    "desc": "NSA's reverse engineering framework \u2014 disassembly, decompilation, scripting, and binary analysis platform",
    "exe": "ghidra",
    "repo": "NationalSecurityAgency/ghidra",
    "stars": 54000,
    "url": "https://github.com/NationalSecurityAgency/ghidra"
  },
  "gpt4all": {
    "added": "2026-06-30",
    "desc": "Local LLM inference on CPU \u2014 GPT4All runs models locally on any machine without GPU",
    "exe": "gpt4all",
    "repo": "nomic-ai/gpt4all",
    "stars": 72000,
    "url": "https://github.com/nomic-ai/gpt4all"
  },
  "gsudo": {
    "added": "2026-08-05",
    "command": "gsudo [command]",
    "desc": "Sudo for Windows \u2014 run elevated commands with UAC. Enables CoAgent to execute admin-privileged operations like service control, registry writes, and system configuration changes.",
    "exe": "gsudo",
    "install": {
      "choco": "choco install gsudo",
      "scoop": "scoop install gsudo",
      "winget": "winget install gerardog.gsudo"
    },
    "modes": [
      "gsudo [cmd]         - Run cmd elevated (UAC prompt)",
      "gsudo -k             - Terminate all cached gsudo sessions",
      "gsudo config CacheMode Disabled - Disable credential cache"
    ],
    "repo": "gerardog/gsudo",
    "stars": 6019,
    "url": "https://github.com/gerardog/gsudo"
  },
  "hexyl": {
    "added": "2026-08-18",
    "command": "hexyl [OPTIONS] <FILE>",
    "desc": "hexyl is a colorful command-line hex viewer that renders binary files as a terminal-friendly hex dump with an optional character panel, byte-range slicing, and offset skipping \u2014 ideal for binary and reverse-engineering inspection.",
    "exe": "hexyl",
    "install": {
      "choco": "choco install hexyl",
      "scoop": "scoop install hexyl",
      "winget": "winget install sharkdp.hexyl"
    },
    "repo": "sharkdp/hexyl",
    "stars": 10259,
    "url": "https://github.com/sharkdp/hexyl"
  },
  "hyperfine": {
    "added": "2026-08-20",
    "command": "hyperfine -N -w 3 -r 10 --export-json out.json 'cmd1' 'cmd2'",
    "desc": "hyperfine is a command-line benchmarking tool that measures and compares the runtime of shell commands with statistical rigor (warmup runs, multiple samples, mean/min/max, relative speedup) and exports results as JSON/CSV/Markdown \u2014 ideal for measuring CoAgent endpoint latency and detecting performance regressions.",
    "exe": "hyperfine",
    "install": {
      "choco": "choco install hyperfine",
      "scoop": "scoop install hyperfine",
      "winget": "winget install sharkdp.hyperfine"
    },
    "repo": "sharkdp/hyperfine",
    "stars": 28681,
    "url": "https://github.com/sharkdp/hyperfine"
  },
  "icacls": {
    "added": "2026-07-15",
    "command": "icacls <path> [/grant <user>:<perm>[...]] [/deny <user>:<perm>[...]] [/remove <user>] [/setowner <user>] [/inheritance:{e|d|r}] [/save <file> [/t]] [/restore <file> [/t]]",
    "desc": "Built-in Windows permission management \u2014 view file/folder security descriptors with detailed ACE entries (user/group, access rights, inheritance flags), grant/deny/remove specific permissions (R/W/X/F/M), set ownership, enable/disable inheritance, backup and restore ACLs to/from file, and check effective permissions for users/groups",
    "exe": "icacls.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls"
  },
  "imagemagick": {
    "added": "2026-07-12",
    "candidates": [
      "magick",
      "magick.exe",
      "convert",
      "convert.exe",
      "identify",
      "identify.exe"
    ],
    "command": "magick <convert|identify|mogrify|composite|montage|compare>",
    "desc": "ImageMagick is a free, open-source software suite for creating, editing, converting, and displaying images. Supports 200+ formats via CLI (magick/convert/identify/mogrify/composite)",
    "exe": "imagemagick",
    "repo": "ImageMagick/ImageMagick",
    "stars": 16934,
    "url": "https://github.com/ImageMagick/ImageMagick"
  },
  "ipconfig": {
    "added": "2026-07-14",
    "command": "ipconfig [/allcompartments] [/all] [/renew [adapter]] [/release [adapter]] [/flushdns] [/displaydns] [/registerdns] [/showclassid adapter] [/setclassid adapter [classid]]",
    "desc": "Built-in Windows network configuration \u2014 display all adapter configurations (IP addresses, subnet masks, default gateways, DNS servers, MAC addresses/WINS servers/DHCP status), release/renew DHCP leases, flush and display DNS resolver cache, register DNS names with DHCP, show DNS resolver cache statistics, and show DHCP class IDs for all adapters",
    "exe": "ipconfig.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/ipconfig"
  },
  "jq": {
    "added": "2026-08-21",
    "command": "jq [--raw-output] [--compact-output] [--slurp] '<filter>' [file.json]",
    "desc": "jq is a lightweight and flexible command-line JSON processor - the de-facto standard for filtering, transforming, and extracting data from JSON. Pipe any JSON API response, config file, or log through a jq filter to reshape it, select fields, compute aggregates, and emit compact or raw output. Machine-readable and subprocess-friendly, it slots directly into CoAgent automation pipelines.",
    "endpoints": {
      "/auto/jq/query": "POST - run a jq filter against JSON input (inline string or file path)",
      "/auto/jq/validate": "POST - validate that input is well-formed JSON",
      "/auto/jq/info": "Feature metadata, install status, version",
      "/auto/jq/ping": "Health check"
    },
    "exe": "jq",
    "install": {
      "choco": "choco install jq",
      "scoop": "scoop install jq",
      "winget": "winget install jqlang.jq"
    },
    "repo": "jqlang/jq",
    "stars": 35476,
    "url": "https://github.com/jqlang/jq"
  },
  "just": {
    "added": "2026-08-11",
    "command": "just [--list] [--summary] [--dump] [recipe] [args...]",
    "desc": "just is a command runner \u2014 like make but focused on commands, not builds. Define recipes in a justfile (or Justfile) and run them with 'just <recipe>'. Supports arguments, dependencies, .env loading, and shell completions. Perfect for project automation scripts that live alongside code.",
    "endpoints": {
      "/auto/just/dump": "GET \u2014 dump the parsed justfile as JSON",
      "/auto/just/info": "Feature metadata, install status, version",
      "/auto/just/list": "GET \u2014 list all recipes in a justfile (optionally filter by path)",
      "/auto/just/ping": "Health check",
      "/auto/just/run": "POST \u2014 run a just recipe with optional arguments"
    },
    "exe": "just",
    "install": {
      "scoop": "scoop install just",
      "winget": "winget install casey.just"
    },
    "repo": "casey/just",
    "stars": 35250,
    "url": "https://github.com/casey/just"
  },
  "komorebi": {
    "added": "2026-07-05",
    "command": "komorebic <subcommand>",
    "desc": "A tiling window manager for Windows \u2014 manage window layouts, workspaces, focus, and tiling state via komorebic CLI",
    "exe": "komorebic.exe",
    "repo": "LGUG2Z/komorebi",
    "stars": 14864,
    "url": "https://github.com/LGUG2Z/komorebi"
  },
  "kopia": {
    "added": "2026-07-20",
    "command": "kopia [command] [flags]",
    "desc": "Cross-platform backup tool for Windows, macOS & Linux with fast incremental backups, client-side end-to-end encryption, compression and data deduplication. CLI and GUI included.",
    "exe": "kopia.exe",
    "repo": "kopia/kopia",
    "stars": 13700,
    "url": "https://github.com/kopia/kopia"
  },
  "llama_cpp": {
    "added": "2026-08-15",
    "command": "llama-server -m model.gguf --port 8080",
    "desc": "llama.cpp is the C/C++ inference engine behind most local LLM serving. Its llama-server binary exposes an OpenAI-compatible REST API (/health, /v1/models, /v1/completions, /v1/chat/completions, /v1/embeddings) that can run quantized GGUF models on CPU or GPU. This route lets CoAgent discover a running llama-server, list its loaded models, generate text, chat, and produce embeddings \u2014 a direct bridge to whatever model is already being served locally.",
    "endpoints": {
      "/auto/llama_cpp/chat": "POST \u2014 chat completion (/v1/chat/completions)",
      "/auto/llama_cpp/embeddings": "POST \u2014 embedding vector (/v1/embeddings)",
      "/auto/llama_cpp/generate": "POST \u2014 text completion (/v1/completions)",
      "/auto/llama_cpp/health": "GET \u2014 llama-server /health status",
      "/auto/llama_cpp/info": "Feature metadata, binary detection, server reachability",
      "/auto/llama_cpp/models": "GET \u2014 loaded models (/v1/models)",
      "/auto/llama_cpp/ping": "Health check"
    },
    "exe": "llama_cpp",
    "install": {
      "build": "cmake -B build && cmake --build build --config Release",
      "manual": "Download prebuilt Windows binaries from github.com/ggml-org/llama.cpp/releases"
    },
    "repo": "ggml-org/llama.cpp",
    "stars": 124019,
    "url": "https://github.com/ggml-org/llama.cpp"
  },
  "mkcert": {
    "added": "2026-07-20",
    "command": "mkcert [flags] domain1 [domain2 ...]",
    "desc": "Simple zero-config tool to make locally trusted development certificates with any hostnames you'd like. Automatically installs CA in system trust store.",
    "exe": "mkcert.exe",
    "repo": "FiloSottile/mkcert",
    "stars": 59345,
    "url": "https://github.com/FiloSottile/mkcert"
  },
  "netsh": {
    "added": "2026-07-08",
    "command": "netsh <interface|wlan|advfirewall|dnsclient|http|winhttp|bridge>",
    "desc": "Built-in Windows network shell \u2014 manage Wi-Fi profiles/interfaces, firewall rules (advfirewall), TCP/IP settings, DNS client cache, network interfaces, HTTP settings, network bridge, routing table, proxy configuration",
    "exe": "netsh.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/networking/technologies/netsh/netsh-contexts"
  },
  "nmap": {
    "added": "2026-07-12",
    "candidates": [
      "nmap",
      "nmap.exe"
    ],
    "command": "nmap <target> [options]",
    "desc": "Nmap (Network Mapper) is a free and open-source utility for network discovery, port scanning, OS fingerprinting, service/version detection, and security auditing",
    "exe": "nmap",
    "repo": "nmap/nmap",
    "stars": 13179,
    "url": "https://github.com/nmap/nmap"
  },
  "obs_studio": {
    "added": "2026-06-30",
    "desc": "Open-source streaming/recording software \u2014 scene composition, source filters, transitions, and capture cards",
    "exe": "obs_studio",
    "repo": "obsproject/obs-studio",
    "stars": 62000,
    "url": "https://github.com/obsproject/obs-studio"
  },
  "ollama": {
    "added": "2026-08-15",
    "command": "ollama run <model> \"<prompt>\"",
    "desc": "Ollama runs open-weight LLMs (Kimi-K2.6, GLM-5.2, DeepSeek, Qwen, Llama, gpt-oss) locally with a one-line install. It exposes a clean REST API on 127.0.0.1:11434 and a CLI for pulling, serving, generating, and embedding. This route lets CoAgent list models, pull new ones, run non-streaming generation/chat, and produce embeddings \u2014 a local reasoning backend the agent can call without any cloud dependency.",
    "endpoints": {
      "/auto/ollama/chat": "POST \u2014 chat completion (messages array)",
      "/auto/ollama/embeddings": "POST \u2014 embedding vector for a prompt",
      "/auto/ollama/generate": "POST \u2014 non-streaming text generation",
      "/auto/ollama/info": "Feature metadata, install status, server reachability",
      "/auto/ollama/list": "GET \u2014 local models (from /api/tags)",
      "/auto/ollama/ping": "Health check",
      "/auto/ollama/ps": "GET \u2014 currently loaded models (from /api/ps)",
      "/auto/ollama/pull": "POST \u2014 pull a model by name",
      "/auto/ollama/show": "GET \u2014 model metadata (param size, quantization, template)"
    },
    "exe": "ollama",
    "install": {
      "scoop": "scoop install ollama",
      "winget": "winget install Ollama.Ollama"
    },
    "repo": "ollama/ollama",
    "stars": 178596,
    "url": "https://github.com/ollama/ollama"
  },
  "open_interpreter": {
    "added": "2026-06-30",
    "desc": "Natural language computer control \u2014 lets LLMs run code and control the desktop",
    "exe": "open_interpreter",
    "repo": "openinterpreter/open-interpreter",
    "stars": 58000,
    "url": "https://github.com/openinterpreter/open-interpreter"
  },
  "pandoc": {
    "added": "2026-08-22",
    "command": "pandoc [OPTIONS] <input> -f <from> -t <to> [-o <output>]",
    "desc": "Pandoc is a universal document converter that transforms between hundreds of markup and document formats \u2014 Markdown, HTML, DOCX, PDF (via engine), LaTeX, EPUB, reStructuredText, MediaWiki, plain text, and more. It is subprocess-callable and ideal for CoAgent document pipelines: convert generated reports and READMEs between formats, extract plain text from rich docs, and emit standalone HTML/PDF output. Reads stdin or a file and writes to stdout or an output path.",
    "endpoints": {
      "/auto/pandoc/convert": "POST \u2014 convert inline text or a file between any supported formats",
      "/auto/pandoc/formats": "GET \u2014 list supported input/output formats",
      "/auto/pandoc/info": "Feature metadata, install status, version",
      "/auto/pandoc/ping": "Health check"
    },
    "exe": "pandoc",
    "install": {
      "choco": "choco install pandoc",
      "scoop": "scoop install pandoc",
      "winget": "winget install JohnMacFarlane.Pandoc"
    },
    "repo": "jgm/pandoc",
    "stars": 45976,
    "url": "https://github.com/jgm/pandoc"
  },
  "pe_sieve": {
    "added": "2026-08-13",
    "command": "pe-sieve.exe /pid <PID> [/json] [/dmode <A|D|V|U|R|N>] [/quiet] [/minidmp] [/dir <out>]",
    "desc": "PE-sieve is a lightweight process scanner that detects malware running on the system and dumps the malicious material for analysis. It recognizes and dumps replaced/injected PEs, shellcode, inline hooks, and other in-memory patches \u2014 including process hollowing, process doppelgaenging, and reflective DLL injection. Runs as a single-process scanner (EXE) or embeddable DLL. Emits a JSON report with /json.",
    "endpoints": {
      "/auto/pe_sieve/info": "Feature metadata, install status, version",
      "/auto/pe_sieve/ping": "Health check",
      "/auto/pe_sieve/scan": "POST \u2014 scan a live process by PID for implants/injections (json, dmode, quiet, minidump, dir)"
    },
    "exe": "pe_sieve",
    "install": {
      "manual": "Download pe-sieve64.zip from https://github.com/hasherezade/pe-sieve/releases and extract to a folder on PATH (or C:\\tools\\pe-sieve)",
      "note": "Not published on winget or scoop. Best-effort: place pe-sieve.exe in a PATH dir."
    },
    "repo": "hasherezade/pe-sieve",
    "stars": 3853,
    "url": "https://github.com/hasherezade/pe-sieve"
  },
  "photoshop_mcp": {
    "added": "2026-07-04",
    "command": "npx @photoshops/mcp-server",
    "desc": "MCP server for Adobe Photoshop automation \u2014 50+ tools for design, image editing, workflow",
    "exe": "npx",
    "repo": "alisaitteke/photoshop-mcp",
    "stars": 155,
    "url": "https://github.com/alisaitteke/photoshop-mcp"
  },
  "plandex": {
    "added": "2026-06-30",
    "desc": "AI coding agent for terminal \u2014 plans and builds large-scale software changes autonomously",
    "exe": "plandex",
    "repo": "plandex-ai/plandex",
    "stars": 11000,
    "url": "https://github.com/plandex-ai/plandex"
  },
  "playwright": {
    "added": "2026-06-30",
    "desc": "Cross-browser automation framework \u2014 reliable end-to-end testing with auto-waiting and browser context isolation",
    "exe": "playwright",
    "repo": "microsoft/playwright",
    "stars": 72000,
    "url": "https://github.com/microsoft/playwright"
  },
  "powercfg": {
    "added": "2026-07-08",
    "command": "powercfg <list|query|changename|duplicatescheme|delete|setactive|getactivescheme|change|hibernate|sleepstudy|batteryreport>",
    "desc": "Built-in Windows power management \u2014 enumerate power schemes, query/subgroup settings, set active plan, configure sleep/hibernate/display timeouts, generate battery health report",
    "exe": "powercfg.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-hardware/operations/powercfg"
  },
  "powertoys": {
    "added": "2026-06-30",
    "desc": "Windows system utilities \u2014 FancyZones, PowerRename, Keyboard Manager, and advanced window management tools",
    "exe": "powertoys",
    "repo": "microsoft/PowerToys",
    "stars": 115000,
    "url": "https://github.com/microsoft/PowerToys"
  },
  "procs": {
    "added": "2026-08-12",
    "command": "procs [--json] [--watch] [--tree] [--only-name <name>] [--or] [--sorta cpu|mem] [PID...]",
    "desc": "procs is a modern replacement for ps written in Rust. It outputs process information with colored terminal output by default, but its killer feature for automation is native JSON output (--json). Filters by name, PID, user, CPU/memory usage, and more. Supports tree view, watch mode, and customizable columns. Perfect for programmatic process monitoring.",
    "endpoints": {
      "/auto/procs/find": "GET \u2014 find process by name/PID with detail",
      "/auto/procs/info": "Feature metadata, install status, version",
      "/auto/procs/kill": "POST \u2014 kill a process by PID (force option)",
      "/auto/procs/list": "GET \u2014 list all processes as JSON (optional filters: name, pid, user)",
      "/auto/procs/ping": "Health check",
      "/auto/procs/tree": "GET \u2014 process tree view as JSON"
    },
    "exe": "procs",
    "install": {
      "scoop": "scoop install procs",
      "winget": "winget install procs"
    },
    "repo": "dalance/procs",
    "stars": 6131,
    "url": "https://github.com/dalance/procs"
  },
  "pywinauto": {
    "added": "2026-06-30",
    "desc": "Python GUI automation for Windows \u2014 send mouse/keyboard, manage windows and controls via UIA and Win32 APIs",
    "exe": "pywinauto",
    "repo": "nickie/pywinauto",
    "stars": 5200,
    "url": "https://github.com/nickie/pywinauto"
  },
  "rapidocr": {
    "added": "2026-06-30",
    "command": "rapidocr -img <image>",
    "desc": "Cross-platform OCR engine using ONNX Runtime for text detection, recognition, and table extraction",
    "exe": "rapidocr.exe",
    "repo": "RapidAI/RapidOCR",
    "stars": 3500,
    "url": "https://github.com/RapidAI/RapidOCR"
  },
  "rclone": {
    "added": "2026-08-23",
    "candidates": [
      "C:\\Program Files\\rclone\\rclone.exe",
      "C:\\Program Files (x86)\\rclone\\rclone.exe"
    ],
    "command": "rclone <listremotes|lsjson|size|about|sync|copy|check> [args]",
    "desc": "rclone is 'rsync for cloud storage' - a single Go binary that lists, syncs, copies and manages files across 80+ providers (Google Drive, S3, OneDrive, Dropbox, Backblaze B2, SFTP, WebDAV, etc.). Subprocess-callable with --json output, so CoAgent can enumerate configured remotes, list files, measure usage/quota, and run automated cloud sync and backup jobs.",
    "endpoints": {
      "/auto/rclone/about": "POST - storage quota/usage for a remote (rclone about remote: --json)",
      "/auto/rclone/check": "POST - integrity-check two paths (rclone check src: dst:)",
      "/auto/rclone/copy": "POST - copy files from source to destination",
      "/auto/rclone/info": "Feature metadata, install status, version",
      "/auto/rclone/list": "POST - list files in a remote path as JSON (rclone lsjson)",
      "/auto/rclone/ping": "Health check",
      "/auto/rclone/remotes": "GET - list configured remotes (rclone listremotes --json)",
      "/auto/rclone/size": "POST - total size + object count of a remote path",
      "/auto/rclone/sync": "POST - one-way sync source to destination (dry-run option)"
    },
    "exe": "rclone",
    "install": {
      "scoop": "scoop install rclone",
      "winget": "winget install Rclone.Rclone"
    },
    "repo": "rclone/rclone",
    "stars": 59324,
    "url": "https://github.com/rclone/rclone"
  },
  "reg": {
    "added": "2026-07-10",
    "command": "reg <query|add|delete|copy|export|import|save|restore|load|unload|compare|flags>",
    "desc": "Built-in Windows Registry CLI \u2014 query/read registry keys and values, add/modify keys and values, delete keys/values, export/import .reg files, compare registry snapshots, copy keys across hives",
    "exe": "reg.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/reg"
  },
  "restic": {
    "added": "2026-08-23",
    "candidates": [
      "C:\\Program Files\\restic\\restic.exe",
      "C:\\Program Files (x86)\\restic\\restic.exe"
    ],
    "command": "restic <init|backup|snapshots|restore|stats|check> [args]",
    "desc": "restic is a fast, secure, deduplicated, end-to-end encrypted backup program written in Go. Versioned snapshots with AES-256 encryption. Fully CLI-driven with --json output and RESTIC_REPOSITORY / RESTIC_PASSWORD env vars, so CoAgent can run automated encrypted backup and restore jobs over local, SFTP, S3, and rclone backends.",
    "endpoints": {
      "/auto/restic/backup": "POST - back up a path into the repository (restic backup --json)",
      "/auto/restic/init": "POST - initialize a new repository (restic init)",
      "/auto/restic/info": "Feature metadata, install status, version",
      "/auto/restic/ping": "Health check",
      "/auto/restic/restore": "POST - restore a snapshot to a target directory",
      "/auto/restic/snapshots": "GET - list snapshots in the repository (--json)",
      "/auto/restic/stats": "GET - repository statistics (--json)"
    },
    "exe": "restic",
    "install": {
      "scoop": "scoop install restic",
      "winget": "winget install restic.restic"
    },
    "repo": "restic/restic",
    "stars": 35669,
    "url": "https://github.com/restic/restic"
  },
  "ripgrep": {
    "added": "2026-08-08",
    "command": "rg [PATTERN] [PATH]",
    "desc": "ripgrep recursively searches directories for a regex pattern while respecting gitignore rules. Blazing fast grep alternative written in Rust.",
    "exe": "rg",
    "install": {
      "choco": "choco install ripgrep",
      "scoop": "scoop install ripgrep",
      "winget": "winget install BurntSushi.ripgrep.MSVC"
    },
    "repo": "BurntSushi/ripgrep",
    "stars": 67118,
    "url": "https://github.com/BurntSushi/ripgrep"
  },
  "rufus": {
    "added": "2026-07-24",
    "cli": "rufus.exe /create /iso:\"<path>\" /drive:<letter>",
    "cli_params": [
      "/create",
      "/iso:",
      "/drive:",
      "/target:layout",
      "/volume_label:",
      "/no_2fa"
    ],
    "desc": "The Reliable USB Formatting Utility. Create bootable USB drives from ISOs, format USB drives, create Windows To Go drives, and more.",
    "exe": "rufus.exe",
    "repo": "pbatard/rufus",
    "stars": 37019,
    "url": "https://github.com/pbatard/rufus"
  },
  "sc": {
    "added": "2026-07-14",
    "command": "sc [<server>] query [<service>] | qc | start | stop | pause | continue | config | failure",
    "desc": "Built-in Windows Service Control \u2014 list all services with state/type, query individual service details (name, display name, PID, type, dependencies), start/stop/pause/resume services, configure service startup type (auto, manual, disabled), set failure recovery actions, query service dependencies, and manage service security descriptors",
    "exe": "sc.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/sc-query"
  },
  "schtasks": {
    "added": "2026-07-17",
    "command": "schtasks <Query|Create|Run|End|Change|Delete> [/S system] [/U user] [/P password]",
    "desc": "Built-in Windows Task Scheduler CLI \u2014 query/create/run/change/end/delete scheduled tasks, query task folders, view task details, manage task scheduler state",
    "exe": "schtasks.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks"
  },
  "scrcpy": {
    "added": "2026-08-12",
    "command": "scrcpy [--list-displays] [--no-window] [--record=file.mp4] [--video-source=camera]",
    "desc": "scrcpy provides display and control of Android devices connected via USB or TCP/IP. Mirror your phone screen, record video, use the device camera as a webcam, and automate interactions \u2014 all from the command line. Supports headless operation with --no-window for server-side automation.",
    "endpoints": {
      "/auto/scrcpy/devices": "GET \u2014 list connected Android devices via adb",
      "/auto/scrcpy/displays": "GET \u2014 list available displays on connected device",
      "/auto/scrcpy/info": "Feature metadata, install status, version",
      "/auto/scrcpy/ping": "Health check",
      "/auto/scrcpy/record": "POST \u2014 start/stop headless screen recording"
    },
    "exe": "adb",
    "install": {
      "scoop": "scoop install scrcpy",
      "winget": "winget install Genymobile.scrcpy"
    },
    "repo": "Genymobile/scrcpy",
    "stars": 147497,
    "url": "https://github.com/Genymobile/scrcpy"
  },
  "sd": {
    "added": "2026-08-17",
    "command": "sd [--preview] [--fixed-strings] <find> <replace_with> [files...]",
    "desc": "sd is an intuitive find & replace CLI (a friendlier sed alternative). It uses JavaScript-flavored regex, avoids sed's confusing escaping, and works across files, directories, and stdin \u2014 ideal for CoAgent to script safe text transformations with a built-in dry-run preview.",
    "endpoints": {
      "/auto/sd/info": "Feature metadata, install status, version",
      "/auto/sd/ping": "Health check",
      "/auto/sd/replace": "POST \u2014 find & replace across a file, directory, or stdin text (with dry-run preview)"
    },
    "exe": "sd",
    "install": {
      "scoop": "scoop install sd",
      "winget": "winget install chmln.sd"
    },
    "repo": "chmln/sd",
    "stars": 7305,
    "url": "https://github.com/chmln/sd"
  },
  "sfc": {
    "added": "2026-07-09",
    "command": "sfc /scannow /verifyonly /verifyfile=<path>",
    "desc": "Built-in Windows System File Checker \u2014 scan and verify integrity of protected system files, repair corrupted files, log verification results, check last scan status",
    "exe": "sfc.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/sfc"
  },
  "sharex": {
    "added": "2026-07-23",
    "cli_actions": [
      "RectangleRegion",
      "PrintScreen",
      "ClipboardUpload",
      "ScreenColorPicker",
      "FileUpload",
      "OCR",
      "HashCheck",
      "Metadata",
      "ImageEditor",
      "VideoConverter",
      "PinToScreen",
      "ImageBeautifier",
      "ImageEffects",
      "ImageViewer",
      "StripMetadata",
      "QRCode"
    ],
    "command": "ShareX.exe [action] [file]",
    "desc": "Screen capture, file sharing and productivity tool. Supports region capture, screen recording, OCR, color picker, file upload, image editing, and more.",
    "exe": "tesseract.exe",
    "repo": "ShareX/ShareX",
    "stars": 38775,
    "url": "https://github.com/ShareX/ShareX"
  },
  "sharpdxscreencapture": {
    "added": "2026-06-30",
    "command": "SharpDxScreenCapture.exe --output <file>",
    "desc": "High-performance screen capture for Windows using DirectX/SharpDX for low-latency frame grabbing",
    "exe": "sharpdxscreencapture",
    "repo": "AnderssonPeter/SharpDxScreenCapture",
    "stars": 400,
    "url": "https://github.com/AnderssonPeter/SharpDxScreenCapture"
  },
  "shutdown": {
    "added": "2026-07-15",
    "command": "shutdown [/i | /l | /s | /r | /g | /a | /p | /h | /hybrid] [/f] [/m \\\\<computer>] [/t <seconds>] [/d <p>:<rr>:<c>] [/c <comment>]",
    "desc": "Built-in Windows system power management \u2014 shutdown (with delay, message, reason), restart (with delay, message, reason), logoff current session, hibernate/sleep, abort pending shutdown, remote machine shutdown/restart (with credentials), and forced termination of running applications on shutdown",
    "exe": "wevtutil.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shutdown"
  },
  "systeminfo": {
    "added": "2026-07-13",
    "command": "systeminfo [/S system] [/U username] [/FO format]",
    "desc": "Built-in Windows system information \u2014 query OS version, build number, system type, total/free physical and virtual memory, processor count, hotfix list, uptime, boot device, time zone, and detailed configuration",
    "exe": "systeminfo.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/systeminfo"
  },
  "takeown": {
    "added": "2026-07-21",
    "command": "takeown /F <path> [/R] [/A] [/D Y|N] [/SKIPSL]",
    "desc": "Built-in Windows file ownership recovery \u2014 take ownership of files/folders recursively, assign to current user or Administrators group, skip symlinks, operate on remote systems",
    "exe": "takeown.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/takeown"
  },
  "taskkill": {
    "added": "2026-07-16",
    "command": "taskkill [/s computer] [/u domain\\user [/p password]] [/fi filter] [/pid pid|/im imagename] [/f] [/t]",
    "desc": "Built-in Windows Process Terminator \u2014 kill processes by PID, image name, or filter; force terminate, kill process trees, remote process termination, filter by window state/modules/services",
    "exe": "taskkill.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill"
  },
  "tasklist": {
    "added": "2026-07-13",
    "command": "tasklist [/S system] [/M module] [/V] [/FI filter] [/FO format] & taskkill [/F] [/IM name | /PID pid]",
    "desc": "Built-in Windows process management \u2014 list all processes with PID/session/memory details, filter by name/user/PID/session, kill processes by PID or image name, force-terminate hung processes",
    "exe": "taskkill.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/tasklist"
  },
  "tmuxp": {
    "added": "2026-06-30",
    "desc": "Session manager for tmux \u2014 manage multiple terminal sessions with YAML configs and workspace restoration",
    "exe": "tmuxp",
    "repo": "tmux-python/tmuxp",
    "stars": 5500,
    "url": "https://github.com/tmux-python/tmuxp"
  },
  "topgrade": {
    "added": "2026-08-14",
    "command": "topgrade [--dry-run] [--yes] [--only <steps>] [--disable <steps>] [--cleanup]",
    "desc": "topgrade detects and upgrades every package manager and tool on your system in a single pass: winget, scoop, chocolatey, pip, npm, cargo, Windows Update, and more. One command keeps the entire machine current \u2014 perfect for autonomous self-maintenance. Supports --dry-run to preview, --only/--disable to scope steps, and --yes for unattended runs.",
    "endpoints": {
      "/auto/topgrade/config": "GET \u2014 locate the topgrade config file",
      "/auto/topgrade/dry-run": "GET \u2014 preview what would be upgraded (no changes applied)",
      "/auto/topgrade/info": "Feature metadata, install status, version",
      "/auto/topgrade/ping": "Health check",
      "/auto/topgrade/run": "POST \u2014 run system-wide upgrades (optional only/disable step filters, cleanup)"
    },
    "exe": "topgrade",
    "install": {
      "scoop": "scoop install topgrade",
      "winget": "winget install topgrade-rs.topgrade"
    },
    "repo": "topgrade-rs/topgrade",
    "stars": 4391,
    "url": "https://github.com/topgrade-rs/topgrade"
  },
  "trippy": {
    "added": "2026-08-05",
    "command": "trip [OPTIONS] [TARGETS]...",
    "desc": "Network diagnostic tool combining traceroute and ping with MTR-style analysis. Supports JSON, CSV, pretty, markdown, and stream output modes. Works with ICMP, UDP, and TCP protocols.",
    "exe": "trip",
    "install": {
      "cargo": "cargo install trippy",
      "scoop": "scoop install trippy",
      "winget": "winget install fujiapple852.trippy"
    },
    "modes": [
      "tui      - Interactive terminal UI (default)",
      "stream   - Continuous stream of tracing data",
      "pretty   - Pretty text table report",
      "markdown - Markdown table report",
      "csv      - CSV report",
      "json     - JSON report",
      "dot      - Graphviz DOT output",
      "flows    - Display all flows",
      "silent   - No output, just run"
    ],
    "protocols": [
      "icmp",
      "udp",
      "tcp"
    ],
    "repo": "fujiapple852/trippy",
    "stars": 7459,
    "url": "https://github.com/fujiapple852/trippy"
  },
  "uv": {
    "added": "2026-08-22",
    "command": "uv [pip|run|tool|python|venv|sync|build] ...",
    "desc": "uv is an extremely fast Python package and project manager written in Rust \u2014 a single binary that replaces pip, pip-tools, virtualenv, pipx, and more. It installs dependencies 10-100x faster than pip, manages virtual environments, runs scripts with pinned dependencies (inline metadata), and installs managed Python toolchains. Ideal for CoAgent's own dependency management, self-healing Python environments, and running isolated tooling.",
    "endpoints": {
      "/auto/uv/pip_install": "POST \u2014 install packages (list or requirements file) via uv pip",
      "/auto/uv/run": "POST \u2014 run a command or Python script in a managed environment",
      "/auto/uv/info": "Feature metadata, install status, version",
      "/auto/uv/ping": "Health check"
    },
    "exe": "uv",
    "install": {
      "choco": "choco install uv",
      "scoop": "scoop install uv",
      "winget": "winget install astral-sh.uv"
    },
    "repo": "astral-sh/uv",
    "stars": 88966,
    "url": "https://github.com/astral-sh/uv"
  },
  "ventoy": {
    "added": "2026-07-24",
    "cli": "Ventoy2Disk.exe VTOYCLI /I|/U <disk> [options]",
    "cli_params": [
      "VTOYCLI",
      "/I",
      "/U",
      "/GPT",
      "/NOSB",
      "/Drive:",
      "/PhyDrive:"
    ],
    "desc": "Open source tool to create bootable USB drive for ISO/WIM/IMG/VHD(x)/EFI files. With Ventoy, you don't need to format the disk over and over, just copy ISO files to the USB drive and boot them.",
    "exe": "Ventoy2Disk.exe",
    "repo": "ventoy/Ventoy",
    "stars": 78216,
    "url": "https://github.com/ventoy/Ventoy"
  },
  "volatility3": {
    "added": "2026-08-19",
    "candidates": [
      "C:\\Python*\\Scripts\\vol.exe",
      "C:\\Program Files\\Python*\\Scripts\\vol.exe",
      "C:\\Users\\*\\AppData\\Local\\Programs\\Python\\Python*\\Scripts\\vol.exe",
      "C:\\Users\\*\\AppData\\Roaming\\Python\\Python*\\Scripts\\vol.exe"
    ],
    "command": "vol.py -f <memory.dump> <plugin> [plugin-args]",
    "desc": "Volatility 3 is the Volatility Foundation's open-source memory forensics framework. Analyze Windows/Linux/macOS memory dumps from the command line: enumerate processes, network connections, loaded modules, registry hives, command lines, and scan for injected code. Plugins are namespaced (windows.pslist, windows.netscan, windows.malfind, linux.pslist).",
    "exe": "vol.py",
    "install": {
      "pip": "pip install volatility3",
      "git": "git clone https://github.com/volatilityfoundation/volatility3"
    },
    "repo": "volatilityfoundation/volatility3",
    "stars": 4336,
    "url": "https://github.com/volatilityfoundation/volatility3"
  },
  "vssadmin": {
    "added": "2026-07-18",
    "command": "vssadmin <subcommand>",
    "desc": "Built-in Windows Volume Shadow Copy Service administration \u2014 list/create/delete volume shadow copies (snapshots), list providers, storage associations, eligible volumes, subscribed VSS writers, and resize shadow copy storage",
    "exe": "vssadmin.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/vssadmin"
  },
  "wevtutil": {
    "added": "2026-07-16",
    "command": "wevtutil <command> [args]",
    "desc": "Built-in Windows Event Log management \u2014 query, export, archive, and clear event logs from Application/System/Security channels; list log metadata, publishers, subscriptions, and log file paths",
    "exe": "wevtutil.exe",
    "repo": "microsoft/windows",
    "stars": 0,
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/wevtutil"
  },
  "win11debloat": {
    "added": "2026-07-22",
    "cli_params": [
      "RunDefaults",
      "RunDefaultsLite",
      "RunSavedSettings",
      "RemoveApps",
      "RemoveGamingApps",
      "ForceRemoveEdge",
      "DisableTelemetry",
      "DisableBing",
      "DisableCopilot",
      "DisableRecall",
      "DisableWidgets",
      "DisableNotifications",
      "DisableSuggestions",
      "EnableDarkMode",
      "ShowHiddenFolders",
      "ShowKnownFileExt",
      "RevertContextMenu",
      "TaskbarAlignLeft",
      "DisableFastStartup"
    ],
    "desc": "A simple PowerShell script that removes pre-installed apps, disables telemetry, and performs various changes to declutter and customize Windows.",
    "exe": "powershell.exe",
    "repo": "Raphire/Win11Debloat",
    "script": "Win11Debloat.ps1",
    "stars": 53444,
    "url": "https://github.com/Raphire/Win11Debloat"
  },
  "winchronicle": {
    "added": "2026-06-30",
    "desc": "Local-first Windows UI Automation memory for AI agents",
    "exe": "winchronicle",
    "repo": "YSCJRH/WinChronicle",
    "stars": 1,
    "url": "https://github.com/YSCJRH/WinChronicle"
  },
  "windows_ai_toolkit": {
    "added": "2026-06-30",
    "desc": "Windows AI integration tools and MCP servers for desktop automation on Windows",
    "exe": "windows_ai_toolkit",
    "repo": "microsoft/windows-ai-toolkit",
    "stars": 1200,
    "url": "https://github.com/microsoft/windows-ai-toolkit"
  },
  "windows_mcp": {
    "added": "2026-07-06",
    "command": "windows-mcp serve | uvx windows-mcp serve",
    "desc": "MCP Server for Computer Use in Windows \u2014 screenshot, click, type, PowerShell, file system, file system, and app control integration via SSE transport",
    "exe": "uvx",
    "repo": "CursorTouch/Windows-MCP",
    "stars": 6342,
    "url": "https://github.com/CursorTouch/Windows-MCP"
  },
  "winget_cli": {
    "added": "2026-07-07",
    "command": "winget <install|search|list|upgrade|uninstall|export|show>",
    "desc": "Windows Package Manager \u2014 search, install, upgrade, list, uninstall, export, and manage software packages via winget CLI",
    "exe": "winget.exe",
    "repo": "microsoft/winget-cli",
    "stars": 26130,
    "url": "https://github.com/microsoft/winget-cli"
  },
  "xh": {
    "added": "2026-08-14",
    "command": "xh [METHOD] <URL> [name:value headers] [name==value query] [--timeout N] [--follow]",
    "desc": "xh is a friendly and fast HTTP client (a modern curl replacement) written in Rust. Sends requests with clean, structured output, native JSON support, syntax-highlighted responses, and connection reuse that makes it much faster for repeated requests. Ideal for programmatic HTTP from CoAgent when curl is awkward or when you want prettier output.",
    "endpoints": {
      "/auto/xh/headers": "GET \u2014 fetch only response headers for a URL",
      "/auto/xh/info": "Feature metadata, install status, version",
      "/auto/xh/ping": "Health check",
      "/auto/xh/request": "POST \u2014 send an HTTP request (method, url, headers, query, body)"
    },
    "exe": "xh",
    "install": {
      "scoop": "scoop install xh",
      "winget": "winget install ducaale.xh"
    },
    "repo": "ducaale/xh",
    "stars": 8014,
    "url": "https://github.com/ducaale/xh"
  },
  "yq": {
    "added": "2026-08-17",
    "command": "yq [eval] [-p FORMAT] [-o FORMAT] '<expression>' [file]",
    "desc": "yq is a portable command-line processor for YAML, JSON, XML, CSV, TSV, TOML, HCL and properties. It is the jq-equivalent for structured data \u2014 query with jq-style expressions and convert between formats. Perfect for CoAgent to read/write configs and transform API payloads.",
    "endpoints": {
      "/auto/yq/convert": "POST \u2014 convert between YAML/JSON/XML/CSV/TSV/TOML/properties",
      "/auto/yq/info": "Feature metadata, install status, version",
      "/auto/yq/ping": "Health check",
      "/auto/yq/query": "POST \u2014 run a jq-style expression against input"
    },
    "exe": "yq",
    "install": {
      "scoop": "scoop install yq",
      "winget": "winget install mikefarah.yq"
    },
    "repo": "mikefarah/yq",
    "stars": 15842,
    "url": "https://github.com/mikefarah/yq"
  },
  "yt_dlp": {
    "added": "2026-07-11",
    "command": "yt-dlp <url> [options]",
    "desc": "Feature-rich command-line audio/video downloader \u2014 download from YouTube and 1000+ sites with format selection, playlist support, subtitles, and metadata embedding",
    "exe": "yt-dlp.exe",
    "repo": "yt-dlp/yt-dlp",
    "stars": 177236,
    "url": "https://github.com/yt-dlp/yt-dlp"
  },
  "zoxide": {
    "added": "2026-08-10",
    "command": "zoxide [query|add|remove|init] [args]",
    "desc": "zoxide is a smarter cd command, inspired by z and autojump. It remembers which directories you use most frequently, so you can jump to them in just a few keystrokes. Supports fzf integration for interactive selection.",
    "endpoints": {
      "/auto/zoxide/info": "Feature metadata, install status, version",
      "/auto/zoxide/list": "GET \u2014 list all tracked directories ranked by frecency",
      "/auto/zoxide/ping": "Health check",
      "/auto/zoxide/query": "POST \u2014 find best-matching directory for a pattern"
    },
    "exe": "zoxide",
    "install": {
      "scoop": "scoop install zoxide",
      "winget": "winget install ajeetdsouza.zoxide"
    },
    "repo": "ajeetdsouza/zoxide",
    "stars": 38583,
    "url": "https://github.com/ajeetdsouza/zoxide"
  },
  "miller": {
    "added": "2026-08-24",
    "command": "mlr --icsv --ojson <verb> [args]",
    "desc": "Miller (mlr) is like awk/sed/cut/join/sort for name-indexed data (CSV, TSV, tabular JSON, DKVP). Convert between formats, filter, aggregate, and reshape tabular data with a single verb chain. Ships a single statically-linked binary (mlr.exe).",
    "endpoints": {
      "/auto/miller/info": "Feature metadata, install status, version",
      "/auto/miller/ping": "Health check",
      "/auto/miller/convert": "POST \u2014 convert between CSV/TSV/JSON/etc.",
      "/auto/miller/stats": "POST \u2014 summary statistics for a column",
      "/auto/miller/process": "POST \u2014 run a Miller verb chain"
    },
    "exe": "mlr",
    "install": {
      "scoop": "scoop install main/miller",
      "winget": "winget install Miller.Miller"
    },
    "repo": "johnkerl/miller",
    "stars": 10002,
    "url": "https://github.com/johnkerl/miller"
  },
  "tokei": {
    "added": "2026-08-24",
    "command": "tokei [path] --output json",
    "desc": "Tokei counts lines of code \u2014 files, lines, code, comments, and blanks \u2014 grouped by language across 150+ languages. Emits JSON/YAML/CBOR for programmatic consumption. Very fast; handles nested comments and respects .gitignore.",
    "endpoints": {
      "/auto/tokei/info": "Feature metadata, install status, version",
      "/auto/tokei/ping": "Health check",
      "/auto/tokei/count": "POST \u2014 code statistics grouped by language",
      "/auto/tokei/languages": "GET \u2014 list recognized languages",
      "/auto/tokei/files": "POST \u2014 per-file breakdown"
    },
    "exe": "tokei",
    "install": {
      "scoop": "scoop install tokei",
      "winget": "winget install XAMPPRocky.tokei"
    },
    "repo": "XAMPPRocky/tokei",
    "stars": 14848,
    "url": "https://github.com/XAMPPRocky/tokei"
  },
  "jc": {
    "added": "2026-08-25",
    "command": "jc -p --<parser> [data on stdin]",
    "desc": "jc (JSON Convert) converts the output of popular command-line tools, file types, and common strings into structured JSON or YAML. Supports 100+ parsers including Windows ipconfig, netstat, and systeminfo. Pipe raw command output in, get clean JSON out \u2014 ideal for turning legacy text-based tools into machine-readable automation endpoints.",
    "endpoints": {
      "/auto/jc/info": "Feature metadata, install status, version",
      "/auto/jc/ping": "Health check",
      "/auto/jc/parse": "POST \u2014 convert command output text (or run a command via magic syntax) to JSON/YAML",
      "/auto/jc/parsers": "GET \u2014 list available parsers"
    },
    "exe": "jc",
    "install": {
      "pip": "pip install jc",
      "winget": "winget install KellyBrazil.jc"
    },
    "repo": "kellyjonbrazil/jc",
    "stars": 8666,
    "url": "https://github.com/kellyjonbrazil/jc"
  },
  "ruff": {
    "added": "2026-08-25",
    "command": "ruff check <path> --output-format json",
    "desc": "ruff is an extremely fast Python linter and formatter written in Rust (10-100x faster than alternatives). Lint with hundreds of rules, auto-fix violations, and format code \u2014 all with machine-readable JSON output ideal for code-review and self-improvement pipelines.",
    "endpoints": {
      "/auto/ruff/info": "Feature metadata, install status, version",
      "/auto/ruff/ping": "Health check",
      "/auto/ruff/check": "POST \u2014 lint a file/directory (JSON output, optional --fix, --select rules)",
      "/auto/ruff/format": "POST \u2014 format a file/directory (or check-only mode)",
      "/auto/ruff/rule": "GET \u2014 explain a lint rule by code"
    },
    "exe": "ruff",
    "install": {
      "pip": "pip install ruff",
      "scoop": "scoop install ruff",
      "winget": "winget install astral-sh.ruff"
    },
    "repo": "astral-sh/ruff",
    "stars": 49316,
    "url": "https://github.com/astral-sh/ruff"
  },
  "mise": {
    "added": "2026-08-26",
    "command": "mise <ls|current|tasks|exec|run> [args]",
    "desc": "mise-en-place is a polyglot developer tool version manager and task runner (successor to asdf/rtx). Pin per-project versions of Node, Python, Go, Rust, and hundreds more via mise.toml, run named tasks, and set env vars. Emits machine-readable JSON for ls/current/tasks \u2014 ideal for reproducible, script-driven tool setup and project automation.",
    "endpoints": {
      "/auto/mise/info": "Feature metadata, install status, version",
      "/auto/mise/ping": "Health check",
      "/auto/mise/list": "GET \u2014 list installed tools and versions as JSON",
      "/auto/mise/current": "GET \u2014 active tool versions for the current scope",
      "/auto/mise/tasks": "GET \u2014 list tasks defined in mise.toml",
      "/auto/mise/exec": "POST \u2014 run a command under a specific tool version",
      "/auto/mise/run": "POST \u2014 run a named task"
    },
    "exe": "mise",
    "install": {
      "scoop": "scoop install mise",
      "winget": "winget install jdx.mise"
    },
    "repo": "jdx/mise",
    "stars": 33057,
    "url": "https://github.com/jdx/mise"
  },
  "shellcheck": {
    "added": "2026-08-26",
    "command": "shellcheck -f json1 <script>",
    "desc": "ShellCheck is a static analysis tool for shell scripts. It detects syntax errors, semantic issues, and subtle bugs in sh/bash/dash/ksh scripts, with JSON/XML/GCC machine-readable output (json1 format) and auto-fix suggestions. Ideal for auditing scripts in CI and self-improvement pipelines.",
    "endpoints": {
      "/auto/shellcheck/info": "Feature metadata, install status, version",
      "/auto/shellcheck/ping": "Health check",
      "/auto/shellcheck/check": "POST \u2014 lint a shell script (provided as text) with JSON output",
      "/auto/shellcheck/file": "POST \u2014 lint a shell script file by path"
    },
    "exe": "shellcheck",
    "install": {
      "scoop": "scoop install shellcheck",
      "winget": "winget install koalaman.shellcheck"
    },
    "repo": "koalaman/shellcheck",
    "stars": 39929,
    "url": "https://github.com/koalaman/shellcheck"
  },
  "dust": {
    "added": "2026-08-28",
    "command": "dust -j <path>  (JSON disk usage)",
    "desc": "dust is a more intuitive version of du, written in Rust. It shows disk usage as a sorted tree and can emit machine-readable JSON (-j) with per-entry byte sizes and nested children — ideal for automated disk-space auditing and finding the largest files/directories.",
    "endpoints": {
      "/auto/dust/info": "Feature metadata, install status, version",
      "/auto/dust/ping": "Health check",
      "/auto/dust/usage": "POST — disk-usage JSON tree of a path (depth/min-size/apparent-size)",
      "/auto/dust/largest": "POST — top N largest files/directories as JSON"
    },
    "exe": "dust",
    "install": {
      "scoop": "scoop install dust",
      "winget": "winget install bootandy.dust"
    },
    "repo": "bootandy/dust",
    "stars": 12192,
    "url": "https://github.com/bootandy/dust"
  },
  "onefetch": {
    "added": "2026-08-28",
    "command": "onefetch --output json <repo-path>",
    "desc": "onefetch is a command-line Git information tool written in Rust. It summarizes a local repository (project info, language breakdown, commit/contributor stats, license, last change) entirely offline, with machine-readable JSON and YAML output for pipeline-friendly repo metadata.",
    "endpoints": {
      "/auto/onefetch/info": "Feature metadata, install status, version",
      "/auto/onefetch/ping": "Health check",
      "/auto/onefetch/repo": "POST — full repo metadata as JSON",
      "/auto/onefetch/languages": "POST — language breakdown of a repo"
    },
    "exe": "onefetch",
    "install": {
      "scoop": "scoop install onefetch",
      "winget": "winget install o2sh.onefetch"
    },
    "repo": "o2sh/onefetch",
    "stars": 12035,
    "url": "https://github.com/o2sh/onefetch"
  },
  "nushell": {
    "added": "2026-08-29",
    "command": "nu -c \"<script>\"",
    "desc": "Nushell is a modern structured-data shell. Every command emits typed values (tables, records, lists) rather than plain text, so pipelines transform structured data natively and can dump machine-readable JSON via `to json`. Ideal for parsing logs, querying CSV/JSON/YAML, and subprocess-driven data wrangling.",
    "endpoints": {
      "/auto/nushell/info": "Feature metadata, install status, version",
      "/auto/nushell/ping": "Health check",
      "/auto/nushell/eval": "POST - run a Nu script string via nu -c",
      "/auto/nushell/script": "POST - run a .nu script file by path",
      "/auto/nushell/query": "POST - run a Nu expression and return JSON"
    },
    "exe": "nu",
    "install": {
      "scoop": "scoop install nu",
      "winget": "winget install nushell.nushell"
    },
    "repo": "nushell/nushell",
    "stars": 40365,
    "url": "https://github.com/nushell/nushell"
  },
  "glow": {
    "added": "2026-08-29",
    "command": "glow -w <width> <file.md>",
    "desc": "glow renders Markdown directly in the terminal with themes, word-wrap, and pager support. It is fully non-interactive when output is piped or a file argument is given, making it a clean way to pretty-print READMEs, release notes, and issue bodies to styled terminal text from a subprocess.",
    "endpoints": {
      "/auto/glow/info": "Feature metadata, install status, version",
      "/auto/glow/ping": "Health check",
      "/auto/glow/render": "POST - render a Markdown string or file to styled terminal text",
      "/auto/glow/render_file": "POST - render a Markdown file by path"
    },
    "exe": "glow",
    "install": {
      "scoop": "scoop install glow",
      "winget": "winget install charmbracelet.glow"
    },
    "repo": "charmbracelet/glow",
    "stars": 27109,
    "url": "https://github.com/charmbracelet/glow"
  }
}

_STATE = None



def _find_tool(tool):
    meta = TOOLS.get(tool, {})
    exe = shutil.which(meta.get("exe", tool))
    if exe:
        return exe
    for c in meta.get("candidates", []):
        if "*" in c:
            m = glob.glob(c)
            if m:
                return m[0]
        elif os.path.isfile(c):
            return c
    return None


def _register_generic(app, require_auth, tool):
    meta = TOOLS.get(tool, {})
    def _info():
        info = dict(meta)
        exe = _find_tool(tool)
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            try:
                r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
                info["version"] = (r.stdout.strip() or r.stderr.strip()).split("\n")[0]
            except Exception:
                info["version"] = "unknown"
        return jsonify(info)
    def _ping():
        exe = _find_tool(tool)
        return jsonify({"status": "ok" if exe else "not_installed",
                         "feature": meta.get("repo", tool), "path": exe})
    app.add_url_rule(f"/auto/{tool}/info", endpoint=f"_auto_{tool}_info",
                      view_func=require_auth(_info), methods=["GET"])
    app.add_url_rule(f"/auto/{tool}/ping", endpoint=f"_auto_{tool}_ping",
                      view_func=require_auth(_ping), methods=["GET"])


# ---- relocated module-level constants / helpers / action handlers ----

def _h_aider_0():
    """Run aider headlessly against a git repo with a coding prompt.

        JSON body:
            cwd (str, required): Directory containing the code to edit.
            message (str, required): The coding task / prompt for the LLM.
            model (str, optional): Model to use (e.g. 'gpt-4o', 'claude-3-5-sonnet', 'deepseek').
                                   Defaults to aider's configured model.
            auto_commit (bool, optional): Let aider git-commit its edits. Default False.
            timeout (int, optional): Max seconds to wait. Default 300, max 1800.

        Requires an LLM API key in the environment (OPENAI_API_KEY, ANTHROPIC_API_KEY,
        DEEPSEEK_API_KEY, etc.) or aider's ~/.aider.conf.yml.
        """
    exe = _find_tool('aider')
    if not exe:
        return (jsonify({'error': 'aider is not installed', 'hint': 'Install with: pip install aider-install  (or pipx/uv)'}), 503)
    data = _json_body() or {}
    cwd = (data.get('cwd') or '').strip()
    message = (data.get('message') or '').strip()
    if not cwd:
        return (jsonify({'error': "Missing 'cwd' field"}), 400)
    if not message:
        return (jsonify({'error': "Missing 'message' field"}), 400)
    if not os.path.isdir(cwd):
        return (jsonify({'error': f'cwd does not exist or is not a directory: {cwd}'}), 400)
    model = (data.get('model') or '').strip()
    timeout = data.get('timeout', 300)
    try:
        timeout = max(10, min(int(timeout), 1800))
    except (ValueError, TypeError):
        timeout = 300
    cmd = [exe, '--yes']
    if not data.get('auto_commit'):
        cmd += ['--no-git', '--no-auto-commits']
    if model:
        cmd += ['--model', model]
    cmd += ['--message', message]
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return jsonify({'ok': r.returncode == 0, 'returncode': r.returncode, 'cwd': cwd, 'model': model or 'default', 'stdout': r.stdout[-4000:], 'stderr': r.stderr[-4000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'aider timed out after {timeout}s', 'cwd': cwd}), 504)
    except Exception as e:
        _log(f"[auto_aider_run] {f'Unexpected error: {e}'}")
        return (jsonify({'error': str(e)}), 500)

def _autohotkey__find_ahk2exe():
    return shutil.which('Ahk2Exe.exe') or shutil.which('ahk2exe')

def _autohotkey__clean_script(value):
    script = str(value or '').strip()
    if not script:
        raise ValueError('script must not be empty')
    if '\x00' in script:
        raise ValueError('script cannot contain null bytes')
    if len(script) > 65536:
        raise ValueError('script exceeds max length (65536 chars)')
    return script

def _autohotkey__clean_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes')
    if isinstance(value, (int, float)):
        return bool(value)
    return False

def _h_autohotkey_1():
    data = _json_body()
    missing = _missing_field(data, 'script')
    if missing:
        return missing
    exe = _find_tool('autohotkey')
    if not exe:
        return (jsonify({'ok': False, 'error': 'AutoHotkey not found on PATH', 'hint': 'Install AutoHotkey from https://www.autohotkey.com/'}), 503)
    try:
        script = _autohotkey__clean_script(data.get('script'))
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    wait = _autohotkey__clean_bool(data.get('wait', True))
    timeout_sec = 30
    try:
        timeout_sec = max(1, min(int(data.get('timeout', 30)), 120))
    except (TypeError, ValueError):
        timeout_sec = 30
    tmp_ahk = None
    try:
        fd, tmp_ahk = tempfile.mkstemp(suffix='.ahk', prefix='coagent_')
        os.close(fd)
        with open(tmp_ahk, 'w', encoding='utf-8') as f:
            f.write(script)
        cmd = [exe, tmp_ahk]
        if wait:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
                try:
                    stdout, stderr = proc.communicate(timeout=timeout_sec)
                    ok = proc.returncode == 0
                    _log(f'[autohotkey] script exit={proc.returncode}')
                    return (jsonify({'ok': ok, 'exit_code': proc.returncode, 'stdout': stdout, 'stderr': stderr}), 200 if ok else 502)
                except subprocess.TimeoutExpired:
                    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                        subprocess.run(['taskkill', '/f', '/t', '/pid', str(proc.pid)], capture_output=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        proc.kill()
                    proc.communicate()
                    _log(f'[autohotkey] script timed out after {timeout_sec}s')
                    return (jsonify({'ok': False, 'error': 'AutoHotkey script timed out'}), 504)
            except OSError as exc:
                _log(f'[autohotkey] launch failed: {exc}')
                return (jsonify({'ok': False, 'error': str(exc)}), 500)
        else:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
                _log(f'[autohotkey] launched detached pid={proc.pid}')
                return jsonify({'ok': True, 'pid': proc.pid, 'message': 'Script launched in background'})
            except OSError as exc:
                _log(f'[autohotkey] detached launch failed: {exc}')
                return (jsonify({'ok': False, 'error': str(exc)}), 500)
    finally:
        if tmp_ahk and os.path.exists(tmp_ahk):
            try:
                os.unlink(tmp_ahk)
            except OSError:
                pass

def _h_autohotkey_2():
    data = _json_body()
    missing = _missing_field(data, 'script')
    if missing:
        return missing
    compiler = _autohotkey__find_ahk2exe()
    if not compiler:
        return (jsonify({'ok': False, 'error': 'Ahk2Exe compiler not found', 'hint': 'Install AutoHotkey with compiler from https://www.autohotkey.com/'}), 503)
    try:
        script = _autohotkey__clean_script(data.get('script'))
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    out_name = str(data.get('output', 'coagent_script.exe')).strip()
    out_name = os.path.basename(out_name)
    if not out_name.lower().endswith('.exe') or out_name in ('.exe', ''):
        out_name = 'coagent_script.exe'
    tmp_ahk = None
    tmp_exe = None
    try:
        fd1, tmp_ahk = tempfile.mkstemp(suffix='.ahk', prefix='coagent_')
        os.close(fd1)
        with open(tmp_ahk, 'w', encoding='utf-8') as f:
            f.write(script)
        tmp_exe = os.path.join(tempfile.gettempdir(), out_name)
        cmd = [compiler, '/in', tmp_ahk, '/out', tmp_exe]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            _log('[autohotkey] compilation timed out')
            return (jsonify({'ok': False, 'error': 'Compilation timed out after 60s'}), 504)
        except OSError as exc:
            _log(f'[autohotkey] compiler launch failed: {exc}')
            return (jsonify({'ok': False, 'error': str(exc)}), 500)
        ok = result.returncode == 0 and os.path.exists(tmp_exe)
        exe_size = os.path.getsize(tmp_exe) if ok else 0
        _log(f'[autohotkey] compile exit={result.returncode} size={exe_size}')
        if not ok and tmp_exe and os.path.exists(tmp_exe):
            try:
                os.unlink(tmp_exe)
            except OSError:
                pass
        return (jsonify({'ok': ok, 'exit_code': result.returncode, 'output': tmp_exe, 'size_bytes': exe_size, 'stderr': result.stderr}), 200 if ok else 502)
    finally:
        if tmp_ahk and os.path.exists(tmp_ahk):
            try:
                os.unlink(tmp_ahk)
            except OSError:
                pass

def _h_bat_3():
    """Read a file with bat syntax highlighting (plain text output)."""
    exe = _find_tool('bat')
    if not exe:
        return (jsonify({'error': 'bat not installed', 'hint': 'Install with: winget install sharkdp.bat'}), 503)
    body = _json_body()
    filepath = body.get('file')
    if not filepath:
        return _missing_field('file')
    if not os.path.isfile(filepath):
        return (jsonify({'error': f'File not found: {filepath}'}), 404)
    try:
        max_lines = int(body.get('max_lines', 500))
    except (TypeError, ValueError):
        max_lines = 500
    max_lines = max(0, max_lines)
    line_range = body.get('line_range', None)
    show_line_numbers = body.get('line_numbers', True)
    language = body.get('language', None)
    theme = body.get('theme', 'ansi')
    cmd = [exe, '--color=never', '--paging=never', '--style=full' if show_line_numbers else '--style=plain']
    if line_range:
        cmd.extend(['--line-range', line_range])
    if language:
        cmd.extend(['--language', language])
    if theme and theme != 'ansi':
        cmd.extend(['--theme', theme])
    cmd.extend(['--', filepath])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = r.stdout.split('\n')
        total = len(lines)
        truncated = total > max_lines
        return jsonify({'file': filepath, 'lines': lines[:max_lines], 'total_lines': total, 'truncated': truncated, 'language': language or 'auto'})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'bat timed out reading file'}), 504)

def _h_bat_4():
    """List all supported languages."""
    exe = _find_tool('bat')
    if not exe:
        return (jsonify({'error': 'bat not installed'}), 503)
    try:
        r = subprocess.run([exe, '--list-languages'], capture_output=True, text=True, timeout=5)
        languages = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
        return jsonify({'languages': languages, 'count': len(languages)})
    except Exception as e:
        return (jsonify({'error': str(e)}), 500)

def _h_bat_5():
    """List all available themes."""
    exe = _find_tool('bat')
    if not exe:
        return (jsonify({'error': 'bat not installed'}), 503)
    try:
        r = subprocess.run([exe, '--list-themes'], capture_output=True, text=True, timeout=5)
        themes = [t.strip() for t in r.stdout.strip().split('\n') if t.strip()]
        return jsonify({'themes': themes, 'count': len(themes)})
    except Exception as e:
        return (jsonify({'error': str(e)}), 500)

_bitsadmin_JOB_STATE_MAP = {'QUEUED': 'queued', 'CONNECTING': 'connecting', 'TRANSFERRING': 'transferring', 'SUSPENDED': 'suspended', 'ERROR': 'error', 'TRANSIENT_ERROR': 'transient_error', 'TRANSFERRED': 'transferred', 'ACKNOWLEDGED': 'acknowledged', 'CANCELLED': 'cancelled'}

_bitsadmin_JOB_TYPE_MAP = {'DOWNLOAD': 'download', 'UPLOAD': 'upload', 'UPLOAD-REPLY': 'upload_reply'}

def _bitsadmin__parse_job_info(output):
    """Parse INFO output into structured dict."""
    info = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or ':' not in stripped:
            continue
        parts = stripped.split(':', 1)
        key = parts[0].strip()
        val = parts[1].strip()
        info[key] = val
    return info

def _bitsadmin__parse_job_state(state_str):
    """Normalize job state string."""
    s = state_str.strip().upper()
    return _bitsadmin_JOB_STATE_MAP.get(s, s.lower())

def _bitsadmin__bad_handle(value):
    """Return True if a job handle/name would be re-interpreted as a
    bitsadmin switch (flag injection)."""
    if not isinstance(value, str):
        return True
    v = value.strip()
    if not v or v.startswith(('/', '-')):
        return True
    return any((ord(c) < 32 for c in v))

def _bitsadmin__parse_job_line(line):
    """Parse a single line from bitsadmin /LIST /VERBOSE output."""
    result = {}
    line = line.strip()
    if line.startswith('{'):
        parts = line.split('}', 1)
        if len(parts) >= 2:
            result['job_id'] = parts[0] + '}'
            rest = parts[1].strip()
            for t, tname in sorted(_bitsadmin_JOB_TYPE_MAP.items(), key=lambda kv: -len(kv[0])):
                if rest.startswith(t):
                    result['type'] = tname
                    rest = rest[len(t):].strip()
                    break
            if rest and (not rest.startswith('{')):
                result['display_name'] = rest
    return result

def _bitsadmin__run_bitsadmin(args, timeout=30):
    """Run bitsadmin.exe with given args, return output or raise."""
    exe = _find_tool('bitsadmin')
    if not exe:
        raise RuntimeError('bitsadmin.exe not found on system')
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('bitsadmin operation timed out')
    except OSError as e:
        raise RuntimeError(f'bitsadmin execution failed: {e}')
    if result.returncode != 0:
        stderr = (result.stderr or '').strip()
        raise RuntimeError(stderr or 'bitsadmin returned non-zero exit code')
    return result.stdout

def _h_bitsadmin_6():
    """List all BITS transfer jobs."""
    try:
        output = _bitsadmin__run_bitsadmin(['/LIST', '/VERBOSE'], timeout=15)
        jobs = []
        current_job = {}
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                if current_job:
                    jobs.append(current_job)
                    current_job = {}
                continue
            parsed = _bitsadmin__parse_job_line(stripped)
            if parsed:
                if current_job:
                    jobs.append(current_job)
                current_job = parsed
                continue
            if ':' in stripped:
                parts = stripped.split(':', 1)
                key = parts[0].strip()
                val = parts[1].strip()
                if key and val:
                    current_job[key] = val
        if current_job:
            jobs.append(current_job)
        return jsonify({'ok': True, 'jobs': jobs, 'count': len(jobs), 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_7():
    """Get detailed info about a specific BITS job by name or GUID."""
    body = _json_body()
    job_id = str(body.get('job_id') or '').strip()
    if not job_id:
        return _missing_field('job_id')
    if _bitsadmin__bad_handle(job_id):
        return (jsonify({'ok': False, 'error': "invalid job_id (must not start with '/' or '-')"}), 400)
    try:
        output = _bitsadmin__run_bitsadmin(['/INFO', job_id, '/VERBOSE'], timeout=15)
        info = _bitsadmin__parse_job_info(output)
        state_key = next((k for k in info if k.lower() == 'state'), None)
        if state_key:
            info['state'] = _bitsadmin__parse_job_state(info[state_key])
        return jsonify({'ok': True, 'job_id': job_id, 'info': info, 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_8():
    """Create a new BITS transfer job."""
    body = _json_body()
    name = str(body.get('name') or '').strip()
    if not name:
        return _missing_field('name')
    if _bitsadmin__bad_handle(name):
        return (jsonify({'ok': False, 'error': "invalid name (must not start with '/' or '-')"}), 400)
    job_type = str(body.get('type') or 'download').strip().lower()
    if job_type not in ('download', 'upload', 'upload_reply'):
        return (jsonify({'ok': False, 'error': f"Invalid type '{job_type}'. Must be 'download', 'upload', or 'upload_reply'"}), 400)
    type_flag = f"/{job_type.upper().replace('_', '-')}"
    try:
        output = _bitsadmin__run_bitsadmin(['/CREATE', type_flag, name], timeout=15)
        return jsonify({'ok': True, 'name': name, 'type': job_type, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_9():
    """Add a file to an existing BITS job."""
    body = _json_body()
    job_id = str(body.get('job_id') or '').strip()
    if not job_id:
        return _missing_field('job_id')
    if _bitsadmin__bad_handle(job_id):
        return (jsonify({'ok': False, 'error': "invalid job_id (must not start with '/' or '-')"}), 400)
    remote_url = str(body.get('remote_url') or '').strip()
    if not remote_url:
        return _missing_field('remote_url')
    if not (remote_url.lower().startswith('http://') or remote_url.lower().startswith('https://')):
        return (jsonify({'ok': False, 'error': 'remote_url must be http:// or https://'}), 400)
    local_path = str(body.get('local_path') or '').strip()
    if not local_path:
        return _missing_field('local_path')
    if _bitsadmin__bad_handle(local_path):
        return (jsonify({'ok': False, 'error': "invalid local_path (must not start with '/' or '-')"}), 400)
    try:
        output = _bitsadmin__run_bitsadmin(['/ADDFILE', job_id, remote_url, local_path], timeout=15)
        return jsonify({'ok': True, 'job_id': job_id, 'remote_url': remote_url, 'local_path': local_path, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_10():
    """Resume a suspended BITS job."""
    body = _json_body()
    job_id = str(body.get('job_id') or '').strip()
    if not job_id:
        return _missing_field('job_id')
    if _bitsadmin__bad_handle(job_id):
        return (jsonify({'ok': False, 'error': "invalid job_id (must not start with '/' or '-')"}), 400)
    try:
        output = _bitsadmin__run_bitsadmin(['/RESUME', job_id], timeout=15)
        return jsonify({'ok': True, 'job_id': job_id, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_11():
    """Suspend an active BITS job."""
    body = _json_body()
    job_id = str(body.get('job_id') or '').strip()
    if not job_id:
        return _missing_field('job_id')
    if _bitsadmin__bad_handle(job_id):
        return (jsonify({'ok': False, 'error': "invalid job_id (must not start with '/' or '-')"}), 400)
    try:
        output = _bitsadmin__run_bitsadmin(['/SUSPEND', job_id], timeout=15)
        return jsonify({'ok': True, 'job_id': job_id, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_12():
    """Cancel a BITS job."""
    body = _json_body()
    job_id = str(body.get('job_id') or '').strip()
    if not job_id:
        return _missing_field('job_id')
    if _bitsadmin__bad_handle(job_id):
        return (jsonify({'ok': False, 'error': "invalid job_id (must not start with '/' or '-')"}), 400)
    try:
        output = _bitsadmin__run_bitsadmin(['/CANCEL', job_id], timeout=15)
        return jsonify({'ok': True, 'job_id': job_id, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_13():
    """Complete a transferred BITS job."""
    body = _json_body()
    job_id = str(body.get('job_id') or '').strip()
    if not job_id:
        return _missing_field('job_id')
    if _bitsadmin__bad_handle(job_id):
        return (jsonify({'ok': False, 'error': "invalid job_id (must not start with '/' or '-')"}), 400)
    try:
        output = _bitsadmin__run_bitsadmin(['/COMPLETE', job_id], timeout=15)
        return jsonify({'ok': True, 'job_id': job_id, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_14():
    """List files in a BITS job."""
    body = _json_body()
    job_id = str(body.get('job_id') or '').strip()
    if not job_id:
        return _missing_field('job_id')
    if _bitsadmin__bad_handle(job_id):
        return (jsonify({'ok': False, 'error': "invalid job_id (must not start with '/' or '-')"}), 400)
    try:
        output = _bitsadmin__run_bitsadmin(['/LISTFILES', job_id], timeout=15)
        return jsonify({'ok': True, 'job_id': job_id, 'output': output, 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_15():
    """Monitor the BITS transfer manager."""
    try:
        output = _bitsadmin__run_bitsadmin(['/MONITOR'], timeout=10)
        return jsonify({'ok': True, 'output': output, 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_16():
    """Delete BITS jobs. Requires explicit confirmation; per-user by default."""
    body = _json_body()
    if body.get('confirm') is not True:
        return (jsonify({'ok': False, 'error': 'confirm=true is required to reset BITS jobs'}), 400)
    args = ['/RESET']
    if body.get('all_users') is True:
        args.append('/ALLUSERS')
    try:
        output = _bitsadmin__run_bitsadmin(args, timeout=30)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_17():
    """Get BITS cache information."""
    try:
        output = _bitsadmin__run_bitsadmin(['/CACHE', '/INFO'], timeout=10)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_18():
    """Delete items from BITS cache."""
    body = _json_body()
    record_id = str(body.get('record_id') or '').strip()
    if record_id and (not record_id.replace('-', '').isalnum()):
        return (jsonify({'ok': False, 'error': 'invalid record_id (digits/hex only)'}), 400)
    try:
        args = ['/CACHE', '/DELETE']
        if record_id:
            args.append(f'/RecordID={record_id}')
        output = _bitsadmin__run_bitsadmin(args, timeout=15)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_bitsadmin_19():
    """List BITS peers."""
    try:
        output = _bitsadmin__run_bitsadmin(['/PEERS', '/LIST'], timeout=10)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

_certutil_HASH_ALGOS = ['MD5', 'SHA1', 'SHA256', 'SHA384', 'SHA512', 'SM3']

def _certutil__run_certutil(args, timeout=30):
    """Run certutil.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('certutil')
    if not exe:
        raise RuntimeError('certutil.exe not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _certutil__parse_store_output(output):
    """Parse certutil -store output into certificate listing."""
    certs = []
    current_cert = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if '====' in stripped:
            if current_cert:
                certs.append(current_cert)
                current_cert = {}
            continue
        if stripped.startswith('Subject:'):
            current_cert['subject'] = stripped[8:].strip()
        elif stripped.startswith('Issuer:'):
            current_cert['issuer'] = stripped[7:].strip()
        elif stripped.startswith('Serial Number:'):
            current_cert['serial'] = stripped[14:].strip()
        elif stripped.startswith('NotBefore:'):
            current_cert['not_before'] = stripped[10:].strip()
        elif stripped.startswith('NotAfter:'):
            current_cert['not_after'] = stripped[9:].strip()
        elif '=' in stripped:
            key, val = stripped.split('=', 1)
            current_cert[key.strip()] = val.strip()
    if current_cert:
        certs.append(current_cert)
    return certs

def _certutil__parse_hash_output(output):
    """Parse certutil -hashfile output into structured result."""
    lines = output.strip().splitlines()
    if len(lines) >= 2:
        algo_line = lines[0].strip().split()[0] if lines[0].strip() else ''
        hash_value = lines[1].strip()
        return (algo_line, hash_value)
    return (None, output.strip())

def _h_certutil_20():
    """Compute file hash using certutil -hashfile."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    filepath = str(body.get('file') or '').strip()
    algorithm = str(body.get('algorithm') or 'SHA256').strip().upper()
    if not filepath:
        return _missing_field('file')
    if algorithm not in _certutil_HASH_ALGOS:
        return (jsonify({'ok': False, 'error': f"unsupported hash algorithm '{algorithm}'. Supported: {', '.join(_certutil_HASH_ALGOS)}"}), 400)
    if not os.path.isfile(filepath):
        return (jsonify({'ok': False, 'error': f'file not found: {filepath}'}), 404)
    if filepath.startswith('/mnt/'):
        parts = filepath.split('/')
        if len(parts) >= 3 and len(parts[2]) == 1:
            drive = parts[2].upper()
            win_path = f'{drive}:\\' + '\\'.join(parts[3:])
            filepath = win_path
    try:
        stdout, stderr, rc = _certutil__run_certutil(['-hashfile', filepath, algorithm], timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'certutil hashfile failed', 'exit_code': rc}), 502)
        algo, hash_val = _certutil__parse_hash_output(stdout)
        return jsonify({'ok': True, 'file': filepath, 'algorithm': algo or algorithm, 'hash': hash_val})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'certutil hash timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_certutil_21():
    """Encode a file to Base64 using certutil -encode."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    filepath = str(body.get('file') or '').strip()
    if not filepath:
        return _missing_field('file')
    if filepath.startswith('/mnt/'):
        parts = filepath.split('/')
        if len(parts) >= 3 and len(parts[2]) == 1:
            drive = parts[2].upper()
            win_path = f'{drive}:\\' + '\\'.join(parts[3:])
            filepath = win_path
    import tempfile
    fd, tmpfile = tempfile.mkstemp(suffix='.b64')
    os.close(fd)
    try:
        stdout, stderr, rc = _certutil__run_certutil(['-encode', filepath, tmpfile], timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'certutil encode failed', 'exit_code': rc}), 502)
        if os.path.isfile(tmpfile):
            with open(tmpfile, 'r') as f:
                encoded = f.read()
        else:
            encoded = ''
        return jsonify({'ok': True, 'file': filepath, 'encoded': encoded})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'certutil encode timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass

def _h_certutil_22():
    """Decode a Base64 file using certutil -decode."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    encoded_file = str(body.get('encoded_file') or '').strip()
    if not encoded_file:
        return _missing_field('encoded_file')
    output_file = str(body.get('output_file') or '').strip()
    auto_generated = False
    if not output_file:
        import tempfile
        fd, output_file = tempfile.mkstemp(suffix='.decoded')
        os.close(fd)
        auto_generated = True
    keep_output = False
    try:
        stdout, stderr, rc = _certutil__run_certutil(['-decode', encoded_file, output_file], timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'certutil decode failed', 'exit_code': rc}), 502)
        file_size = os.path.getsize(output_file) if os.path.isfile(output_file) else 0
        keep_output = True
        return jsonify({'ok': True, 'input': encoded_file, 'output': output_file, 'size_bytes': file_size})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'certutil decode timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    finally:
        if auto_generated and (not keep_output):
            try:
                os.unlink(output_file)
            except OSError:
                pass

def _h_certutil_23():
    """List certificates in a store (default: MY/CurrentUser)."""
    from flask import request
    store_name = request.args.get('store', 'My')
    store_location = request.args.get('location', 'CurrentUser')
    try:
        stdout, stderr, rc = _certutil__run_certutil(['-store', store_location, store_name], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'certutil store query failed', 'exit_code': rc}), 502)
        certs = _certutil__parse_store_output(stdout)
        return jsonify({'ok': True, 'store': f'{store_location}\\{store_name}', 'certificates': certs, 'count': len(certs)})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'certutil store query timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_certutil_24():
    """Generate a certificate signing request (CSR) using an existing INF file."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    inf_file = str(body.get('inf_file') or '').strip()
    output_file = str(body.get('output_file') or '').strip()
    if not inf_file:
        return _missing_field('inf_file')
    args = ['-newreq']
    if output_file:
        args.extend([output_file, inf_file])
    else:
        args.append(inf_file)
    try:
        stdout, stderr, rc = _certutil__run_certutil(args, timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'certutil -newreq failed', 'exit_code': rc}), 502)
        return jsonify({'ok': True, 'inf_file': inf_file, 'output_file': output_file or '(auto-generated)', 'stdout': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'certutil CSR generation timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _chkdsk__run_chkdsk(args, timeout=120, input_text=None):
    """Run chkdsk.exe with given args, return parsed output or raise."""
    exe = _find_tool('chkdsk')
    if not exe:
        raise RuntimeError('chkdsk.exe not found on system')
    kwargs = {}
    if input_text is not None:
        kwargs['input'] = input_text
    else:
        kwargs['stdin'] = subprocess.DEVNULL
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError('chkdsk operation timed out')
    except OSError as e:
        raise RuntimeError(f'chkdsk execution failed: {e}')
    if result.returncode != 0:
        stderr = (result.stderr or '').strip()
        raise RuntimeError(stderr or 'chkdsk returned non-zero exit code')
    return result.stdout

def _chkdsk__sanitize_volume(volume):
    """Validate a chkdsk volume, rejecting flag-like inputs."""
    v = (volume or '').strip().rstrip('\\')
    if not v:
        raise ValueError('volume must not be empty')
    if v.startswith(('/', '-')):
        raise ValueError(f'invalid volume: {v}')
    return v

def _chkdsk__parse_chkdsk_output(output):
    """Extract key statistics from chkdsk output."""
    result = {'raw_output': output, 'parsed': {}}
    patterns = [('files_total', '(\\d+)\\s+file\\w+\\s+processed', 1), ('folders_total', '(\\d+)\\s+((folder|directory)\\w+)\\s+processed', 1), ('total_disk_space', '(\\d[\\d,]*)\\s+KB\\s+total\\s+disk\\s+space', 1), ('bad_sectors', '(\\d+)\\s+KB\\s+in\\s+bad\\s+sectors', 1), ('in_use_files', '(\\d+)\\s+file\\w+\\s+indexed', 1), ('log_file_size', '(\\d+)\\s+KB\\s+in\\s+log\\s+file', 1), ('available_space', '(\\d[\\d,]*)\\s+KB\\s+available', 1), ('allocation_units', '(\\d[\\d,]*)\\s+allocation\\s+units', 1), ('errors_found', '(\\d+)\\s+(error|problem)\\w+\\s+found', 1), ('bad_in_user_file', '(\\d+)\\s+KB\\s+in\\s+bad\\s+sectors\\s+in\\s+user\\s+files', 1), ('file_system_type', '(The type of the file system is\\s*:\\s*(\\w+))', 2), ('volume_name', '(Volume label is\\s*(\\w[\\w ]*)\\s*\\.)', 2), ('stage', '(Stage\\s+\\d+:\\s+.+)', 1), ('fs_state', '(Windows has scanned the file system and found no problems|Windows has found problems with the file system)', 1)]
    for key, pattern, group in patterns:
        m = re.search(pattern, output, re.IGNORECASE)
        if m:
            val = m.group(group).strip()
            try:
                val = int(val.replace(',', '').replace('.', ''))
            except (ValueError, AttributeError):
                pass
            result['parsed'][key] = val
    return result

def _h_chkdsk_25():
    """Run a read-only scan on a volume (no repair) — safe, non-destructive."""
    body = _json_body()
    try:
        volume = _chkdsk__sanitize_volume(body.get('volume') or 'C:')
    except ValueError as e:
        return (jsonify({'ok': False, 'volume': None, 'error': str(e)}), 400)
    try:
        output = _chkdsk__run_chkdsk([volume], timeout=120)
        parsed = _chkdsk__parse_chkdsk_output(output)
        return jsonify({'ok': True, 'volume': volume, 'parsed': parsed})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'volume': volume, 'error': str(e)}), 503)

def _h_chkdsk_26():
    """Schedule a repair scan (/F) — may require volume dismount or next boot."""
    body = _json_body()
    try:
        volume = _chkdsk__sanitize_volume(body.get('volume') or 'C:')
    except ValueError as e:
        return (jsonify({'ok': False, 'volume': None, 'error': str(e)}), 400)
    try:
        output = _chkdsk__run_chkdsk([volume, '/F'], timeout=300)
        parsed = _chkdsk__parse_chkdsk_output(output)
        return jsonify({'ok': True, 'volume': volume, 'parsed': parsed})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'volume': volume, 'error': str(e)}), 503)

def _h_chkdsk_27():
    """Run a thorough scan (/R) — locates bad sectors and recovers readable info."""
    body = _json_body()
    try:
        volume = _chkdsk__sanitize_volume(body.get('volume') or 'C:')
    except ValueError as e:
        return (jsonify({'ok': False, 'volume': None, 'error': str(e)}), 400)
    try:
        output = _chkdsk__run_chkdsk([volume, '/R'], timeout=600)
        parsed = _chkdsk__parse_chkdsk_output(output)
        return jsonify({'ok': True, 'volume': volume, 'parsed': parsed})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'volume': volume, 'error': str(e)}), 503)

def _h_chkdsk_28():
    """Force dismount before scan (/X) — useful for non-system volumes."""
    body = _json_body()
    try:
        volume = _chkdsk__sanitize_volume(body.get('volume') or 'D:')
    except ValueError as e:
        return (jsonify({'ok': False, 'volume': None, 'error': str(e)}), 400)
    try:
        output = _chkdsk__run_chkdsk([volume, '/X', '/F'], timeout=300)
        parsed = _chkdsk__parse_chkdsk_output(output)
        return jsonify({'ok': True, 'volume': volume, 'parsed': parsed})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'volume': volume, 'error': str(e)}), 503)

def _h_chkdsk_29():
    """Schedule chkdsk to run on next boot (for system volumes in use)."""
    body = _json_body()
    try:
        volume = _chkdsk__sanitize_volume(body.get('volume') or 'C:')
    except ValueError as e:
        return (jsonify({'ok': False, 'volume': None, 'error': str(e)}), 400)
    try:
        output = _chkdsk__run_chkdsk([volume, '/F', '/R'], timeout=30, input_text='Y\n')
        parsed = _chkdsk__parse_chkdsk_output(output)
        return jsonify({'ok': True, 'volume': volume, 'parsed': parsed})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'volume': volume, 'error': str(e)}), 503)

def _h_chkdsk_30():
    """List available volumes via a single wmic logicaldisk query."""
    try:
        result = subprocess.run(['wmic', 'logicaldisk', 'get', 'DeviceID,VolumeName,FileSystem,Size,FreeSpace', '/format:csv'], capture_output=True, text=True, timeout=15)
        drives = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith('Node') or line.startswith(','):
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                drives.append({'volume': parts[1].strip() if len(parts) > 1 else '', 'filesystem': parts[2].strip() if len(parts) > 2 else '', 'free_bytes': parts[3].strip() if len(parts) > 3 else '', 'size_bytes': parts[4].strip() if len(parts) > 4 else '', 'label': parts[5].strip() if len(parts) > 5 else ''})
        return jsonify({'ok': True, 'volumes': drives})
    except Exception as e:
        return (jsonify({'ok': False, 'error': str(e)}), 500)

def _choco__clean_package_name(value):
    """Validate and sanitize a Chocolatey package name/ID."""
    name = str(value or '').strip()
    if not name:
        raise ValueError('package name must not be empty')
    if len(name) > 256:
        raise ValueError('package name too long (max 256 chars)')
    if '\x00' in name:
        raise ValueError('package name cannot contain null bytes')
    if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9._-]*', name):
        raise ValueError(f'package name contains invalid characters: {name!r}')
    return name

def _h_choco_31():
    """Search for packages on Chocolatey community feed."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    query = body.get('query', '')
    try:
        query = _choco__clean_package_name(query) if query else query
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    if not query:
        return _missing_field('query')
    exe = _find_tool('choco')
    if not exe:
        return (jsonify({'ok': False, 'error': 'choco not found'}), 503)
    try:
        result = subprocess.run([exe, 'search', query, '--limit', '30'], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'search failed'}), 502)
        return jsonify({'ok': True, 'query': query, 'raw_output': result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'choco search timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_choco_32():
    """List locally installed Chocolatey packages."""
    exe = _find_tool('choco')
    if not exe:
        return (jsonify({'ok': False, 'error': 'choco not found'}), 503)
    try:
        result = subprocess.run([exe, 'list', '--local-only'], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'list failed'}), 502)
        packages = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line or 'packages installed' in line or ('chocolatey' in line.lower() and 'v' in line):
                continue
            parts = line.split()
            if len(parts) >= 2:
                version = parts[1]
                if version.startswith('v'):
                    version = version[1:]
                packages.append({'name': parts[0], 'version': version})
            elif parts:
                packages.append({'name': parts[0], 'version': ''})
        return jsonify({'ok': True, 'count': len(packages), 'packages': packages})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'choco list timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_choco_33():
    """Install a package via Chocolatey."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    package_name = body.get('package_name', '')
    try:
        package_name = _choco__clean_package_name(package_name)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('choco')
    if not exe:
        return (jsonify({'ok': False, 'error': 'choco not found'}), 503)
    version = body.get('version', '')
    force = body.get('force') is True
    params = body.get('params', '')
    install_args = body.get('install_args', '')
    cmd = [exe, 'install', package_name, '-y']
    if version:
        cmd.extend(['--version', version])
    if force:
        cmd.append('--force')
    if params:
        cmd.extend(['--params', params])
    if install_args:
        cmd.extend(['--install-arguments', install_args])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return jsonify({'ok': result.returncode == 0, 'package_name': package_name, 'version': version or 'latest', 'exit_code': result.returncode, 'stdout': result.stdout.strip()[-2000:], 'stderr': result.stderr.strip()[-1000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'choco install timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_choco_34():
    """Upgrade a package (or all packages) via Chocolatey."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    package_name = body.get('package_name', '')
    if package_name:
        try:
            package_name = _choco__clean_package_name(package_name)
        except ValueError as e:
            return (jsonify({'ok': False, 'error': str(e)}), 400)
    elif body.get('all') is not True:
        return (jsonify({'ok': False, 'error': 'package_name required, or set all=true to upgrade all'}), 400)
    exe = _find_tool('choco')
    if not exe:
        return (jsonify({'ok': False, 'error': 'choco not found'}), 503)
    cmd = [exe, 'upgrade', package_name if package_name else 'all', '-y']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return jsonify({'ok': result.returncode == 0, 'package_name': package_name or 'all', 'exit_code': result.returncode, 'stdout': result.stdout.strip()[-2000:], 'stderr': result.stderr.strip()[-1000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'choco upgrade timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_choco_35():
    """Uninstall a package via Chocolatey."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    package_name = body.get('package_name', '')
    try:
        package_name = _choco__clean_package_name(package_name)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('choco')
    if not exe:
        return (jsonify({'ok': False, 'error': 'choco not found'}), 503)
    try:
        result = subprocess.run([exe, 'uninstall', package_name, '-y'], capture_output=True, text=True, timeout=120)
        return jsonify({'ok': result.returncode == 0, 'package_name': package_name, 'exit_code': result.returncode, 'stdout': result.stdout.strip()[-2000:], 'stderr': result.stderr.strip()[-1000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'choco uninstall timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_choco_36():
    """List outdated packages that can be upgraded."""
    exe = _find_tool('choco')
    if not exe:
        return (jsonify({'ok': False, 'error': 'choco not found'}), 503)
    try:
        result = subprocess.run([exe, 'outdated', '-r'], capture_output=True, text=True, timeout=60)
        if result.returncode not in (0, 2):
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'outdated check failed'}), 502)
        packages = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line or 'Outdated Packages' in line or '---' in line:
                continue
            parts = line.split('|')
            if len(parts) >= 3:
                packages.append({'name': parts[0].strip(), 'current_version': parts[1].strip(), 'available_version': parts[2].strip()})
        return jsonify({'ok': True, 'count': len(packages), 'outdated_packages': packages})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'choco outdated timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_choco_37():
    """Get detailed info about a package from the Chocolatey community feed."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    package_name = body.get('package_name', '')
    try:
        package_name = _choco__clean_package_name(package_name)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('choco')
    if not exe:
        return (jsonify({'ok': False, 'error': 'choco not found'}), 503)
    try:
        result = subprocess.run([exe, 'info', package_name], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or f"package '{package_name}' not found"}), 404)
        return jsonify({'ok': True, 'package_name': package_name, 'details': result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'choco info timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _cognee__clean_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a non-empty string')
    if '\x00' in value:
        raise ValueError(f'{field} cannot contain null bytes')
    return value.strip()

def _cognee__find_cognee_cli():
    return shutil.which('cognee-cli') or shutil.which('cognee-cli.exe')

def _h_cognee_38():
    data = _json_body()
    if not isinstance(data, dict) or 'query' not in data:
        return _missing_field('query')
    exe = _cognee__find_cognee_cli()
    if not exe:
        return (jsonify({'ok': False, 'error': 'cognee-cli command not found on PATH', 'hint': 'Install Cognee with `uv pip install cognee` or `pip install cognee`.'}), 503)
    try:
        query = _cognee__clean_text(data.get('query'), 'query')
        timeout = max(1, min(int(data.get('timeout', 60)), 300))
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    if query.startswith('-'):
        return (jsonify({'ok': False, 'error': 'query must not look like a CLI flag'}), 400)
    command = [exe, 'recall', query]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as exc:
        _log(f'[cognee] recall timed out after {timeout}s')
        return (jsonify({'ok': False, 'error': f'cognee-cli recall timed out after {timeout}s', 'stdout': exc.stdout or '', 'stderr': exc.stderr or ''}), 504)
    except OSError as exc:
        _log(f'[cognee] launch failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[cognee] recall exit={result.returncode}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

def _copyq__clean_text(value):
    text = str(value or '').strip()
    if not text:
        raise ValueError('text must not be empty')
    if '\x00' in text:
        raise ValueError('text cannot contain null bytes')
    return text

def _h_copyq_39():
    exe = _find_tool('copyq')
    if not exe:
        return (jsonify({'ok': False, 'error': 'copyq command not found on PATH', 'hint': 'Install CopyQ from https://hluk.github.io/CopyQ/'}), 503)
    try:
        result = subprocess.run([exe, 'clipboard'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
    except OSError as exc:
        _log(f'[copyq] clipboard read failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'copyq clipboard read timed out'}), 504)
    ok = result.returncode == 0
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'text': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

def _h_copyq_40():
    data = _json_body()
    missing = _missing_field(data, 'text')
    if missing:
        return missing
    exe = _find_tool('copyq')
    if not exe:
        return (jsonify({'ok': False, 'error': 'copyq command not found on PATH', 'hint': 'Install CopyQ from https://hluk.github.io/CopyQ/'}), 503)
    try:
        text = _copyq__clean_text(data.get('text'))
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    try:
        result = subprocess.run([exe, 'copy', '--', text], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
    except OSError as exc:
        _log(f'[copyq] clipboard write failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'copyq clipboard write timed out'}), 504)
    ok = result.returncode == 0
    _log(f'[copyq] clipboard write exit={result.returncode} length={len(text)}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'length': len(text), 'stderr': result.stderr}), 200 if ok else 502)

def _h_copyq_41():
    exe = _find_tool('copyq')
    if not exe:
        return (jsonify({'ok': False, 'error': 'copyq command not found on PATH', 'hint': 'Install CopyQ from https://hluk.github.io/CopyQ/'}), 503)
    try:
        limit = max(1, min(int(request.args.get('limit', 10)), 100))
    except (TypeError, ValueError):
        limit = 10
    try:
        result = subprocess.run([exe, 'eval', '--', f'var items = []; for (var i = 0; i < Math.min(size(), {limit}); ++i) {{   items.push(str(read(i))); }}', "items.join('\\n---SEPARATOR---\\n')"], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
    except OSError as exc:
        _log(f'[copyq] history failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'copyq history timed out'}), 504)
    ok = result.returncode == 0
    if not ok:
        return (jsonify({'ok': False, 'exit_code': result.returncode, 'stderr': result.stderr}), 502)
    items = [item.strip() for item in result.stdout.split('\n---SEPARATOR---\n') if item.strip()]
    return jsonify({'ok': True, 'count': len(items), 'items': items, 'exit_code': result.returncode, 'stderr': result.stderr})

def _h_copyq_42():
    """Execute arbitrary CopyQ script expression."""
    data = _json_body()
    missing = _missing_field(data, 'script')
    if missing:
        return missing
    exe = _find_tool('copyq')
    if not exe:
        return (jsonify({'ok': False, 'error': 'copyq command not found on PATH', 'hint': 'Install CopyQ from https://hluk.github.io/CopyQ/'}), 503)
    try:
        script = _copyq__clean_text(data.get('script'))
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    try:
        result = subprocess.run([exe, 'eval', '--', script], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
    except subprocess.TimeoutExpired as exc:
        _log(f'[copyq] eval timed out after 10s script={script[:80]}')
        return (jsonify({'ok': False, 'error': 'copyq eval timed out', 'stdout': exc.stdout or '', 'stderr': exc.stderr or ''}), 504)
    except OSError as exc:
        _log(f'[copyq] eval failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[copyq] eval exit={result.returncode}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

_defrag__ALLOWED_DEFRAG_SPECIALS = ('/C', '/AllVolumes', '/E')

def _defrag__build_volume_args(body):
    """Build defrag volume arguments from a request body, rejecting flags."""
    volumes = body.get('volumes', '')
    if not volumes:
        raise ValueError('volumes is required')
    args = []
    if isinstance(volumes, list):
        vols = [_defrag__sanitize_volume(v) for v in volumes]
    else:
        vols = [_defrag__sanitize_volume(volumes)]
    # Handle /E (all volumes except listed) regardless of container shape
    if '/E' in vols:
        if len(vols) != 1:
            raise ValueError('/E must be the only volume specifier')
        exceptions = body.get('except', [])
        if not exceptions:
            raise ValueError("/E requires an 'except' list of volumes to exclude")
        exc_list = exceptions if isinstance(exceptions, list) else [exceptions]
        vols.extend(_defrag__sanitize_volume(e) for e in exc_list)
    args.extend(vols)
    return args

def _defrag__sanitize_volume(value):
    """Validate a volume specifier, rejecting flag-like inputs."""
    v = str(value or '').strip()
    if not v:
        raise ValueError('empty volume specifier')
    if v in _defrag__ALLOWED_DEFRAG_SPECIALS:
        return v
    if v.startswith(('/', '-')):
        raise ValueError(f'invalid volume specifier: {v}')
    return v

def _defrag__run_defrag(args, timeout=120):
    """Run defrag with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('defrag')
    if not exe:
        raise RuntimeError('defrag not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, errors='replace', stdin=subprocess.DEVNULL)
    return (result.stdout, result.stderr, result.returncode)

def _h_defrag_43():
    """Analyze disk fragmentation for one or more volumes.
        
        Body:
          volumes (required): Drive letter(s) e.g. "C:" or ["C:", "D:"]
            or special: "/C" (all volumes) or "/E" (all except listed)
          verbose (optional, bool): Show detailed fragmentation stats
          progress (optional, bool): Print progress during analysis
        """
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    volumes = body.get('volumes', '')
    if not volumes:
        return _missing_field('volumes')
    try:
        args = _defrag__build_volume_args(body)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    args.append('/A')
    if body.get('verbose', False):
        args.append('/V')
    if body.get('progress', False):
        args.append('/U')
    try:
        stdout, stderr, rc = _defrag__run_defrag(args, timeout=120)
        return jsonify({'ok': rc in (0, 1), 'exit_code': rc, 'volumes': volumes, 'analysis': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'defrag analyze timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_defrag_44():
    """Run optimal defragmentation/optimization for each volume's media type.
        
        Body:
          volumes (required): Drive letter(s) e.g. "C:" or ["C:", "D:"]
            or "/C" for all volumes
          normal_priority (optional, bool): Run at normal priority (default low)
          multi_thread (optional, bool|int): Run volumes in parallel (True or thread count)
          verbose (optional, bool): Show detailed output
          progress (optional, bool): Print progress
          mode (optional, str): One of 'optimize' (default), 'defrag', 'retrim',
            'tier_optimize', 'boot_optimize', 'free_space_consolidate',
            'slab_consolidate'
        """
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    volumes = body.get('volumes', '')
    if not volumes:
        return _missing_field('volumes')
    try:
        args = _defrag__build_volume_args(body)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    mode = body.get('mode') or 'optimize'
    if not isinstance(mode, str):
        return (jsonify({'ok': False, 'error': 'mode must be a string'}), 400)
    mode = mode.lower()
    mode_flags = {'optimize': '/O', 'defrag': '/D', 'retrim': '/L', 'tier_optimize': '/G', 'boot_optimize': '/B', 'free_space_consolidate': '/X', 'slab_consolidate': '/K'}
    flag = mode_flags.get(mode)
    if not flag:
        return (jsonify({'ok': False, 'error': f"invalid mode '{mode}'. Valid: {', '.join(mode_flags.keys())}"}), 400)
    args.append(flag)
    if body.get('verbose', False):
        args.append('/V')
    if body.get('progress', False):
        args.append('/U')
    if body.get('normal_priority', False):
        args.append('/H')
    mt = body.get('multi_thread', None)
    if mt:
        if isinstance(mt, bool):
            args.append('/M')
        elif isinstance(mt, int):
            args.extend(['/M', str(mt)])
    try:
        stdout, stderr, rc = _defrag__run_defrag(args, timeout=300)
        return jsonify({'ok': rc in (0, 1, 2), 'exit_code': rc, 'mode': mode, 'volumes': volumes, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'defrag optimize timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_defrag_45():
    """Track progress of a running defrag operation on a volume.
        
        Body:
          volume (required): Drive letter e.g. "C:"
        """
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    volume = body.get('volume', '')
    if not isinstance(volume, str):
        return (jsonify({'ok': False, 'error': 'volume must be a string'}), 400)
    volume = volume.strip()
    if not volume:
        return _missing_field('volume')
    if volume.startswith(('/', '-')):
        return (jsonify({'ok': False, 'error': 'invalid volume specifier'}), 400)
    args = [volume, '/T', '/U']
    try:
        stdout, stderr, rc = _defrag__run_defrag(args, timeout=15)
        return jsonify({'ok': rc in (0, 1), 'exit_code': rc, 'volume': volume, 'progress': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'defrag progress check timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_delta_46():
    """Syntax-highlight a diff or text snippet.
        Body: {"content": "diff --git ...", "theme": "Monokai Extended", "width": 120, "side_by_side": false}
        """
    body = _json_body()
    content = body.get('content', '')
    theme = body.get('theme', 'Monokai Extended')
    width = body.get('width', 120)
    side_by_side = body.get('side_by_side', False)
    if not content or not content.strip():
        return (jsonify({'error': "'content' is required"}), 400)
    exe = _find_tool('delta')
    if not exe:
        return (jsonify({'error': 'delta not installed', 'hint': 'Install with: winget install dandavison.delta'}), 503)
    try:
        cmd = [exe, '--no-gitconfig', '--paging', 'never', '--width', str(width), '--theme', theme]
        if side_by_side:
            cmd.append('--side-by-side')
        r = subprocess.run(cmd, input=content, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            _log(f'[delta format error] {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip() or 'delta formatting failed'}), 500)
        return jsonify({'formatted': r.stdout.strip(), 'theme': theme, 'width': width, 'side_by_side': side_by_side, 'input_lines': len(content.splitlines())})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'delta format timed out'}), 504)
    except Exception as e:
        _log(f'[delta format exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _h_delta_47():
    """List all available color themes."""
    exe = _find_tool('delta')
    if not exe:
        return (jsonify({'error': 'delta not installed', 'hint': 'Install with: winget install dandavison.delta'}), 503)
    try:
        r = subprocess.run([exe, '--list-themes'], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return (jsonify({'error': r.stderr.strip() or 'delta --list-themes failed'}), 500)
        themes = [t.strip() for t in r.stdout.strip().split('\n') if t.strip()]
        return jsonify({'themes': themes, 'total': len(themes)})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'delta --list-themes timed out'}), 504)
    except Exception as e:
        _log(f'[delta themes exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _h_delta_48():
    """List all supported languages for syntax highlighting."""
    exe = _find_tool('delta')
    if not exe:
        return (jsonify({'error': 'delta not installed', 'hint': 'Install with: winget install dandavison.delta'}), 503)
    try:
        r = subprocess.run([exe, '--list-languages'], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return (jsonify({'error': r.stderr.strip() or 'delta --list-languages failed'}), 500)
        langs = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
        return jsonify({'languages': langs, 'total': len(langs)})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'delta --list-languages timed out'}), 504)
    except Exception as e:
        _log(f'[delta languages exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _detect_it_easy__as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return default

def _detect_it_easy__find_diec():
    """Locate diec (Detect It Easy console) on this system."""
    for name in ('diec.exe', 'diec'):
        exe = shutil.which(name)
        if exe:
            return exe
    candidates = [os.path.expandvars('%LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\horsicq.DIE-engine_*\\diec.exe'), os.path.expandvars('%USERPROFILE%\\scoop\\shims\\diec.exe'), os.path.expandvars('%USERPROFILE%\\scoop\\apps\\detect-it-easy\\*\\diec.exe'), os.path.expandvars('%USERPROFILE%\\scoop\\apps\\die-engine\\*\\diec.exe'), 'C:\\Program Files\\Detect It Easy\\diec.exe', 'C:\\Program Files (x86)\\Detect It Easy\\diec.exe']
    for c in candidates:
        if '*' in c:
            matches = glob.glob(c)
            if matches:
                return matches[0]
        elif os.path.isfile(c):
            return c
    return None

def _h_detect_it_easy_49():
    """Fingerprint a file or directory.
        Body: {"path": "C:\\sample.exe", "json": true, "deep": false, "heuristic": false, "recursive": false, "info": false}
        """
    body = _json_body()
    if not isinstance(body, dict):
        return _missing_field('path')
    target = body.get('path')
    if not target:
        return _missing_field('path')
    target = os.path.expandvars(os.path.expanduser(str(target)))
    target = os.path.abspath(target)
    if target.startswith('-'):
        return (jsonify({'error': 'path must not look like a CLI flag'}), 400)
    if not os.path.exists(target):
        return (jsonify({'error': f'Path does not exist: {target}'}), 404)
    json_out = _detect_it_easy__as_bool(body.get('json'), True)
    deep = _detect_it_easy__as_bool(body.get('deep'), False)
    heuristic = _detect_it_easy__as_bool(body.get('heuristic'), False)
    recursive = _detect_it_easy__as_bool(body.get('recursive'), False)
    info_only = _detect_it_easy__as_bool(body.get('info'), False)
    exe = _detect_it_easy__find_diec()
    if not exe:
        return (jsonify({'error': 'diec (Detect It Easy console) not installed', 'hint': 'Install with: winget install horsicq.DIE-engine   OR   scoop install detect-it-easy'}), 503)
    try:
        cmd = [exe]
        if json_out:
            cmd.append('-j')
        if deep:
            cmd.append('-d')
        if heuristic:
            cmd.append('-u')
        if recursive:
            cmd.append('-r')
        if info_only:
            cmd.append('-i')
        cmd.append(target)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace')
        if r.returncode != 0 and (not r.stdout):
            _log(f"[die_detect] {f'diec exited {r.returncode}: {r.stderr.strip()}'}")
            return (jsonify({'error': r.stderr.strip() or 'diec scan failed'}), 500)
        return jsonify({'target': target, 'is_dir': os.path.isdir(target), 'exit_code': r.returncode, 'format': 'json' if json_out else 'plaintext', 'deep': deep, 'heuristic': heuristic, 'recursive': recursive, 'result': (r.stdout or '').strip() or (r.stderr or '').strip()})
    except subprocess.TimeoutExpired:
        _log(f"[die_detect] {f'detect on {target} timed out'}")
        return (jsonify({'error': 'diec scan timed out after 60s', 'target': target}), 504)
    except Exception as e:
        _log(f"[die_detect] {f'Error detecting {target}: {e}'}")
        return (jsonify({'error': str(e), 'target': target}), 500)

def _devtoys__find_devtoys_cli():
    """Locate DevToys CLI binary on this system."""
    exe = shutil.which('DevToys.CLI.exe')
    if exe:
        return exe
    for p in ['C:\\Program Files\\DevToys\\DevToys.CLI.exe', 'C:\\Program Files\\DevToys\\cli\\DevToys.CLI.exe', 'C:\\Program Files (x86)\\DevToys\\DevToys.CLI.exe', os.path.expanduser('~\\AppData\\Local\\Programs\\DevToys\\DevToys.CLI.exe'), os.path.expanduser('~\\AppData\\Local\\DevToys\\CLI\\DevToys.CLI.exe')]:
        if os.path.isfile(p):
            return p
    for p in ['C:\\Program Files\\DevToys\\DevToys.exe', os.path.expanduser('~\\AppData\\Local\\Programs\\DevToys\\DevToys.exe')]:
        if os.path.isfile(p):
            return p
    for p in ['C:\\Program Files\\WindowsApps\\DevToys.DevToys_*\\DevToys.CLI.exe']:
        import glob as gl
        matches = gl.glob(p)
        if matches:
            return matches[0]
    return None

def _h_devtoys_50():
    """Encode text to Base64 using DevToys CLI or Python fallback."""
    body = _json_body()
    text = body.get('text', '')
    if not text:
        return _missing_field('text')
    cli = _devtoys__find_devtoys_cli()
    if cli and cli.endswith('DevToys.CLI.exe'):
        try:
            result = subprocess.run([cli, 'base64-encode', text], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                output = result.stdout.strip()
                return jsonify({'ok': True, 'encoded': output, 'tool': 'DevToys CLI'})
        except (subprocess.TimeoutExpired, OSError):
            pass
    import base64
    encoded = base64.b64encode(text.encode('utf-8')).decode('utf-8')
    return jsonify({'ok': True, 'encoded': encoded, 'tool': 'Python stdlib (fallback)'})

def _h_devtoys_51():
    """Decode Base64 to text using DevToys CLI or Python fallback."""
    body = _json_body()
    encoded = body.get('encoded', '')
    if not encoded:
        return _missing_field('encoded')
    cli = _devtoys__find_devtoys_cli()
    if cli and cli.endswith('DevToys.CLI.exe'):
        try:
            result = subprocess.run([cli, 'base64-decode', encoded], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                output = result.stdout.strip()
                return jsonify({'ok': True, 'decoded': output, 'tool': 'DevToys CLI'})
        except (subprocess.TimeoutExpired, OSError):
            pass
    import base64
    try:
        decoded = base64.b64decode(encoded).decode('utf-8')
        return jsonify({'ok': True, 'decoded': decoded, 'tool': 'Python stdlib (fallback)'})
    except Exception as e:
        return (jsonify({'ok': False, 'error': f'Base64 decode failed: {str(e)}'}), 400)

def _h_devtoys_52():
    """Generate hash of text using DevToys CLI or Python fallback."""
    body = _json_body()
    text = body.get('text', '')
    algorithm = body.get('algorithm', 'sha256').lower()
    if not text:
        return _missing_field('text')
    supported = ['md5', 'sha1', 'sha256', 'sha384', 'sha512']
    if algorithm not in supported:
        return (jsonify({'ok': False, 'error': f"Unsupported algorithm '{algorithm}'. Supported: {', '.join(supported)}"}), 400)
    cli = _devtoys__find_devtoys_cli()
    if cli and cli.endswith('DevToys.CLI.exe'):
        try:
            result = subprocess.run([cli, 'hash', '--algorithm', algorithm, text], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                output = result.stdout.strip()
                return jsonify({'ok': True, 'hash': output, 'algorithm': algorithm, 'tool': 'DevToys CLI'})
        except (subprocess.TimeoutExpired, OSError):
            pass
    import hashlib
    h = hashlib.new(algorithm)
    h.update(text.encode('utf-8'))
    return jsonify({'ok': True, 'hash': h.hexdigest(), 'algorithm': algorithm, 'tool': 'Python hashlib (fallback)'})

def _h_devtoys_53():
    """Format/pretty-print JSON text using DevToys CLI or Python fallback."""
    body = _json_body()
    json_text = body.get('json', '')
    indent_size = body.get('indent', 2)
    if not json_text:
        return _missing_field('json')
    cli = _devtoys__find_devtoys_cli()
    if cli and cli.endswith('DevToys.CLI.exe'):
        try:
            result = subprocess.run([cli, 'json-format', '--indent', str(indent_size), json_text], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                output = result.stdout.strip()
                return jsonify({'ok': True, 'formatted': output, 'tool': 'DevToys CLI'})
        except (subprocess.TimeoutExpired, OSError):
            pass
    try:
        parsed = json_lib.loads(json_text)
        formatted = json_lib.dumps(parsed, indent=indent_size)
        return jsonify({'ok': True, 'formatted': formatted, 'tool': 'Python json (fallback)'})
    except json_lib.JSONDecodeError as e:
        return (jsonify({'ok': False, 'error': f'Invalid JSON: {str(e)}'}), 400)

def _h_devtoys_54():
    """Generate a UUID using DevToys CLI or Python fallback."""
    import uuid
    cli = _devtoys__find_devtoys_cli()
    if cli and cli.endswith('DevToys.CLI.exe'):
        try:
            result = subprocess.run([cli, 'uuid-generate'], capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                output = result.stdout.strip()
                return jsonify({'ok': True, 'uuid': output, 'tool': 'DevToys CLI'})
        except (subprocess.TimeoutExpired, OSError):
            pass
    return jsonify({'ok': True, 'uuid': str(uuid.uuid4()), 'tool': 'Python uuid (fallback)'})

def _diskpart__parse_partition_list(output):
    """Parse 'list partition' output."""
    partitions = []
    lines = output.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if 'Partition ###' in line:
            header_idx = i
            break
    if header_idx is None:
        return partitions
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line or line.startswith('-') or '---' in line:
            continue
        if 'DISKPART' in line or 'list partition' in line.lower():
            continue
        parts = re.split('\\s{2,}', line)
        if len(parts) >= 3:
            partitions.append({'raw': line, 'parts': parts})
    return partitions

def _diskpart__parse_disk_list(output):
    """Parse 'list disk' output into structured data."""
    disks = []
    lines = output.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if 'Disk ###' in line:
            header_idx = i
            break
    if header_idx is None:
        return disks
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line or line.startswith('-') or '---' in line:
            continue
        if 'DISKPART' in line or 'list disk' in line.lower():
            continue
        parts = re.split('\\s{2,}', line)
        if len(parts) >= 4:
            try:
                disk_num = parts[0].replace('Disk', '').strip()
                status = parts[1].strip()
                size = parts[2].strip()
                free = parts[3].strip() if len(parts) > 3 else ''
                dyn = parts[4].strip() if len(parts) > 4 else ''
                gpt = parts[5].strip() if len(parts) > 5 else ''
            except (IndexError, ValueError):
                continue
            disks.append({'disk': disk_num, 'status': status, 'size': size, 'free': free, 'dynamic': dyn, 'gpt': gpt})
    return disks

def _diskpart__run_diskpart_script(script_lines, timeout=30):
    """Run diskpart.exe with a list of commands, return stdout or raise."""
    exe = _find_tool('diskpart')
    if not exe:
        raise RuntimeError('diskpart.exe not found on system')
    input_text = '\n'.join(script_lines) + '\n'
    try:
        result = subprocess.run([exe], input=input_text.encode('utf-16le', errors='replace'), capture_output=True, text=False, timeout=timeout)
        stdout = result.stdout.decode('utf-16le', errors='replace') if result.stdout else ''
        stderr = result.stderr.decode('utf-16le', errors='replace') if result.stderr else ''
    except subprocess.TimeoutExpired:
        raise RuntimeError('diskpart operation timed out')
    except OSError as e:
        raise RuntimeError(f'diskpart execution failed: {e}')
    if result.returncode != 0:
        raise RuntimeError(stderr.strip() or 'diskpart returned non-zero exit code')
    return stdout

def _diskpart__parse_volume_list(output):
    """Parse 'list volume' output into structured data."""
    volumes = []
    lines = output.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if 'Volume ###' in line:
            header_idx = i
            break
    if header_idx is None:
        return volumes
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line or line.startswith('-') or '---' in line:
            continue
        if 'DISKPART' in line or 'list volume' in line.lower():
            continue
        parts = re.split('\\s{2,}', line)
        if len(parts) >= 3:
            volumes.append({'raw': line, 'parts': parts})
    return volumes

def _h_diskpart_55():
    """List all physical disks attached to the system."""
    try:
        output = _diskpart__run_diskpart_script(['list disk', 'exit'], timeout=15)
        parsed = _diskpart__parse_disk_list(output)
        return jsonify({'ok': True, 'disks': parsed, 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_diskpart_56():
    """List all volumes (partitions with drive letters/mounts)."""
    try:
        output = _diskpart__run_diskpart_script(['list volume', 'exit'], timeout=15)
        parsed = _diskpart__parse_volume_list(output)
        return jsonify({'ok': True, 'volumes': parsed, 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_diskpart_57():
    """List partitions on a specific disk."""
    body = _json_body()
    disk_num = str(body.get('disk') or '0').strip()
    if not disk_num.isdigit():
        return (jsonify({'ok': False, 'error': 'disk must be a numeric index'}), 400)
    try:
        output = _diskpart__run_diskpart_script([f'select disk {disk_num}', 'list partition', 'exit'], timeout=15)
        parsed = _diskpart__parse_partition_list(output)
        return jsonify({'ok': True, 'disk': disk_num, 'partitions': parsed, 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'disk': disk_num, 'error': str(e)}), 503)

def _h_diskpart_58():
    """Get detailed info about a specific disk."""
    body = _json_body()
    disk_num = str(body.get('disk') or '0').strip()
    if not disk_num.isdigit():
        return (jsonify({'ok': False, 'error': 'disk must be a numeric index'}), 400)
    try:
        output = _diskpart__run_diskpart_script([f'select disk {disk_num}', 'detail disk', 'exit'], timeout=15)
        return jsonify({'ok': True, 'disk': disk_num, 'detail': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'disk': disk_num, 'error': str(e)}), 503)

def _h_diskpart_59():
    """Remove all partitions from a disk (DESTRUCTIVE — requires confirmation)."""
    body = _json_body()
    disk_num = str(body.get('disk') or '').strip()
    confirm = body.get('confirm', False)
    if not disk_num:
        return _missing_field('disk')
    if not disk_num.isdigit():
        return (jsonify({'ok': False, 'error': 'disk must be a numeric index'}), 400)
    if not confirm:
        return (jsonify({'ok': False, 'error': "Confirmation required — set 'confirm: true' to proceed. This is DESTRUCTIVE and removes ALL data on the disk."}), 400)
    try:
        output = _diskpart__run_diskpart_script([f'select disk {disk_num}', 'clean', 'exit'], timeout=30)
        return jsonify({'ok': True, 'disk': disk_num, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'disk': disk_num, 'error': str(e)}), 503)

def _h_diskpart_60():
    """Convert a disk from MBR to GPT (DESTRUCTIVE — requires confirmation)."""
    body = _json_body()
    disk_num = str(body.get('disk') or '').strip()
    confirm = body.get('confirm', False)
    if not disk_num:
        return _missing_field('disk')
    if not disk_num.isdigit():
        return (jsonify({'ok': False, 'error': 'disk must be a numeric index'}), 400)
    if not confirm:
        return (jsonify({'ok': False, 'error': "Confirmation required — set 'confirm: true' to proceed. Converts disk format (MBR->GPT)."}), 400)
    try:
        output = _diskpart__run_diskpart_script([f'select disk {disk_num}', 'convert gpt', 'exit'], timeout=30)
        return jsonify({'ok': True, 'disk': disk_num, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'disk': disk_num, 'error': str(e)}), 503)

def _h_diskpart_61():
    """Create a new partition on a disk. Specify size in MB (optional)."""
    body = _json_body()
    disk_num = str(body.get('disk') or '').strip()
    size_mb = body.get('size_mb')
    partition_type = str(body.get('type', 'primary')).strip().lower()
    if not disk_num:
        return _missing_field('disk')
    if not disk_num.isdigit():
        return (jsonify({'ok': False, 'error': 'disk must be a numeric index'}), 400)
    if partition_type not in ('primary', 'extended', 'logical'):
        partition_type = 'primary'
    if size_mb not in (None, ''):
        try:
            size_mb = int(size_mb)
        except (ValueError, TypeError):
            return (jsonify({'ok': False, 'error': 'size_mb must be an integer'}), 400)
        if size_mb < 1 or size_mb > 1000000000:
            return (jsonify({'ok': False, 'error': 'size_mb must be between 1 and 1000000000'}), 400)
    commands = [f'select disk {disk_num}']
    if size_mb:
        commands.append(f'create partition {partition_type} size={size_mb}')
    else:
        commands.append(f'create partition {partition_type}')
    commands.append('exit')
    try:
        output = _diskpart__run_diskpart_script(commands, timeout=30)
        return jsonify({'ok': True, 'disk': disk_num, 'type': partition_type, 'size_mb': size_mb, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'disk': disk_num, 'error': str(e)}), 503)

def _h_diskpart_62():
    """Format a volume with specified filesystem (DESTRUCTIVE — requires confirmation)."""
    body = _json_body()
    volume_num = str(body.get('volume') or '').strip()
    fs = str(body.get('filesystem') or 'NTFS').strip().upper()
    label = str(body.get('label') or '').strip()
    quick = body.get('quick', True)
    confirm = body.get('confirm', False)
    if not volume_num:
        return _missing_field('volume')
    if not volume_num.isdigit():
        return (jsonify({'ok': False, 'error': 'volume must be a numeric index'}), 400)
    if fs not in ('NTFS', 'FAT', 'FAT32', 'EXFAT', 'REFS', 'UDF'):
        return (jsonify({'ok': False, 'error': f"unsupported filesystem '{fs}'"}), 400)
    if label and (not re.fullmatch('[A-Za-z0-9 _\\-.]{1,32}', label)):
        return (jsonify({'ok': False, 'error': 'label may only contain letters, digits, spaces, and ._- (max 32 chars)'}), 400)
    if not confirm:
        return (jsonify({'ok': False, 'error': "Confirmation required — set 'confirm: true' to proceed. Formatting is DESTRUCTIVE."}), 400)
    commands = [f'select volume {volume_num}']
    quick_flag = 'quick' if quick else ''
    if label:
        commands.append(f'format fs={fs} label="{label}" {quick_flag}'.strip())
    else:
        commands.append(f'format fs={fs} {quick_flag}'.strip())
    commands.append('exit')
    try:
        output = _diskpart__run_diskpart_script(commands, timeout=120)
        return jsonify({'ok': True, 'volume': volume_num, 'filesystem': fs, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'volume': volume_num, 'error': str(e)}), 503)

def _h_diskpart_63():
    """Assign a drive letter to a volume."""
    body = _json_body()
    volume_num = str(body.get('volume') or '').strip()
    letter = str(body.get('letter') or '').strip().upper().replace(':', '')
    if not volume_num:
        return _missing_field('volume')
    if not volume_num.isdigit():
        return (jsonify({'ok': False, 'error': 'volume must be a numeric index'}), 400)
    if not letter or len(letter) != 1 or letter not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        return (jsonify({'ok': False, 'error': 'Invalid drive letter'}), 400)
    try:
        output = _diskpart__run_diskpart_script([f'select volume {volume_num}', f'assign letter={letter}', 'exit'], timeout=15)
        return jsonify({'ok': True, 'volume': volume_num, 'letter': letter, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'volume': volume_num, 'error': str(e)}), 503)

def _h_diskpart_64():
    """Remove a drive letter from a volume (make it hidden)."""
    body = _json_body()
    volume_num = str(body.get('volume') or '').strip()
    letter = str(body.get('letter') or '').strip().upper().replace(':', '')
    if not volume_num:
        return _missing_field('volume')
    if not volume_num.isdigit():
        return (jsonify({'ok': False, 'error': 'volume must be a numeric index'}), 400)
    if not letter or len(letter) != 1 or letter not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        return (jsonify({'ok': False, 'error': 'Invalid drive letter'}), 400)
    try:
        output = _diskpart__run_diskpart_script([f'select volume {volume_num}', f'remove letter={letter}', 'exit'], timeout=15)
        return jsonify({'ok': True, 'volume': volume_num, 'letter': letter, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'volume': volume_num, 'error': str(e)}), 503)

def _dism__run_dism(args, timeout=60):
    """Run dism.exe with given args, return parsed output or raise."""
    exe = _find_tool('dism')
    if not exe:
        raise RuntimeError('Dism.exe not found on system')
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Dism operation timed out')
    except OSError as e:
        raise RuntimeError(f'Dism execution failed: {e}')
    if result.returncode != 0:
        stderr = (result.stderr or '').strip()
        raise RuntimeError(stderr or 'Dism returned non-zero exit code')
    return result.stdout

def _h_dism_65():
    """Run DISM /ScanHealth — check component store corruption."""
    try:
        output = _dism__run_dism(['/online', '/Cleanup-Image', '/ScanHealth'], timeout=120)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_dism_66():
    """Run DISM /CheckHealth — quick health check (reads existing logs only)."""
    try:
        output = _dism__run_dism(['/online', '/Cleanup-Image', '/CheckHealth'], timeout=30)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_dism_67():
    """Run DISM /RestoreHealth — repair component store corruption."""
    try:
        output = _dism__run_dism(['/online', '/Cleanup-Image', '/RestoreHealth'], timeout=300)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_dism_68():
    """List all Windows features and their state."""
    try:
        output = _dism__run_dism(['/online', '/Get-Features', '/Format:Table'], timeout=30)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_dism_69():
    """Enable a Windows feature by name."""
    body = _json_body()
    name = str(body.get('name') or '').strip()
    if not name:
        return _missing_field('name')
    if not re.fullmatch(r'[A-Za-z0-9._\-]+', name):
        return (jsonify({'ok': False, 'error': 'invalid feature name (letters, digits, . _ - only)'}), 400)
    try:
        output = _dism__run_dism(['/online', '/Enable-Feature', f'/FeatureName:{name}', '/All'], timeout=180)
        return jsonify({'ok': True, 'feature': name, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'feature': name, 'error': str(e)}), 503)

def _h_dism_70():
    """Disable a Windows feature by name."""
    body = _json_body()
    name = str(body.get('name') or '').strip()
    if not name:
        return _missing_field('name')
    if not re.fullmatch(r'[A-Za-z0-9._\-]+', name):
        return (jsonify({'ok': False, 'error': 'invalid feature name (letters, digits, . _ - only)'}), 400)
    try:
        output = _dism__run_dism(['/online', '/Disable-Feature', f'/FeatureName:{name}'], timeout=180)
        return jsonify({'ok': True, 'feature': name, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'feature': name, 'error': str(e)}), 503)

def _h_dism_71():
    """Get detailed state of a specific Windows feature."""
    body = _json_body()
    name = str(body.get('name') or '').strip()
    if not name:
        return _missing_field('name')
    if not re.fullmatch(r'[A-Za-z0-9._\-]+', name):
        return (jsonify({'ok': False, 'error': 'invalid feature name (letters, digits, . _ - only)'}), 400)
    try:
        output = _dism__run_dism(['/online', '/Get-FeatureInfo', f'/FeatureName:{name}'], timeout=30)
        return jsonify({'ok': True, 'feature': name, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'feature': name, 'error': str(e)}), 503)

def _h_dism_72():
    """List all installed Windows packages."""
    try:
        output = _dism__run_dism(['/online', '/Get-Packages', '/Format:Table'], timeout=30)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_dism_73():
    """Get current edition and version info."""
    try:
        output = _dism__run_dism(['/online', '/Get-CurrentEdition'], timeout=15)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _driverquery__parse_csv_drivers(text):
    """Parse driverquery CSV output into list of dicts."""
    lines = text.strip().splitlines()
    if not lines:
        return []
    headers = [h.strip().strip('"') for h in lines[0].split(',')]
    drivers = []
    for line in lines[1:]:
        if not line.strip():
            continue
        values = [v.strip().strip('"') for v in line.split(',')]
        entry = {}
        for i, h in enumerate(headers):
            if i < len(values):
                entry[h] = values[i]
            else:
                entry[h] = ''
        drivers.append(entry)
    return drivers

def _driverquery__run_driverquery(args, timeout=15):
    """Run driverquery with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('driverquery')
    if not exe:
        raise RuntimeError('driverquery not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_driverquery_74():
    """List drivers as structured JSON (parsed from CSV output).
        
        Query params:
          signed (optional, bool): Only show signed driver info
          verbose (optional, bool): Show verbose module details
        """
    from flask import request
    args = ['/FO', 'CSV']
    show_signed = request.args.get('signed', '').lower() in ('1', 'true', 'yes')
    verbose = request.args.get('verbose', '').lower() in ('1', 'true', 'yes')
    if show_signed and verbose:
        return (jsonify({'ok': False, 'error': '/SI and /V are mutually exclusive'}), 400)
    if show_signed:
        args.append('/SI')
    if verbose:
        args.append('/V')
    try:
        stdout, stderr, rc = _driverquery__run_driverquery(args)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'driverquery failed'}), 502)
        drivers = _driverquery__parse_csv_drivers(stdout)
        return jsonify({'ok': True, 'drivers': drivers, 'count': len(drivers), 'signed_only': show_signed, 'verbose': verbose})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'driverquery timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_driverquery_75():
    """List drivers as raw text table.
        
        Query params:
          format (optional, str): 'TABLE' (default), 'LIST', or 'CSV'
          no_header (optional, bool): Omit column headers (TABLE/CSV only)
          signed (optional, bool): Only show signed driver info
          verbose (optional, bool): Show verbose module details
        """
    from flask import request
    fmt = request.args.get('format', 'TABLE').upper()
    if fmt not in ('TABLE', 'LIST', 'CSV'):
        return (jsonify({'ok': False, 'error': f"invalid format '{fmt}'. Use TABLE, LIST, or CSV"}), 400)
    args = ['/FO', fmt]
    no_header = request.args.get('no_header', '').lower() in ('1', 'true', 'yes')
    if no_header and fmt in ('TABLE', 'CSV'):
        args.append('/NH')
    show_signed = request.args.get('signed', '').lower() in ('1', 'true', 'yes')
    verbose = request.args.get('verbose', '').lower() in ('1', 'true', 'yes')
    if show_signed and verbose:
        return (jsonify({'ok': False, 'error': '/SI and /V are mutually exclusive'}), 400)
    if show_signed:
        args.append('/SI')
    if verbose:
        args.append('/V')
    try:
        stdout, stderr, rc = _driverquery__run_driverquery(args)
        return jsonify({'ok': True, 'exit_code': rc, 'format': fmt, 'output': stdout.strip() if rc == 0 else stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'driverquery timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _excel_mcp_server__optional_int(value, field, default, minimum, maximum):
    if value in (None, ''):
        return default
    number = int(value)
    if number < minimum or number > maximum:
        raise ValueError(f'{field} must be between {minimum} and {maximum}')
    return number

def _excel_mcp_server__clean_file_path(value):
    path = str(value or '').strip()
    if not path:
        raise ValueError('file path must not be empty')
    if '\x00' in path:
        raise ValueError('file path cannot contain null bytes')
    return path

def _excel_mcp_server__find_excel_mcp():
    configured = os.environ.get('EXCEL_MCP_CMD', '').strip()
    if configured and shutil.which(configured):
        return configured
    candidates = ['excel-mcp', 'excel-mcp.exe', 'excel-mcp-server', 'excel_mcp_server']
    for cmd in candidates:
        found = shutil.which(cmd)
        if found:
            return found
    return None

def _h_excel_mcp_server_76():
    """Execute an Excel operation via the MCP server.
        
        Body: {
            "file": "C:\\path\\to\\workbook.xlsx",
            "operation": "read_cell",
            "params": {"sheet": "Sheet1", "cell": "A1"}
        }
        """
    data = _json_body()
    missing = _missing_field(data, 'file')
    if missing:
        return missing
    if 'operation' not in data:
        return _missing_field('operation')
    cmd = _excel_mcp_server__find_excel_mcp()
    if not cmd:
        return (jsonify({'ok': False, 'error': 'excel-mcp command not found on PATH', 'hint': 'Install with `uvx excel-mcp-server` or `pip install excel-mcp-server`'}), 503)
    try:
        file_path = _excel_mcp_server__clean_file_path(data.get('file'))
        operation = str(data.get('operation', '')).strip()
        if not operation:
            raise ValueError('operation must be a non-empty string')
        params = data.get('params', {})
        timeout = _excel_mcp_server__optional_int(data.get('timeout'), 'timeout', 60, 5, 300)
    except (ValueError, TypeError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    if not Path(file_path).is_file():
        return (jsonify({'ok': False, 'error': f'File not found: {file_path}'}), 404)
    command = [cmd, '--file', file_path, '--operation', operation]
    if params:
        import json as _json
        command.extend(['--params', _json.dumps(params)])
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as exc:
        _log(f'[excel_mcp] Operation timed out after {timeout}s operation={operation}')
        return (jsonify({'ok': False, 'error': f'Excel operation timed out after {timeout}s', 'stdout': exc.stdout or '', 'stderr': exc.stderr or ''}), 504)
    except OSError as exc:
        _log(f'[excel_mcp] launch failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[excel_mcp] exit={result.returncode} operation={operation}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'file': file_path, 'operation': operation, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

def _h_eza_77():
    """List directory contents via eza, with optional JSON output.

        GET params or JSON body:
            path (str, optional): Directory to list. Defaults to current dir.
            long (bool, optional): Detailed listing with size/permissions. Default True.
            git (bool, optional): Show git status per file. Default True.
            icons (bool, optional): Show file-type icons. Default False.
            all (bool, optional): Include hidden files. Default False.
            tree (bool, optional): Recursive tree view (implies --long). Default False.
            json (bool, optional): Return machine-readable JSON. Default True.
            sort (str, optional): Sort field: name|size|time|ext|none. Default 'name'.
            max_depth (int, optional): Tree depth when tree=True. Default 3.
            max_entries (int, optional): Cap returned entries. Default 500.
        """
    exe = _find_tool('eza')
    if not exe:
        return (jsonify({'error': 'eza is not installed', 'hint': 'Install with: winget install eza-community.eza', 'entries': []}), 503)
    if request.method == 'POST':
        data = _json_body() or {}
    else:
        data = {k: v for k, v in request.args.items()}
    path = data.get('path', '.') or '.'
    if not os.path.isdir(path):
        return (jsonify({'error': f'Path does not exist or is not a directory: {path}', 'entries': []}), 400)
    use_json = str(data.get('json', 'true')).lower() in ('1', 'true', 'yes')
    use_long = str(data.get('long', 'true')).lower() in ('1', 'true', 'yes')
    use_tree = str(data.get('tree', 'false')).lower() in ('1', 'true', 'yes')
    cmd = [exe, '--color', 'never']
    if use_json:
        cmd.append('--json')
    elif use_long:
        cmd.append('--long')
    if str(data.get('git', 'true')).lower() in ('1', 'true', 'yes'):
        cmd.append('--git')
    if str(data.get('icons', 'false')).lower() in ('1', 'true', 'yes'):
        cmd.append('--icons')
    if str(data.get('all', 'false')).lower() in ('1', 'true', 'yes'):
        cmd.append('--all')
    sort = (data.get('sort') or 'name').lower()
    sort_map = {'name': '--sort=Name', 'size': '--sort=size', 'time': '--sort=modified', 'ext': '--sort=extension', 'none': '--sort=none'}
    if sort in sort_map:
        cmd.append(sort_map[sort])
    if use_tree:
        cmd.append('--tree')
        try:
            cmd.extend(['--level', str(max(1, min(int(data.get('max_depth', 3)), 10)))])
        except (ValueError, TypeError):
            cmd.extend(['--level', '3'])
    cmd.append('--')
    cmd.append(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            _log(f"[auto_eza_list] {f'eza exited {r.returncode}: {r.stderr[:300]}'}")
            return (jsonify({'error': r.stderr.strip() or 'eza failed', 'entries': []}), 500)
        try:
            max_entries = max(1, min(int(data.get('max_entries', 500)), 5000))
        except (ValueError, TypeError):
            max_entries = 500
        if use_json:
            entries = json.loads(r.stdout) if r.stdout.strip() else []
            if not isinstance(entries, list):
                entries = [entries]
            total = len(entries)
            entries = entries[:max_entries]
            return jsonify({'path': path, 'total': total, 'returned': len(entries), 'entries': entries})
        else:
            lines = [l for l in r.stdout.split('\n') if l]
            total = len(lines)
            lines = lines[:max_entries]
            return jsonify({'path': path, 'total': total, 'returned': len(lines), 'entries': lines})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'eza timed out after 30s', 'entries': []}), 504)
    except json.JSONDecodeError:
        return (jsonify({'error': 'eza returned non-JSON output', 'entries': []}), 500)
    except Exception as e:
        _log(f"[auto_eza_list] {f'Unexpected error: {e}'}")
        return (jsonify({'error': str(e), 'entries': []}), 500)

def _fd__as_bool(value, default=False):
    """Coerce a query/body value to bool — GET params always arrive as strings."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return default

def _h_fd_78():
    """Search for files by name pattern using fd.

        GET params or JSON body:
            pattern (str): File name pattern to search for (supports regex, glob, exact)
            path (str, optional): Directory to search in. Defaults to CWD.
            type (str, optional): 'f' for files, 'd' for directories, 'l' for symlinks
            extension (str, optional): Filter by file extension (e.g. 'py', 'txt')
            case_sensitive (bool, optional): Force case-sensitive search. Default: smart case.
            max_depth (int, optional): Maximum directory depth to search.
            max_results (int, optional): Maximum results to return. Default 200.
            absolute (bool, optional): Show absolute paths. Default False.
            hidden (bool, optional): Search hidden files/dirs too. Default False.
            list_details (bool, optional): Show detailed listing. Default False.
        """
    exe = _find_tool('fd')
    if not exe:
        return (jsonify({'error': 'fd is not installed', 'hint': 'Install with: winget install sharkdp.fd', 'results': []}), 503)
    if request.method == 'POST':
        data = _json_body() or {}
    else:
        data = {k: v for k, v in request.args.items()}
    pattern = data.get('pattern', '').strip()
    if not pattern:
        return (jsonify({'error': "Missing 'pattern' parameter", 'results': []}), 400)
    search_path = data.get('path', '.')
    if not os.path.isdir(search_path):
        return (jsonify({'error': f'Path does not exist or is not a directory: {search_path}', 'results': []}), 400)
    cmd = [exe]
    ftype = data.get('type')
    if ftype in ('f', 'd', 'l', 'x', 'e'):
        cmd.extend(['--type', ftype])
    ext = data.get('extension')
    if ext:
        cmd.extend(['--extension', ext.lstrip('.')])
    if _fd__as_bool(data.get('case_sensitive')):
        cmd.append('--case-sensitive')
    max_depth = data.get('max_depth')
    if max_depth is not None:
        try:
            cmd.extend(['--max-depth', str(int(max_depth))])
        except (ValueError, TypeError):
            return (jsonify({'error': f'Invalid max_depth value: {max_depth}', 'results': []}), 400)
    max_results = data.get('max_results', 200)
    try:
        max_results = max(1, min(int(max_results), 5000))
    except (ValueError, TypeError):
        max_results = 200
    if _fd__as_bool(data.get('absolute')):
        cmd.append('--absolute-path')
    if _fd__as_bool(data.get('hidden')):
        cmd.append('--hidden')
    if _fd__as_bool(data.get('no_ignore')):
        cmd.append('--no-ignore')
    if _fd__as_bool(data.get('list_details')):
        cmd.extend(['--list-details'])
    cmd.extend(['--strip-cwd-prefix'])
    cmd.append('--')
    cmd.append(pattern)
    cmd.append(search_path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0 and r.returncode != 1:
            _log(f"[auto_fd_search] {f'fd exited with code {r.returncode}: {r.stderr[:500]}'}")
            return (jsonify({'error': r.stderr.strip() or 'fd search failed', 'results': []}), 500)
        lines = [l for l in r.stdout.strip().split('\n') if l]
        total = len(lines)
        lines = lines[:max_results]
        return jsonify({'pattern': pattern, 'path': search_path, 'total': total, 'returned': len(lines), 'results': lines})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'fd search timed out after 30s', 'results': []}), 504)
    except FileNotFoundError:
        return (jsonify({'error': 'fd executable not found', 'hint': 'Install with: winget install sharkdp.fd', 'results': []}), 503)
    except Exception as e:
        _log(f"[auto_fd_search] {f'Unexpected error: {e}'}")
        return (jsonify({'error': str(e), 'results': []}), 500)

_fsutil_ALLOWED_SUBCOMMANDS = {'fsinfo': ['drives', 'drivetype', 'volumeinfo', 'ntfsinfo', 'statistics'], 'file': ['queryfilenamebydata', 'queryfilemetadata', 'validdata', 'layout', 'optimizemedia', 'querynamebydatalocation'], 'volume': ['allocationreport', 'diskfree', 'dismount', 'fsinfo', 'health', 'querycluster', 'repair'], 'hardlink': ['create', 'list'], 'sparse': ['queryflag', 'queryrange', 'setflag', 'setrange'], 'usn': ['createmft', 'deletejournal', 'enumdata', 'queryjournal', 'readjournal', 'readdata'], 'quota': ['modify', 'query', 'track', 'violations'], 'behavior': ['query', 'set', 'queryallowextents', 'querydisable8dot3', 'querydisablecompression', 'querydisablelastaccess', 'queryencryptpagingfile', 'querymftzone', 'querymemorypriority', 'queryquotanotify', 'queryresolvebitmap', 'querysymlinkevaluation'], 'dirty': ['query', 'set'], 'reparsepoint': ['query', 'delete']}

def _fsutil__run_fsutil(args, timeout=15):
    exe = _find_tool('fsutil')
    if not exe:
        raise RuntimeError('fsutil not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_fsutil_79():
    """Query filesystem information: drives, drivetype, volumeinfo, ntfsinfo, statistics."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    subcommand = str(body.get('subcommand', '')).strip().lower()
    if not subcommand:
        return _missing_field('subcommand')
    if subcommand not in _fsutil_ALLOWED_SUBCOMMANDS['fsinfo']:
        return (jsonify({'ok': False, 'error': f'invalid fsinfo subcommand: {subcommand}'}), 400)
    args = ['fsinfo', subcommand]
    if subcommand in ('drivetype', 'volumeinfo', 'ntfsinfo', 'statistics'):
        drive = body.get('drive', '')
        if drive:
            args.append(drive)
    try:
        stdout, stderr, rc = _fsutil__run_fsutil(args, timeout=15)
        return jsonify({'ok': rc == 0, 'subcommand': subcommand, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'fsutil fsinfo command timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_fsutil_80():
    """Query disk free space for a specific drive."""
    try:
        from flask import request
        drive = request.args.get('drive', 'c:')
    except Exception:
        drive = 'c:'
    drive = drive.strip().rstrip('\\/')
    if not drive.endswith(':'):
        drive = drive + ':'
    try:
        stdout, stderr, rc = _fsutil__run_fsutil(['volume', 'diskfree', drive], timeout=15)
        return jsonify({'ok': rc == 0, 'drive': drive, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'fsutil diskfree command timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_fsutil_81():
    """Query file metadata: layout, name, metadata info, or valid data length."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    subcommand = str(body.get('subcommand', '')).strip().lower()
    file_path = str(body.get('path', '')).strip()
    if not subcommand:
        return _missing_field('subcommand')
    if subcommand not in _fsutil_ALLOWED_SUBCOMMANDS['file']:
        return (jsonify({'ok': False, 'error': f'invalid file subcommand: {subcommand}'}), 400)
    if not file_path:
        return _missing_field('path')
    args = ['file', subcommand, file_path]
    try:
        stdout, stderr, rc = _fsutil__run_fsutil(args, timeout=15)
        return jsonify({'ok': rc == 0, 'subcommand': subcommand, 'path': file_path, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'fsutil file command timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_fsutil_82():
    """Query volume information: allocation report or health for a drive."""
    try:
        from flask import request
        drive = request.args.get('drive', 'c:')
        query = request.args.get('query', 'allocationreport').strip().lower()
    except Exception:
        drive = 'c:'
        query = 'allocationreport'
    drive = drive.strip().rstrip('\\/')
    if not drive.endswith(':'):
        drive = drive + ':'
    allowed_volume = ['allocationreport', 'health']
    for q in query.split(','):
        q = q.strip()
        if q and q not in allowed_volume:
            return (jsonify({'ok': False, 'error': f'invalid volume query: {q}'}), 400)
    results = []
    for q in query.split(','):
        q = q.strip()
        if not q:
            continue
        try:
            stdout, stderr, rc = _fsutil__run_fsutil(['volume', q, drive], timeout=15)
            results.append({'query': q, 'ok': rc == 0, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
        except subprocess.TimeoutExpired:
            results.append({'query': q, 'ok': False, 'error': 'timed out'})
        except Exception as e:
            results.append({'query': q, 'ok': False, 'error': str(e)})
    return jsonify({'ok': True, 'drive': drive, 'results': results})

def _h_fsutil_83():
    """Create or list hard links."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    subcommand = str(body.get('subcommand', '')).strip().lower()
    if subcommand not in _fsutil_ALLOWED_SUBCOMMANDS['hardlink']:
        return (jsonify({'ok': False, 'error': f'invalid hardlink subcommand: {subcommand}'}), 400)
    if subcommand == 'create':
        filename = str(body.get('filename', '')).strip()
        newpath = str(body.get('newpath', '')).strip()
        if not filename:
            return _missing_field('filename')
        if not newpath:
            return _missing_field('newpath')
        args = ['hardlink', 'create', newpath, filename]
    else:
        filename = str(body.get('filename', '')).strip()
        if not filename:
            return _missing_field('filename')
        args = ['hardlink', 'list', filename]
    try:
        stdout, stderr, rc = _fsutil__run_fsutil(args, timeout=15)
        return jsonify({'ok': rc == 0, 'subcommand': subcommand, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'fsutil hardlink command timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_fsutil_84():
    """Query or manage disk quotas on a volume."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    subcommand = str(body.get('subcommand', '')).strip().lower()
    if subcommand not in _fsutil_ALLOWED_SUBCOMMANDS['quota']:
        return (jsonify({'ok': False, 'error': f'invalid quota subcommand: {subcommand}'}), 400)
    drive = str(body.get('drive', 'c:')).strip()
    if not drive.endswith(':'):
        drive = drive + ':'
    args = ['quota', subcommand, drive]
    if subcommand == 'modify':
        threshold = body.get('threshold')
        limit = body.get('limit')
        username = body.get('username')
        if threshold is None or threshold == '':
            return _missing_field('threshold')
        if limit is None or limit == '':
            return _missing_field('limit')
        try:
            threshold = int(threshold)
            limit = int(limit)
        except (TypeError, ValueError):
            return (jsonify({'ok': False, 'error': 'threshold and limit must be integers'}), 400)
        args.extend([str(threshold), str(limit)])
        if username:
            args.append(str(username).strip())
    try:
        stdout, stderr, rc = _fsutil__run_fsutil(args, timeout=15)
        return jsonify({'ok': rc == 0, 'subcommand': subcommand, 'drive': drive, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'fsutil quota command timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_fzf_85():
    """Fuzzy-filter a list of strings. Body: {"query": "pattern", "items": ["str1", "str2", ...]}"""
    body = _json_body()
    query = body.get('query', '')
    items = body.get('items', [])
    if not isinstance(items, list):
        return (jsonify({'error': "'items' must be a list of strings"}), 400)
    exe = _find_tool('fzf')
    if not exe:
        return (jsonify({'error': 'fzf not installed', 'hint': 'Install with: winget install junegunn.fzf'}), 503)
    try:
        stdin = '\n'.join((str(i) for i in items))
        r = subprocess.run([exe, '--filter', str(query)], input=stdin, capture_output=True, text=True, timeout=15)
        if r.returncode == 1:
            return jsonify({'matches': [], 'query': query, 'total_input': len(items)})
        if r.returncode != 0:
            _log(f'[fzf filter error] {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip() or 'fzf filter failed'}), 500)
        matches = [m for m in r.stdout.strip().split('\n') if m]
        return jsonify({'matches': matches, 'query': query, 'total_input': len(items), 'total_matches': len(matches)})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'fzf filter timed out'}), 504)
    except Exception as e:
        _log(f'[fzf filter exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _h_fzf_86():
    """Fuzzy-search a directory. Body: {"query": "pattern", "path": "/some/dir", "type": "f|d|all"}"""
    body = _json_body()
    query = body.get('query', '')
    search_path = body.get('path', '.')
    file_type = body.get('type', 'all')
    exe = _find_tool('fzf')
    if not exe:
        return (jsonify({'error': 'fzf not installed', 'hint': 'Install with: winget install junegunn.fzf'}), 503)
    if not os.path.isdir(search_path):
        return (jsonify({'error': f'Directory not found: {search_path}'}), 404)
    try:
        fd_exe = shutil.which('fd')
        if fd_exe:
            type_arg = [] if file_type == 'all' else ['--type', file_type]
            list_cmd = [fd_exe, '--color', 'never', '--hidden', '--no-ignore', '--max-depth', '10']
            if type_arg:
                list_cmd.extend(type_arg)
            list_cmd.append('.')
            r_list = subprocess.run(list_cmd, cwd=search_path, capture_output=True, text=True, timeout=30)
            if r_list.returncode != 0 and (not r_list.stdout.strip()):
                _log(f"[fzf fd listing failed] {(r_list.stderr or '').strip()}")
                return (jsonify({'error': 'directory listing failed', 'detail': (r_list.stderr or '').strip()}), 500)
            items = [l for l in r_list.stdout.splitlines() if l]
        else:
            if os.name == 'nt':
                dir_cmd = ['cmd', '/c', 'dir', '/s', '/b']
                if file_type == 'f':
                    dir_cmd.append('/a:-d')
                r_list = subprocess.run(dir_cmd, cwd=search_path, capture_output=True, text=True, timeout=30)
                if r_list.returncode != 0 and (not r_list.stdout.strip()):
                    _log(f"[fzf dir listing failed] {(r_list.stderr or '').strip()}")
                    return (jsonify({'error': 'directory listing failed', 'detail': (r_list.stderr or '').strip()}), 500)
            else:
                find_cmd = ['find', '.', '-maxdepth', '10']
                if file_type == 'f':
                    find_cmd.extend(['-type', 'f'])
                elif file_type == 'd':
                    find_cmd.extend(['-type', 'd'])
                r_list = subprocess.run(find_cmd, cwd=search_path, capture_output=True, text=True, timeout=30)
                if r_list.returncode != 0:
                    _log(f"[fzf find listing partial/failed] {(r_list.stderr or '').strip()}")
            items = [l for l in r_list.stdout.splitlines() if l]
        if not query:
            return jsonify({'matches': items[:200], 'query': query, 'path': search_path, 'total_matches': len(items), 'truncated': len(items) > 200})
        stdin = '\n'.join(items)
        r = subprocess.run([exe, '--filter', str(query)], input=stdin, capture_output=True, text=True, timeout=15)
        if r.returncode == 1:
            return jsonify({'matches': [], 'query': query, 'path': search_path, 'total_input': len(items)})
        if r.returncode != 0:
            _log(f'[fzf search error] {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip() or 'fzf search failed'}), 500)
        matches = [m for m in r.stdout.strip().split('\n') if m]
        return jsonify({'matches': matches[:200], 'query': query, 'path': search_path, 'total_input': len(items), 'total_matches': len(matches), 'truncated': len(matches) > 200})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'fzf search timed out'}), 504)
    except Exception as e:
        _log(f'[fzf search exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _h_gsudo_87():
    """Run a command with elevated privileges via gsudo.
        Body: {"command": "whoami", "timeout": 30, "accept_elevation": true}
        Returns: {"stdout": "...", "stderr": "...", "exit_code": 0}
        """
    body = _json_body()
    if not body:
        return (jsonify({'error': 'JSON body required'}), 400)
    command = str(body.get('command', '')).strip()
    if not command:
        return _missing_field('command')
    try:
        timeout = int(body.get('timeout', 30))
    except (TypeError, ValueError):
        return (jsonify({'error': 'timeout must be an integer', 'command': command}), 400)
    if timeout <= 0:
        return (jsonify({'error': 'timeout must be positive', 'command': command}), 400)
    timeout = min(timeout, 120)
    accept = body.get('accept_elevation', False)
    exe = _find_tool('gsudo')
    if not exe:
        return (jsonify({'error': 'gsudo not found', 'install_hint': 'winget install gerardog.gsudo'}), 503)
    if not accept:
        return (jsonify({'warning': 'Elevation not accepted', 'hint': 'Set accept_elevation=true to confirm you want to run this elevated', 'command': command}), 403)
    try:
        import shlex
        args = [exe] + shlex.split(command, posix=os.name != 'nt')
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return jsonify({'stdout': r.stdout, 'stderr': r.stderr, 'exit_code': r.returncode, 'command': command})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'Command timed out after {timeout}s', 'command': command}), 504)
    except FileNotFoundError:
        return (jsonify({'error': 'gsudo executable disappeared', 'path': exe}), 500)
    except Exception as e:
        _log(f'gsudo run failed: {e}')
        return (jsonify({'error': str(e), 'command': command}), 500)

def _h_gsudo_88():
    """Check if gsudo has an active elevated session (cached credentials)."""
    exe = _find_tool('gsudo')
    if not exe:
        return (jsonify({'error': 'gsudo not found'}), 503)
    try:
        r = subprocess.run([exe, 'whoami'], capture_output=True, text=True, timeout=5)
        return jsonify({'elevated': r.returncode == 0, 'user': r.stdout.strip() if r.returncode == 0 else None})
    except Exception as e:
        return (jsonify({'error': str(e)}), 500)

_icacls_PERMISSION_ENTRY_RE = re.compile('^(.+?)\\s+((?:[A-Z]+(?:\\+[A-Z]+)*(?:\\([A-Z]+\\))*\\s*)+)$')

def _icacls__run_icacls(args, timeout=15):
    """Run icacls.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('icacls')
    if not exe:
        raise RuntimeError('icacls not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _icacls__parse_permissions(perm_str):
    """Parse an icacls permission string into structured entries.

    Format examples:
      BUILTIN\\Users:(OI)(CI)(RX)
      NT AUTHORITY\\SYSTEM:(F)
      DOMAIN\\User:(R,W,D)

    Returns list of dicts with user, access, and inheritance flags.
    """
    results = []
    remaining = perm_str
    while remaining:
        m = re.match('^(.+?):(\\(.*?\\))\\s*(\\(.*?\\))?\\s*(\\(.*?\\))?\\s*(\\(.*?\\))?\\s*(\\(.*?\\))?\\s*(.*)', remaining.strip())
        if m:
            user = m.group(1).strip()
            access = m.group(2).strip('()')
            inheritance_flags = []
            for g in [m.group(3), m.group(4), m.group(5), m.group(6)]:
                if g:
                    flag = g.strip('()')
                    inheritance_flags.append(flag)
            results.append({'user': user, 'access': access, 'inheritance': inheritance_flags if inheritance_flags else []})
            remaining = m.group(7).strip() if m.group(7) else ''
        else:
            break
    return results

def _icacls__clean_path(path):
    """Validate a Windows filesystem path."""
    p = str(path or '').strip()
    if not p:
        raise ValueError('path must not be empty')
    if len(p) > 32767:
        raise ValueError('path too long (max 32767 chars)')
    if '\x00' in p:
        raise ValueError('path cannot contain null bytes')
    for c in '|><&':
        if c in p:
            raise ValueError(f"path contains invalid character '{c}'")
    if p[0] in '/-':
        raise ValueError("path must not begin with '/' or '-'")
    return p

def _icacls__parse_icacls_output(text):
    """Parse icacls output into structured entries.

    icacls output format per file:
      <path> <user1>:(<perm>)[(<inheritance>)]...
      <user2>:(<perm>)[(<inheritance>)]...
    """
    entries = []
    lines = text.split('\n')
    current_entry = None
    for line in lines:
        stripped = line.rstrip('\r')
        if not stripped:
            continue
        if stripped.startswith('Successfully'):
            continue
        if stripped.startswith('processed file:'):
            continue
        m = _icacls_PERMISSION_ENTRY_RE.match(stripped)
        if m:
            path = m.group(1).strip()
            perm_str = m.group(2).strip()
            permissions = _icacls__parse_permissions(perm_str)
            entry = {'path': path.replace('\\', '/'), 'raw_acl': perm_str, 'permissions': permissions}
            entries.append(entry)
            current_entry = entry
        elif current_entry:
            trimmed = stripped.strip()
            if trimmed:
                permissions = _icacls__parse_permissions(trimmed)
                current_entry['permissions'].extend(permissions)
                current_entry['raw_acl'] += ' ' + trimmed
    return entries

def _icacls__clean_username(user):
    """Validate a username/group name for icacls."""
    u = str(user or '').strip()
    if not u:
        raise ValueError('user/group name must not be empty')
    if len(u) > 256:
        raise ValueError('user/group name too long (max 256 chars)')
    if '\x00' in u:
        raise ValueError('user/group name cannot contain null bytes')
    if u[0] in '/-':
        raise ValueError("user/group name must not begin with '/' or '-'")
    return u

def _h_icacls_89():
    """Display security descriptor for a file or folder."""
    try:
        from flask import request
        target = request.args.get('path', '')
    except Exception:
        return _missing_field('path (query param)')
    try:
        target = _icacls__clean_path(target)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('icacls')
    if not exe:
        return (jsonify({'ok': False, 'error': 'icacls not found'}), 503)
    try:
        stdout, stderr, rc = _icacls__run_icacls([target], timeout=15)
        if rc != 0 and 'Cannot find' in stdout:
            return (jsonify({'ok': False, 'error': f'path not found: {target}'}), 404)
        if rc != 0 and 'Access is denied' in stdout:
            return (jsonify({'ok': False, 'error': f'access denied: {target}'}), 403)
        parsed = _icacls__parse_icacls_output(stdout)
        return jsonify({'ok': rc == 0, 'path': target, 'entries': parsed, 'entry_count': len(parsed), 'exit_code': rc, 'raw_output': stdout.strip() if rc != 0 else None})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'icacls display timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_icacls_90():
    """Grant permissions to a user on a file/folder."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    target = body.get('path', '')
    user = body.get('user', '')
    perm = body.get('permission', 'R')
    inherit = body.get('inheritance', False)
    try:
        target = _icacls__clean_path(target)
        user = _icacls__clean_username(user)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    perm = str(perm).strip().upper()
    valid_perms = {'F', 'M', 'RX', 'R', 'W', 'D', 'RD', 'WD', 'AD', 'RE', 'WA', 'RC'}
    if perm not in valid_perms:
        return (jsonify({'ok': False, 'error': f"invalid permission '{perm}'. Valid: {', '.join(sorted(valid_perms))}"}), 400)
    exe = _find_tool('icacls')
    if not exe:
        return (jsonify({'ok': False, 'error': 'icacls not found'}), 503)
    if inherit:
        grant_str = f'{user}:(OI)(CI){perm}'
    else:
        grant_str = f'{user}:{perm}'
    args = [target, '/grant', grant_str]
    try:
        stdout, stderr, rc = _icacls__run_icacls(args, timeout=15)
        success = rc == 0
        return jsonify({'ok': success, 'path': target, 'user': user, 'permission': perm, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'icacls grant timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_icacls_91():
    """Deny permissions to a user on a file/folder."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    target = body.get('path', '')
    user = body.get('user', '')
    perm = body.get('permission', 'R')
    inherit = body.get('inheritance', False)
    try:
        target = _icacls__clean_path(target)
        user = _icacls__clean_username(user)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    perm = str(perm).strip().upper()
    valid_perms = {'F', 'M', 'RX', 'R', 'W', 'D', 'RD', 'WD', 'AD', 'RE', 'WA', 'RC'}
    if perm not in valid_perms:
        return (jsonify({'ok': False, 'error': f"invalid permission '{perm}'. Valid: {', '.join(sorted(valid_perms))}"}), 400)
    exe = _find_tool('icacls')
    if not exe:
        return (jsonify({'ok': False, 'error': 'icacls not found'}), 503)
    if inherit:
        deny_str = f'{user}:(OI)(CI){perm}'
    else:
        deny_str = f'{user}:{perm}'
    args = [target, '/deny', deny_str]
    try:
        stdout, stderr, rc = _icacls__run_icacls(args, timeout=15)
        success = rc == 0
        return jsonify({'ok': success, 'path': target, 'user': user, 'permission': perm, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'icacls deny timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_icacls_92():
    """Remove all permissions for a user on a file/folder."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    target = body.get('path', '')
    user = body.get('user', '')
    try:
        target = _icacls__clean_path(target)
        user = _icacls__clean_username(user)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('icacls')
    if not exe:
        return (jsonify({'ok': False, 'error': 'icacls not found'}), 503)
    try:
        stdout, stderr, rc = _icacls__run_icacls([target, '/remove', user], timeout=15)
        success = rc == 0
        return jsonify({'ok': success, 'path': target, 'user': user, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'icacls remove timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_icacls_93():
    """Set ownership of a file/folder."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    target = body.get('path', '')
    owner = body.get('owner', '')
    try:
        target = _icacls__clean_path(target)
        owner = _icacls__clean_username(owner)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('icacls')
    if not exe:
        return (jsonify({'ok': False, 'error': 'icacls not found'}), 503)
    try:
        stdout, stderr, rc = _icacls__run_icacls([target, '/setowner', owner, '/t', '/c'], timeout=30)
        success = rc == 0
        return jsonify({'ok': success, 'path': target, 'owner': owner, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'icacls setowner timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_icacls_94():
    """Enable or disable permission inheritance on a file/folder."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    target = body.get('path', '')
    mode = body.get('mode', 'enable')
    try:
        target = _icacls__clean_path(target)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    mode = str(mode).strip().lower()
    valid_modes = {'enable': 'e', 'disable': 'd', 'remove': 'r'}
    if mode not in valid_modes:
        return (jsonify({'ok': False, 'error': f"invalid mode '{mode}'. Use one of: enable, disable, remove"}), 400)
    exe = _find_tool('icacls')
    if not exe:
        return (jsonify({'ok': False, 'error': 'icacls not found'}), 503)
    try:
        stdout, stderr, rc = _icacls__run_icacls([target, f'/inheritance:{valid_modes[mode]}'], timeout=15)
        success = rc == 0
        return jsonify({'ok': success, 'path': target, 'mode': mode, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'icacls inheritance timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_icacls_95():
    """Save ACLs for files/folders to a backup file."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    target = body.get('path', '')
    acl_file = body.get('acl_file', '')
    try:
        target = _icacls__clean_path(target)
        acl_file = _icacls__clean_path(acl_file)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('icacls')
    if not exe:
        return (jsonify({'ok': False, 'error': 'icacls not found'}), 503)
    try:
        stdout, stderr, rc = _icacls__run_icacls([target, '/save', acl_file, '/t'], timeout=30)
        success = rc == 0
        return jsonify({'ok': success, 'path': target, 'acl_file': acl_file, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'icacls save timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_icacls_96():
    """Restore ACLs from a previously saved backup file."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    acl_file = body.get('acl_file', '')
    target = body.get('path', '')
    try:
        acl_file = _icacls__clean_path(acl_file)
        if target:
            target = _icacls__clean_path(target)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('icacls')
    if not exe:
        return (jsonify({'ok': False, 'error': 'icacls not found'}), 503)
    if not target:
        return (jsonify({'ok': False, 'error': 'target path is required for restore'}), 400)
    args = [target, '/restore', acl_file]
    try:
        stdout, stderr, rc = _icacls__run_icacls(args, timeout=30)
        success = rc == 0
        return jsonify({'ok': success, 'acl_file': acl_file, 'target': target, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'icacls restore timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _imagemagick__run_magick(args, timeout=30):
    """Run magick with args and return (stdout, stderr, exit_code)."""
    exe = _imagemagick__find_magick()
    if not exe:
        raise RuntimeError('ImageMagick not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _imagemagick__safe_path(path):
    """Validate and sanitize a file path."""
    if not path or not isinstance(path, str):
        raise ValueError('path must be a non-empty string')
    if len(path) > 4096:
        raise ValueError('path too long')
    normalized = os.path.normpath(path)
    if '..' in normalized.replace('\\', '/').split('/'):
        raise ValueError('path traversal detected')
    return path

def _imagemagick__find_magick():
    """Locate ImageMagick binaries — magick, convert, identify."""
    candidates = ['magick', 'magick.exe', 'convert', 'convert.exe', 'identify', 'identify.exe']
    for name in candidates:
        exe = shutil.which(name)
        if exe:
            return exe
    for p in ['C:\\Program Files\\ImageMagick-7.1.11-Q16-HDRI\\magick.exe', 'C:\\Program Files\\ImageMagick-7.1.10-Q16-HDRI\\magick.exe', 'C:\\Program Files\\ImageMagick-7.1.9-Q16-HDRI\\magick.exe', 'C:\\Program Files\\ImageMagick-7.0.10-Q16\\magick.exe', 'C:\\Program Files\\ImageMagick-7.0.11-Q16\\magick.exe', 'C:\\Program Files\\ImageMagick-7.0.12-Q16\\magick.exe', 'C:\\Program Files\\ImageMagick-7.0.13-Q16\\magick.exe', 'C:\\Program Files\\ImageMagick-7.0.14-Q16\\magick.exe', 'C:\\Program Files\\ImageMagick-6.9.12-Q16\\convert.exe', 'C:\\Program Files\\ImageMagick-6.9.11-Q16\\convert.exe']:
        if os.path.isfile(p):
            return p
    return None

def _h_imagemagick_97():
    """Get detailed image information: format, dimensions, colorspace, size."""
    body = _json_body()
    if body is None:
        return (jsonify({'ok': False, 'error': 'request body must be JSON'}), 400)
    path = body.get('path', '')
    if not path:
        return _missing_field('path')
    try:
        safe_path = _imagemagick__safe_path(path)
        if not os.path.isfile(safe_path):
            return (jsonify({'ok': False, 'error': f'file not found: {path}'}), 404)
        stdout, stderr, code = _imagemagick__run_magick(['identify', '-verbose', safe_path], timeout=15)
        if code != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'identify failed'}), 502)
        info = {'path': path, 'raw_output': stdout}
        for line in stdout.split('\n'):
            line_s = line.strip()
            if line_s.startswith('Format:'):
                info['format'] = line_s.split(':', 1)[1].strip()
            elif line_s.startswith('Geometry:'):
                info['geometry'] = line_s.split(':', 1)[1].strip()
            elif line_s.startswith('Depth:'):
                info['depth'] = line_s.split(':', 1)[1].strip()
            elif line_s.startswith('Colorspace:'):
                info['colorspace'] = line_s.split(':', 1)[1].strip()
            elif line_s.startswith('Channel statistics:'):
                pass
        simple, _, _ = _imagemagick__run_magick(['identify', safe_path], timeout=10)
        info['simple'] = simple.strip() if simple else None
        info['ok'] = True
        return jsonify(info)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'identify timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)

def _h_imagemagick_98():
    """Convert an image from one format to another with optional resize."""
    body = _json_body()
    if body is None:
        return (jsonify({'ok': False, 'error': 'request body must be JSON'}), 400)
    source = body.get('source', '')
    dest = body.get('dest', '')
    options = body.get('options', '')
    if not source or not dest:
        return _missing_field('source and dest')
    try:
        safe_source = _imagemagick__safe_path(source)
        safe_dest = _imagemagick__safe_path(dest)
        if not os.path.isfile(safe_source):
            return (jsonify({'ok': False, 'error': f'source file not found: {source}'}), 404)
        check_out, _, check_code = _imagemagick__run_magick(['identify', safe_source], timeout=10)
        if check_code != 0:
            return (jsonify({'ok': False, 'error': 'source is not a valid image file'}), 400)
        args = [safe_source]
        if options:
            safe_ops_re = re.compile('^(?:-(?:resize|quality|strip|colorspace|flatten|background|alpha|gravity|extent|crop|rotate|flip|flop|threshold|negate|modulate|blur|sharpen|enhance|normalize|contrast|brightness-contrast|level|gamma|auto-gamma|auto-level|auto-orient)(?:\\s+[a-zA-Z0-9_%#x.,+\\-]+)*)(?:\\s+-(?:resize|quality|strip|colorspace|flatten|background|alpha|gravity|extent|crop|rotate|flip|flop|threshold|negate|modulate|blur|sharpen|enhance|normalize|contrast|brightness-contrast|level|gamma|auto-gamma|auto-level|auto-orient)(?:\\s+[a-zA-Z0-9_%#x.,+\\-]+)*)*$')
            if not safe_ops_re.match(options.strip()):
                return (jsonify({'ok': False, 'error': 'options contain unsafe flags'}), 400)
            args.extend(options.strip().split())
        args.append(safe_dest)
        stdout, stderr, code = _imagemagick__run_magick(args, timeout=60)
        if code != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'conversion failed'}), 502)
        if os.path.isfile(safe_dest):
            size = os.path.getsize(safe_dest)
            return jsonify({'ok': True, 'source': source, 'dest': dest, 'size_bytes': size, 'stderr': stderr.strip() if stderr else None})
        else:
            return jsonify({'ok': True, 'source': source, 'dest': dest, 'note': 'conversion completed but output file not found — may be a streaming operation', 'stderr': stderr.strip() if stderr else None})
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'conversion timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)

def _h_imagemagick_99():
    """Compare two images and produce a difference metric."""
    body = _json_body()
    if body is None:
        return (jsonify({'ok': False, 'error': 'request body must be JSON'}), 400)
    ref = body.get('reference', '')
    test = body.get('test', '')
    metric = body.get('metric', 'AE')
    if not ref or not test:
        return _missing_field('reference and test')
    try:
        safe_ref = _imagemagick__safe_path(ref)
        safe_test = _imagemagick__safe_path(test)
        if not os.path.isfile(safe_ref):
            return (jsonify({'ok': False, 'error': f'reference file not found: {ref}'}), 404)
        if not os.path.isfile(safe_test):
            return (jsonify({'ok': False, 'error': f'test file not found: {test}'}), 404)
        valid_metrics = ['AE', 'MAE', 'RMSE', 'MSE', 'PAE', 'PSNR', 'SSIM', 'PHASH']
        if metric.upper() not in valid_metrics:
            return (jsonify({'ok': False, 'error': f"unsupported metric '{metric}'. Valid: {', '.join(valid_metrics)}"}), 400)
        stdout, stderr, code = _imagemagick__run_magick(['compare', '-metric', metric.upper(), safe_ref, safe_test, 'null:'], timeout=30)
        if code == 2:
            return (jsonify({'ok': False, 'error': stderr.strip() or stdout.strip() or 'compare failed'}), 502)
        metric_value = stderr.strip() if stderr else stdout.strip()
        return jsonify({'ok': True, 'reference': ref, 'test': test, 'metric': metric.upper(), 'value': metric_value, 'identical': code == 0})
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'compare timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)

def _h_imagemagick_100():
    """Resize an image to specified dimensions."""
    body = _json_body()
    if body is None:
        return (jsonify({'ok': False, 'error': 'request body must be JSON'}), 400)
    source = body.get('source', '')
    output = body.get('output', '')
    width = body.get('width', '')
    height = body.get('height', '')
    keep_aspect = body.get('keep_aspect', True)
    if not source or not output:
        return _missing_field('source and output')
    if not width and (not height):
        return _missing_field('width and/or height')
    try:
        w = None
        h = None
        for name, val in (('width', width), ('height', height)):
            if val in (None, ''):
                continue
            try:
                n = int(str(val).strip())
            except (TypeError, ValueError):
                raise ValueError(f'{name} must be an integer')
            if n < 0 or n > 20000:
                raise ValueError(f'{name} must be between 0 and 20000')
            if name == 'width':
                w = n
            else:
                h = n
        safe_source = _imagemagick__safe_path(source)
        safe_output = _imagemagick__safe_path(output)
        if not os.path.isfile(safe_source):
            return (jsonify({'ok': False, 'error': f'file not found: {source}'}), 404)
        geom = f"{(w if w is not None else '')}x{(h if h is not None else '')}"
        if keep_aspect:
            geom += '>'
        args = [safe_source, '-resize', geom, safe_output]
        stdout, stderr, code = _imagemagick__run_magick(args, timeout=60)
        if code != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'resize failed'}), 502)
        if os.path.isfile(safe_output):
            new_size = os.path.getsize(safe_output)
            id_stdout, _, _ = _imagemagick__run_magick(['identify', safe_output], timeout=10)
            return jsonify({'ok': True, 'source': source, 'output': output, 'size_bytes': new_size, 'geometry': geom, 'identify': id_stdout.strip() if id_stdout else None})
        return jsonify({'ok': True, 'source': source, 'output': output, 'geometry': geom})
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'resize timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)

_ipconfig_ADAPTER_NAME_RE = re.compile('^(Ethernet adapter|Wireless LAN adapter|Bluetooth|Tunnel adapter|Wi-Fi|Local Area Connection|Unknown adapter)\\s+(.+?):')

_ipconfig_ADAPTER_KEY_RE = re.compile('^\\s+(.+?)\\s+\\.\\s*:\\s+(.+)$')

_ipconfig_DNS_SUFFIX_RE = re.compile('^\\s+Primary Dns Suffix\\s+\\.\\s*:\\s+(.+)$')

_ipconfig_ROUTING_ENABLED_RE = re.compile('^\\s+IP Routing Enabled\\s+\\.\\s*:\\s+(.+)$')

_ipconfig_WINS_PROXY_RE = re.compile('^\\s+WINS Proxy Enabled\\s+\\.\\s*:\\s+(.+)$')

_ipconfig_NODE_TYPE_RE = re.compile('^\\s+Node Type\\s+\\.\\s*:\\s+(.+)$')

_ipconfig_HOST_NAME_RE = re.compile('^\\s+Host Name\\s+\\.\\s*:\\s+(.+)$')

def _ipconfig__parse_dns_cache(text):
    """Parse ipconfig /displaydns output."""
    records = []
    current = {}
    lines = text.split('\n')
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('---'):
            continue
        if stripped.startswith('    ') or stripped.startswith('\t'):
            if ':' in stripped:
                key, _, value = stripped.partition(':')
                key = key.strip()
                value = value.strip()
                mapped_key = {'Record Name': 'record_name', 'Record Type': 'record_type', 'Time To Live': 'ttl', 'Data Length': 'data_length', 'Section': 'section', 'A (Host) Record': 'a_record', 'AAAA Record': 'aaaa_record', 'CNAME Record': 'cname_record'}.get(key, key.lower().replace(' ', '_'))
                current[mapped_key] = value
        else:
            if current and ('record_name' in current or 'a_record' in current):
                records.append(current)
                current = {}
            if '---' not in stripped and (not stripped.startswith('Record Name')):
                current['record_name'] = stripped
    if current and ('record_name' in current or 'a_record' in current):
        records.append(current)
    return records

def _ipconfig__parse_ipconfig_all(text):
    """Parse ipconfig /all output into structured data."""
    result = {}
    host_info = {}
    adapters = []
    current_adapter = None
    lines = text.split('\n')
    for line in lines:
        stripped = line.rstrip('\r')
        m = _ipconfig_HOST_NAME_RE.match(line)
        if m:
            host_info['host_name'] = m.group(1).strip()
            continue
        m = _ipconfig_DNS_SUFFIX_RE.match(line)
        if m:
            host_info['primary_dns_suffix'] = m.group(1).strip()
            continue
        m = _ipconfig_NODE_TYPE_RE.match(line)
        if m:
            host_info['node_type'] = m.group(1).strip()
            continue
        m = _ipconfig_ROUTING_ENABLED_RE.match(line)
        if m:
            host_info['ip_routing_enabled'] = m.group(1).strip()
            continue
        m = _ipconfig_WINS_PROXY_RE.match(line)
        if m:
            host_info['wins_proxy_enabled'] = m.group(1).strip()
            continue
        m = _ipconfig_ADAPTER_NAME_RE.match(line)
        if m:
            if current_adapter:
                adapters.append(current_adapter)
            current_adapter = {'interface_type': m.group(1).strip(), 'name': m.group(2).strip().rstrip(':'), 'properties': []}
            continue
        if current_adapter:
            m = _ipconfig_ADAPTER_KEY_RE.match(line)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                current_adapter['properties'].append({'key': key, 'value': value})
    if current_adapter:
        adapters.append(current_adapter)
    result['host'] = host_info
    result['adapters'] = adapters
    result['adapter_count'] = len(adapters)
    return result

def _ipconfig__clean_adapter_name(name):
    """Validate an adapter name."""
    n = str(name or '').strip()
    if not n:
        raise ValueError('adapter name must not be empty')
    if len(n) > 256:
        raise ValueError('adapter name too long (max 256 chars)')
    if '\x00' in n:
        raise ValueError('adapter name cannot contain null bytes')
    return n

def _ipconfig__run_ipconfig(args, timeout=15):
    """Run ipconfig with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('ipconfig')
    if not exe:
        raise RuntimeError('ipconfig not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_ipconfig_101():
    """Get full network configuration for all adapters."""
    exe = _find_tool('ipconfig')
    if not exe:
        return (jsonify({'ok': False, 'error': 'ipconfig not found'}), 503)
    try:
        stdout, stderr, rc = _ipconfig__run_ipconfig(['/all'], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'ipconfig /all failed'}), 502)
        parsed = _ipconfig__parse_ipconfig_all(stdout)
        return jsonify({'ok': True, 'host': parsed['host'], 'adapters': parsed['adapters'], 'adapter_count': parsed['adapter_count']})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'ipconfig /all timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_ipconfig_102():
    """Renew DHCP lease for all adapters or a specific adapter."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    adapter = body.get('adapter', None)
    exe = _find_tool('ipconfig')
    if not exe:
        return (jsonify({'ok': False, 'error': 'ipconfig not found'}), 503)
    args = ['/renew']
    if adapter:
        try:
            adapter = _ipconfig__clean_adapter_name(adapter)
        except ValueError as e:
            return (jsonify({'ok': False, 'error': str(e)}), 400)
        args.append(adapter)
    try:
        stdout, stderr, rc = _ipconfig__run_ipconfig(args, timeout=30)
        return jsonify({'ok': rc == 0, 'adapter': adapter or 'all', 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'ipconfig /renew timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_ipconfig_103():
    """Release DHCP lease for all adapters or a specific adapter."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    adapter = body.get('adapter', None)
    exe = _find_tool('ipconfig')
    if not exe:
        return (jsonify({'ok': False, 'error': 'ipconfig not found'}), 503)
    args = ['/release']
    if adapter:
        try:
            adapter = _ipconfig__clean_adapter_name(adapter)
        except ValueError as e:
            return (jsonify({'ok': False, 'error': str(e)}), 400)
        args.append(adapter)
    try:
        stdout, stderr, rc = _ipconfig__run_ipconfig(args, timeout=30)
        return jsonify({'ok': rc == 0, 'adapter': adapter or 'all', 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'ipconfig /release timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_ipconfig_104():
    """Flush the DNS resolver cache."""
    exe = _find_tool('ipconfig')
    if not exe:
        return (jsonify({'ok': False, 'error': 'ipconfig not found'}), 503)
    try:
        stdout, stderr, rc = _ipconfig__run_ipconfig(['/flushdns'], timeout=15)
        return jsonify({'ok': rc == 0, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'ipconfig /flushdns timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_ipconfig_105():
    """Display the DNS resolver cache contents."""
    exe = _find_tool('ipconfig')
    if not exe:
        return (jsonify({'ok': False, 'error': 'ipconfig not found'}), 503)
    try:
        stdout, stderr, rc = _ipconfig__run_ipconfig(['/displaydns'], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'ipconfig /displaydns failed'}), 502)
        records = _ipconfig__parse_dns_cache(stdout)
        return jsonify({'ok': True, 'record_count': len(records), 'records': records[:200]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'ipconfig /displaydns timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_ipconfig_106():
    """Register DNS names with DHCP and refresh DNS registrations."""
    exe = _find_tool('ipconfig')
    if not exe:
        return (jsonify({'ok': False, 'error': 'ipconfig not found'}), 503)
    try:
        stdout, stderr, rc = _ipconfig__run_ipconfig(['/registerdns'], timeout=30)
        return jsonify({'ok': rc == 0, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'ipconfig /registerdns timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_ipconfig_107():
    """Show DHCP class ID for all adapters or a specific adapter."""
    try:
        from flask import request
        adapter = request.args.get('adapter', '')
    except Exception:
        adapter = ''
    exe = _find_tool('ipconfig')
    if not exe:
        return (jsonify({'ok': False, 'error': 'ipconfig not found'}), 503)
    args = ['/showclassid']
    if adapter:
        try:
            adapter = _ipconfig__clean_adapter_name(adapter)
        except ValueError as e:
            return (jsonify({'ok': False, 'error': str(e)}), 400)
        args.append(adapter)
    try:
        stdout, stderr, rc = _ipconfig__run_ipconfig(args, timeout=15)
        return jsonify({'ok': rc == 0, 'adapter': adapter or 'all', 'output': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'ipconfig /showclassid timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_ipconfig_108():
    """Set DHCP class ID for a specific adapter."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    adapter = body.get('adapter', '')
    class_id = body.get('class_id', '')
    try:
        adapter = _ipconfig__clean_adapter_name(adapter)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    cid = str(class_id or '').strip()
    if not cid:
        return _missing_field('class_id')
    if len(cid) > 256:
        return (jsonify({'ok': False, 'error': 'class_id too long (max 256 chars)'}), 400)
    exe = _find_tool('ipconfig')
    if not exe:
        return (jsonify({'ok': False, 'error': 'ipconfig not found'}), 503)
    try:
        stdout, stderr, rc = _ipconfig__run_ipconfig(['/setclassid', adapter, cid], timeout=15)
        return jsonify({'ok': rc == 0, 'adapter': adapter, 'class_id': cid, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'ipconfig /setclassid timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _just__find_justfile(requested_path=None):
    """Find a justfile or Justfile in the requested directory, or cwd."""
    search_dir = requested_path or os.getcwd()
    if not os.path.isdir(search_dir):
        return None
    for name in ('justfile', 'Justfile', '.justfile', '.Justfile'):
        candidate = os.path.join(search_dir, name)
        if os.path.isfile(candidate):
            return candidate
    return None

def _h_just_109():
    """List all recipes in a justfile. Query params: ?path=/some/dir"""
    exe = _find_tool('just')
    if not exe:
        return (jsonify({'error': 'just not installed', 'hint': 'Install with: winget install casey.just'}), 503)
    search_path = request.args.get('path', os.getcwd())
    justfile = _just__find_justfile(search_path)
    if not justfile:
        return (jsonify({'error': f'No justfile found in {search_path}', 'hint': "Create a file called 'justfile' with recipe definitions"}), 404)
    try:
        r = subprocess.run([exe, '--list', '--list-heading', ''], cwd=os.path.dirname(justfile), capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            _log(f'[just list error] {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip() or 'just --list failed'}), 500)
        recipes = {}
        for line in r.stdout.strip().split('\n'):
            if not line.strip():
                continue
            line = line.strip()
            if ' # ' in line:
                name, desc = line.split(' # ', 1)
                recipes[name.strip()] = desc.strip()
            else:
                recipes[line] = ''
        return jsonify({'justfile': justfile, 'recipes': recipes, 'total': len(recipes)})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'just --list timed out'}), 504)
    except Exception as e:
        _log(f'[just list exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _h_just_110():
    """Run a just recipe. Body: {"recipe": "build", "args": ["--release"], "path": "/some/dir"}"""
    body = _json_body()
    if not isinstance(body, dict):
        return (jsonify({'error': 'request body must be a JSON object'}), 400)
    recipe = body.get('recipe', '')
    args = body.get('args', [])
    run_path = body.get('path', os.getcwd())
    if not isinstance(recipe, str) or not recipe.strip():
        return (jsonify({'error': "'recipe' must be a non-empty string"}), 400)
    recipe = recipe.strip()
    if recipe.startswith('-') or any((c.isspace() for c in recipe)) or '\x00' in recipe:
        return (jsonify({'error': 'recipe name contains invalid characters'}), 400)
    if not isinstance(args, list):
        return (jsonify({'error': "'args' must be a list"}), 400)
    exe = _find_tool('just')
    if not exe:
        return (jsonify({'error': 'just not installed', 'hint': 'Install with: winget install casey.just'}), 503)
    justfile = _just__find_justfile(run_path)
    if not justfile:
        return (jsonify({'error': f'No justfile found in {run_path}', 'hint': "Create a 'justfile' with your recipes first"}), 404)
    try:
        cmd = [exe, '--', recipe]
        cmd.extend([str(a) for a in args])
        r = subprocess.run(cmd, cwd=os.path.dirname(justfile), capture_output=True, text=True, timeout=120)
        return jsonify({'recipe': recipe, 'justfile': justfile, 'exit_code': r.returncode, 'stdout': r.stdout.strip()[-10000:], 'stderr': r.stderr.strip()[-5000:], 'success': r.returncode == 0})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'Recipe execution timed out (120s limit)', 'recipe': recipe}), 504)
    except Exception as e:
        _log(f'[just run exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _h_just_111():
    """Dump the parsed justfile as JSON. Query params: ?path=/some/dir"""
    exe = _find_tool('just')
    if not exe:
        return (jsonify({'error': 'just not installed', 'hint': 'Install with: winget install casey.just'}), 503)
    search_path = request.args.get('path', os.getcwd())
    justfile = _just__find_justfile(search_path)
    if not justfile:
        return (jsonify({'error': f'No justfile found in {search_path}'}), 404)
    try:
        r = subprocess.run([exe, '--dump', '--dump-format', 'json'], cwd=os.path.dirname(justfile), capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            _log(f'[just dump error] {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip() or 'just --dump failed'}), 500)
        return jsonify({'justfile': justfile, 'dump': json.loads(r.stdout) if r.stdout.strip() else {}})
    except json.JSONDecodeError:
        return jsonify({'justfile': justfile, 'dump_raw': r.stdout.strip()[:10000], 'note': 'JSON parse failed, returning raw output'})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'just --dump timed out'}), 504)
    except Exception as e:
        _log(f'[just dump exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _komorebi__clean_count(value):
    try:
        c = int(value) if value is not None else 1
    except (TypeError, ValueError):
        raise ValueError('count must be an integer')
    return max(1, min(c, 50))

def _komorebi__clean_action(value):
    action = str(value or '').strip().lower()
    if not action:
        raise ValueError('action must not be empty')
    if '\x00' in action:
        raise ValueError('action cannot contain null bytes')
    if action.startswith('-'):
        raise ValueError("action cannot start with '-'")
    if not action.replace('-', '').replace('_', '').isalnum():
        raise ValueError('action contains invalid characters')
    return action

def _komorebi__find_komorebic():
    return shutil.which('komorebic') or shutil.which('komorebic.exe')

def _h_komorebi_112():
    exe = _komorebi__find_komorebic()
    if not exe:
        return (jsonify({'ok': False, 'error': 'komorebic command not found on PATH', 'hint': 'Install komorebi from https://github.com/LGUG2Z/komorebi'}), 503)
    try:
        result = subprocess.run([exe, 'state'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
    except OSError as exc:
        _log(f'[komorebi] state failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'komorebic state timed out'}), 504)
    ok = result.returncode == 0
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

def _h_komorebi_113():
    data = _json_body()
    missing = _missing_field(data, 'action')
    if missing:
        return missing
    exe = _komorebi__find_komorebic()
    if not exe:
        return (jsonify({'ok': False, 'error': 'komorebic command not found on PATH', 'hint': 'Install komorebi from https://github.com/LGUG2Z/komorebi'}), 503)
    try:
        action = _komorebi__clean_action(data.get('action'))
        count = _komorebi__clean_count(data.get('count'))
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    command = [exe, action]
    extras = data.get('args')
    if extras:
        if not isinstance(extras, list):
            return (jsonify({'ok': False, 'error': 'args must be a list'}), 400)
        for arg in extras:
            s = str(arg)
            if s.startswith('-') or '\x00' in s:
                return (jsonify({'ok': False, 'error': f'invalid arg: {s!r}'}), 400)
            command.append(s)
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, shell=False)
    except subprocess.TimeoutExpired as exc:
        _log(f'[komorebi] command timed out after 15s action={action}')
        return (jsonify({'ok': False, 'error': f'komorebic command timed out after 15s', 'stdout': exc.stdout or '', 'stderr': exc.stderr or ''}), 504)
    except OSError as exc:
        _log(f'[komorebi] launch failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[komorebi] action={action} exit={result.returncode}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'action': action, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

def _h_komorebi_114():
    data = _json_body()
    missing = _missing_field(data, 'workspace')
    if missing:
        return missing
    exe = _komorebi__find_komorebic()
    if not exe:
        return (jsonify({'ok': False, 'error': 'komorebic command not found on PATH', 'hint': 'Install komorebi from https://github.com/LGUG2Z/komorebi'}), 503)
    try:
        workspace = int(data.get('workspace', 0))
        if workspace < 0 or workspace > 9:
            raise ValueError('workspace must be 0-9')
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    subcommand = (data.get('subcommand') or 'focus').strip().lower()
    if subcommand not in ('focus', 'move'):
        return (jsonify({'ok': False, 'error': "subcommand must be 'focus' or 'move'"}), 400)
    cmd_subcommand = 'focus-workspace' if subcommand == 'focus' else 'move-to-workspace'
    command = [exe, cmd_subcommand, str(workspace)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'workspace command timed out'}), 504)
    except OSError as exc:
        _log(f'[komorebi] workspace failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[komorebi] workspace subcommand={subcommand} workspace={workspace} exit={result.returncode}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'subcommand': subcommand, 'workspace': workspace, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

_kopia__STORAGE_FLAGS = {'filesystem': ('filesystem', '--path'), 's3': ('s3', '--bucket'), 'gcs': ('gcs', '--bucket'), 'azure': ('azure', '--container')}

def _kopia__storage_connect_args(storage_type, location):
    """Build the positional provider + flag args for repository connect/create."""
    provider, flag = _kopia__STORAGE_FLAGS[storage_type]
    return [provider, flag, location]

def _kopia__run_kopia(args, timeout=60):
    """Run kopia with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('kopia')
    if not exe:
        raise RuntimeError('kopia not found on system')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_kopia_115():
    """Get kopia version information."""
    try:
        stdout, stderr, rc = _kopia__run_kopia(['version'], timeout=10)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'kopia version check failed'}), 502)
        return jsonify({'ok': True, 'version': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'kopia timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_kopia_116():
    """Get kopia repository status and configuration."""
    try:
        stdout, stderr, rc = _kopia__run_kopia(['status'], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'kopia status check failed', 'connected': False}), 200)
        try:
            json_out, _, json_rc = _kopia__run_kopia(['status', '--json'], timeout=15)
            if json_rc == 0 and json_out.strip():
                parsed = json_lib.loads(json_out)
                return jsonify({'ok': True, 'connected': True, 'status': parsed, 'raw': stdout.strip()})
        except (json_lib.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired):
            pass
        return jsonify({'ok': True, 'connected': True, 'raw': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'kopia timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_kopia_117():
    """List available snapshots. Optionally filter by path or source hostname.

        Query params:
          - path: filter snapshots by source path (optional)
          - host: filter by hostname (optional)
          - all: if true, show all snapshots (default: false, shows latest only)
        """
    try:
        from flask import request
        path_filter = request.args.get('path', '')
        host_filter = request.args.get('host', '')
        show_all = request.args.get('all', '').lower() in ('true', '1', 'yes')
        args = ['snapshot', 'list']
        if show_all:
            args.append('--all')
        if path_filter:
            args.extend(['--path', path_filter])
        if host_filter:
            args.extend(['--host', host_filter])
        stdout, stderr, rc = _kopia__run_kopia(args, timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'kopia snapshot list failed'}), 502)
        json_args = args.copy()
        json_args.append('--json')
        try:
            json_out, _, json_rc = _kopia__run_kopia(json_args, timeout=30)
            if json_rc == 0 and json_out.strip():
                parsed = json_lib.loads(json_out)
                snaps = parsed if isinstance(parsed, list) else [parsed]
                return jsonify({'ok': True, 'count': len(snaps), 'snapshots': snaps})
        except (json_lib.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired):
            pass
        return jsonify({'ok': True, 'raw': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'kopia timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_kopia_118():
    """List all configured backup policies."""
    try:
        stdout, stderr, rc = _kopia__run_kopia(['policy', 'list'], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'kopia policy list failed'}), 502)
        try:
            json_out, _, json_rc = _kopia__run_kopia(['policy', 'list', '--json'], timeout=15)
            if json_rc == 0 and json_out.strip():
                parsed = json_lib.loads(json_out)
                policies = parsed if isinstance(parsed, list) else [parsed]
                return jsonify({'ok': True, 'count': len(policies), 'policies': policies})
        except (json_lib.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired):
            pass
        return jsonify({'ok': True, 'raw': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'kopia timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_kopia_119():
    """Connect to an existing kopia repository.

        Body:
          - storage_type: "filesystem" (default), "s3", "gcs", "azure"
          - path_or_bucket: path to repo dir or bucket name (required)
          - password: repository password (highly recommended to set)
          - hostname: optional hostname to use for snapshots
        """
    body = _json_body()
    storage_type = str(body.get('storage_type') or 'filesystem').strip().lower()
    if storage_type not in _kopia__STORAGE_FLAGS:
        return (jsonify({'ok': False, 'error': f"Unsupported storage_type '{storage_type}'. Valid: {', '.join(sorted(_kopia__STORAGE_FLAGS))}"}), 400)
    location = (body.get('path_or_bucket') or body.get('location') or '').strip()
    password = body.get('password') or ''
    hostname = str(body.get('hostname') or '').strip()
    if not location:
        return (jsonify({'ok': False, 'error': 'path_or_bucket (storage location) is required'}), 400)
    if location.startswith('-'):
        return (jsonify({'ok': False, 'error': "storage location must not begin with '-'"}), 400)
    args = ['repository', 'connect'] + _kopia__storage_connect_args(storage_type, location)
    if hostname:
        args.extend(['--override-hostname', hostname])
    env = os.environ.copy()
    if password:
        env['KOPIA_PASSWORD'] = password
    else:
        _log('[kopia] WARNING: No password provided for repository connection')
    exe = _find_tool('kopia')
    if not exe:
        return (jsonify({'ok': False, 'error': 'kopia not found'}), 503)
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'kopia connect failed'}), 502)
        return jsonify({'ok': True, 'storage_type': storage_type, 'location': location, 'output': result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'kopia timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_kopia_120():
    """Create a new kopia repository.

        Body:
          - storage_type: "filesystem" (default), "s3", "gcs", "azure"
          - path_or_bucket: path to repo dir or bucket name (required)
          - password: repository password (required)
          - max_revision_size: optional max per-revision size
          - hostname: optional hostname
        """
    body = _json_body()
    storage_type = str(body.get('storage_type') or 'filesystem').strip().lower()
    if storage_type not in _kopia__STORAGE_FLAGS:
        return (jsonify({'ok': False, 'error': f"Unsupported storage_type '{storage_type}'. Valid: {', '.join(sorted(_kopia__STORAGE_FLAGS))}"}), 400)
    location = (body.get('path_or_bucket') or body.get('location') or '').strip()
    password = body.get('password') or ''
    hostname = str(body.get('hostname') or '').strip()
    max_revision = body.get('max_revision_size')
    if not location:
        return (jsonify({'ok': False, 'error': 'path_or_bucket (storage location) is required'}), 400)
    if location.startswith('-'):
        return (jsonify({'ok': False, 'error': "storage location must not begin with '-'"}), 400)
    if not password:
        return (jsonify({'ok': False, 'error': 'password is required for a new repository'}), 400)
    args = ['repository', 'create'] + _kopia__storage_connect_args(storage_type, location)
    if hostname:
        args.extend(['--override-hostname', hostname])
    if max_revision:
        args.extend(['--max-revision-size', str(max_revision)])
    env = os.environ.copy()
    env['KOPIA_PASSWORD'] = password
    exe = _find_tool('kopia')
    if not exe:
        return (jsonify({'ok': False, 'error': 'kopia not found'}), 503)
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'kopia create repo failed'}), 502)
        return jsonify({'ok': True, 'storage_type': storage_type, 'location': location, 'output': result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'kopia timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_kopia_121():
    """Run kopia maintenance tasks (blob cleanup, data migration, etc.)."""
    body = _json_body()
    full = body.get('full', False)
    safe = body.get('safe', True)
    args = ['maintenance', 'run']
    if full:
        args.append('--full')
    if not safe:
        args.append('--safety=none')
    try:
        stdout, stderr, rc = _kopia__run_kopia(args, timeout=300)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'kopia maintenance failed'}), 502)
        return jsonify({'ok': True, 'full': full, 'output': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'kopia maintenance timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_kopia_122():
    """Disconnect from the current kopia repository (requires confirmation)."""
    body = _json_body()
    confirm = body.get('confirm', False)
    if not confirm:
        return (jsonify({'ok': False, 'error': "Confirmation required — set 'confirm: true' to proceed. Disconnects from current repository. Data remains in the repository."}), 400)
    delete_config = body.get('delete_config', False)
    args = ['repository', 'disconnect']
    if delete_config:
        args.append('--delete-config')
    try:
        stdout, stderr, rc = _kopia__run_kopia(args, timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'kopia disconnect failed'}), 502)
        return jsonify({'ok': True, 'output': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'kopia timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

_llama_cpp__DEFAULT_PORTS = [8080, 8081, 8082]

_llama_cpp__SERVER_URL_ENV = 'LLAMA_CPP_SERVER_URL'

def _llama_cpp__http(base, method, path, payload=None, timeout=120):
    url = base + path
    data = None
    headers = {'Content-Type': 'application/json'}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            try:
                return (resp.status, json.loads(raw), raw)
            except json.JSONDecodeError:
                return (resp.status, None, raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            return (e.code, json.loads(raw), raw)
        except json.JSONDecodeError:
            return (e.code, None, raw)
    except urllib.error.URLError as e:
        return (0, None, str(e.reason))
    except OSError as e:
        # socket.timeout / connection reset raised during resp.read() on slow responses
        return (0, None, str(e))

def _llama_cpp__server_status(base):
    status, j, _ = _llama_cpp__http(base, 'GET', '/health', timeout=5)
    return (status == 200, j)

def _llama_cpp__server_base(body=None):
    """Resolve the llama-server base URL.

    Priority: explicit request base_url > env var > first reachable default port.
    """
    if isinstance(body, dict):
        explicit = (body.get('base_url') or body.get('server') or '').strip()
        if explicit:
            if not explicit.startswith(('http://', 'https://')):
                explicit = 'http://' + explicit
            return explicit.rstrip('/')
    env = os.environ.get(_llama_cpp__SERVER_URL_ENV, '').strip()
    if env:
        if not env.startswith(('http://', 'https://')):
            env = 'http://' + env
        return env.rstrip('/')
    for port in _llama_cpp__DEFAULT_PORTS:
        base = f'http://127.0.0.1:{port}'
        try:
            with urllib.request.urlopen(base + '/health', timeout=2) as resp:
                if resp.status == 200:
                    return base
        except Exception:
            continue
    return 'http://127.0.0.1:8080'

def _h_llama_cpp_123():
    base = _llama_cpp__server_base(request.args.to_dict() or None)
    ok, j = _llama_cpp__server_status(base)
    return (jsonify({'reachable': ok, 'base_url': base, 'health': j if isinstance(j, dict) else {'status': j}}), 200 if ok else 503)

def _h_llama_cpp_124():
    base = _llama_cpp__server_base(request.args.to_dict() or None)
    status, j, _ = _llama_cpp__http(base, 'GET', '/v1/models', timeout=10)
    if status == 200 and isinstance(j, dict):
        data = j.get('data') or []
        return jsonify({'count': len(data), 'models': data, 'base_url': base})
    return (jsonify({'error': 'could not list models', 'base_url': base, 'detail': j}), 503)

def _h_llama_cpp_125():
    body = _json_body()
    prompt = body.get('prompt')
    if prompt is None:
        return _missing_field('prompt')
    base = _llama_cpp__server_base(body)
    try:
        max_tokens = int(body.get('max_tokens', 256))
        temperature = float(body.get('temperature', 0.8))
    except (TypeError, ValueError):
        return (jsonify({'error': 'max_tokens must be an integer and temperature must be a number'}), 400)
    payload = {'prompt': str(prompt), 'max_tokens': max_tokens, 'temperature': temperature, 'stream': False}
    for opt in ('top_p', 'top_k', 'repeat_penalty', 'stop', 'seed'):
        if body.get(opt) is not None:
            payload[opt] = body[opt]
    status, j, _ = _llama_cpp__http(base, 'POST', '/v1/completions', payload, timeout=600)
    if status == 200 and isinstance(j, dict):
        choices = j.get('choices') or []
        text = ''
        if choices:
            text = (choices[0].get('text') or '') or ''
        return jsonify({'base_url': base, 'text': text, 'usage': j.get('usage'), 'model': j.get('model')})
    return (jsonify({'error': f'completion failed (status {status})', 'detail': j}), 502)

def _h_llama_cpp_126():
    body = _json_body()
    messages = body.get('messages')
    if not isinstance(messages, list) or not messages:
        return _missing_field('messages')
    base = _llama_cpp__server_base(body)
    try:
        max_tokens = int(body.get('max_tokens', 256))
        temperature = float(body.get('temperature', 0.8))
    except (TypeError, ValueError):
        return (jsonify({'error': 'max_tokens must be an integer and temperature must be a number'}), 400)
    payload = {'messages': messages, 'max_tokens': max_tokens, 'temperature': temperature, 'stream': False}
    for opt in ('top_p', 'top_k', 'repeat_penalty', 'stop', 'seed'):
        if body.get(opt) is not None:
            payload[opt] = body[opt]
    status, j, _ = _llama_cpp__http(base, 'POST', '/v1/chat/completions', payload, timeout=600)
    if status == 200 and isinstance(j, dict):
        choices = j.get('choices') or []
        msg = {}
        if choices:
            msg = choices[0].get('message') or {}
        return jsonify({'base_url': base, 'message': msg, 'usage': j.get('usage'), 'model': j.get('model')})
    return (jsonify({'error': f'chat failed (status {status})', 'detail': j}), 502)

def _h_llama_cpp_127():
    body = _json_body()
    text = body.get('input') or body.get('prompt')
    if text is None:
        return _missing_field('input')
    base = _llama_cpp__server_base(body)
    payload = {'input': text}
    if body.get('model'):
        payload['model'] = str(body['model'])
    status, j, _ = _llama_cpp__http(base, 'POST', '/v1/embeddings', payload, timeout=300)
    if status == 200 and isinstance(j, dict):
        data = j.get('data') or [{}]
        emb = data[0].get('embedding') if data else None
        return jsonify({'base_url': base, 'dimensions': len(emb) if isinstance(emb, list) else None, 'embedding': emb, 'model': j.get('model')})
    return (jsonify({'error': f'embeddings failed (status {status})', 'detail': j}), 502)

def _mkcert__validate_output_name(name, field):
    """Validate an output filename: no path separators or parent traversal."""
    n = str(name or '').strip()
    if not n:
        raise ValueError(f'{field} must not be empty')
    if '\x00' in n:
        raise ValueError(f'{field} cannot contain null bytes')
    if '/' in n or '\\' in n or '..' in n:
        raise ValueError(f"{field} must be a plain filename (no path separators or '..')")
    return n

def _mkcert__run_mkcert(args, timeout=30, cwd=None, env=None):
    """Run mkcert with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('mkcert')
    if not exe:
        raise RuntimeError('mkcert not found on system')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    return (result.stdout, result.stderr, result.returncode)

def _h_mkcert_128():
    """Get mkcert version information."""
    try:
        stdout, stderr, rc = _mkcert__run_mkcert(['-version'], timeout=10)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'mkcert version check failed'}), 502)
        version = stdout.strip()
        m = re.search('v?(\\d+\\.\\d+(?:\\.\\d+)?)', version)
        return jsonify({'ok': True, 'version_raw': version, 'version': m.group(1) if m else version})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'mkcert timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_mkcert_129():
    """Install the local CA into system or browser trust stores.

        Options:
          - trust_store: "system" (default), "nss" (Firefox), "java", or "all"
        """
    body = _json_body()
    trust_store = str(body.get('trust_store') or 'system').strip().lower()
    valid_stores = ('system', 'nss', 'java', 'all')
    if trust_store not in valid_stores:
        return (jsonify({'ok': False, 'error': f"Invalid trust_store. Valid: {', '.join(valid_stores)}"}), 400)
    try:
        if trust_store == 'all':
            trust_stores = 'system,nss,java'
        elif trust_store == 'nss':
            trust_stores = 'nss'
        elif trust_store == 'java':
            trust_stores = 'java'
        else:
            trust_stores = 'system'
        env = os.environ.copy()
        env['TRUST_STORES'] = trust_stores
        stdout, stderr, rc = _mkcert__run_mkcert(['-install'], timeout=30, env=env)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'mkcert CA install failed'}), 502)
        return jsonify({'ok': True, 'trust_store': trust_store, 'output': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'mkcert timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_mkcert_130():
    """Generate a locally-trusted TLS certificate for given domains.

        Body:
          - domains: list of domain names (required, min 1)
          - output_dir: directory to write cert/key files (default: current dir)
          - cert_file: output cert filename (default: cert.pem)
          - key_file: output key filename (default: key.pem)
          - p12: if true, also export as PKCS12 (default: false)
          - ec: if true, use ECDSA key (default: false)
        """
    body = _json_body()
    domains = body.get('domains')
    if not domains or not isinstance(domains, list) or len(domains) == 0:
        return _missing_field('domains (list, min 1)')
    cleaned_domains = []
    for d in domains:
        if not isinstance(d, str) or not d.strip():
            return (jsonify({'ok': False, 'error': 'Each domain must be a non-empty string'}), 400)
        d = d.strip()
        if d.startswith('-'):
            return (jsonify({'ok': False, 'error': f"domain '{d}' must not start with '-'"}), 400)
        cleaned_domains.append(d)
    domains = cleaned_domains
    output_dir = str(body.get('output_dir') or '.').strip()
    try:
        cert_file = _mkcert__validate_output_name(body.get('cert_file') or 'cert.pem', 'cert_file')
        key_file = _mkcert__validate_output_name(body.get('key_file') or 'key.pem', 'key_file')
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    p12 = body.get('p12', False)
    ec = body.get('ec', False)
    args = []
    if ec:
        args.append('-ecdsa')
    if p12:
        args.append('-pkcs12')
    args.extend(['-cert-file', cert_file, '-key-file', key_file])
    p12_file = None
    if p12:
        p12_file = cert_file.rsplit('.', 1)[0] + '.p12'
        args.extend(['-p12-file', p12_file])
    args.extend(domains)
    try:
        stdout, stderr, rc = _mkcert__run_mkcert(args, timeout=30, cwd=output_dir)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'mkcert certificate generation timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    if rc != 0:
        return (jsonify({'ok': False, 'error': stderr.strip() or 'mkcert certificate generation failed'}), 502)
    result = {'ok': True, 'domains': domains, 'cert_file': os.path.join(output_dir, cert_file), 'key_file': os.path.join(output_dir, key_file), 'output': stdout.strip()}
    if p12:
        result['p12_file'] = os.path.join(output_dir, p12_file)
    return jsonify(result)

def _h_mkcert_131():
    """Get the location of the mkcert CA root certificate and key."""
    try:
        caroot_args = ['-CAROOT']
        stdout, stderr, rc = _mkcert__run_mkcert(caroot_args, timeout=10)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'mkcert CAROOT failed'}), 502)
        caroot_path = stdout.strip()
        root_ca_pem = os.path.join(caroot_path, 'rootCA.pem')
        root_ca_key = os.path.join(caroot_path, 'rootCA-key.pem')
        return jsonify({'ok': True, 'caroot_dir': caroot_path, 'root_ca_pem': root_ca_pem if os.path.isfile(root_ca_pem) else None, 'root_ca_key': root_ca_key if os.path.isfile(root_ca_key) else None, 'ca_installed': os.path.isfile(root_ca_pem)})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'mkcert timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_mkcert_132():
    """Uninstall the local CA from trust stores (requires confirmation)."""
    body = _json_body()
    confirm = body.get('confirm', False)
    if confirm is not True:
        return (jsonify({'ok': False, 'error': "Confirmation required — set 'confirm: true' to proceed. This removes the mkcert CA from the system trust store."}), 400)
    try:
        stdout, stderr, rc = _mkcert__run_mkcert(['-uninstall'], timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'mkcert CA uninstall failed'}), 502)
        return jsonify({'ok': True, 'output': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'mkcert timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

_netsh_READONLY_CONTEXTS = {'interface': ['show', 'dump'], 'wlan': ['show'], 'advfirewall': ['show'], 'dnsclient': ['show'], 'winhttp': ['show'], 'http': ['show'], 'bridge': ['show']}

_netsh_CONTEXTS = ['interface', 'wlan', 'advfirewall', 'dnsclient', 'winhttp', 'http', 'bridge', 'ras']

def _netsh__run_netsh(context, *args, timeout=15):
    """Run netsh <context> <args> and return (stdout, stderr, exit_code)."""
    exe = _find_tool('netsh')
    if not exe:
        raise RuntimeError('netsh not found')
    safe_args = _netsh__clean_netsh_command([context] + list(args))
    result = subprocess.run([exe] + safe_args, capture_output=True, text=True, timeout=timeout, errors='replace', stdin=subprocess.DEVNULL)
    return (result.stdout, result.stderr, result.returncode)

def _netsh__clean_context(value):
    """Validate that the requested context is in our allowed list."""
    ctx = str(value or '').strip().lower()
    if ctx not in _netsh_CONTEXTS:
        raise ValueError(f"unsupported netsh context '{ctx}'. Allowed: {', '.join(_netsh_CONTEXTS)}")
    return ctx

def _netsh__clean_netsh_command(args_list, context_readonly=True):
    """Validate and sanitize netsh arguments to prevent injection.

    Each argument must be alphanumeric, a colon-separated key=value,
    or a common netsh flag (show, set, add, delete, dump, help, ?).
    """
    allowed_tokens_re = re.compile('^[a-zA-Z0-9_\\-.:=?@/\\\\+*]+$')
    for arg in args_list:
        if not allowed_tokens_re.match(arg):
            raise ValueError(f'netsh argument contains disallowed characters: {arg!r}')
        if len(arg) > 256:
            raise ValueError(f'netsh argument too long: {len(arg)} chars (max 256)')
        if '\x00' in arg:
            raise ValueError('netsh argument contains null bytes')
    return args_list

def _h_netsh_133():
    """Show network interface configuration (IP, DNS, interfaces)."""
    try:
        results = {}
        for sub_cmd in ['interface', 'interface ip', 'interface ipv4', 'interface ipv6']:
            try:
                parts = sub_cmd.split()
                stdout, stderr, rc = _netsh__run_netsh(*parts, 'show', 'config', timeout=15)
                results[sub_cmd.replace(' ', '_')] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results[sub_cmd] = str(e)
        stdout, stderr, rc = _netsh__run_netsh('interface', 'show', 'interface', timeout=15)
        results['interfaces'] = stdout.strip() if rc == 0 else stderr.strip()
        return jsonify({'ok': True, 'results': results})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_netsh_134():
    """Show Wi-Fi profiles and interfaces."""
    try:
        results = {}
        try:
            stdout, stderr, rc = _netsh__run_netsh('wlan', 'show', 'interfaces', timeout=15)
            results['interfaces'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['interfaces'] = str(e)
        try:
            stdout, stderr, rc = _netsh__run_netsh('wlan', 'show', 'profiles', timeout=15)
            results['profiles'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['profiles'] = str(e)
        try:
            stdout, stderr, rc = _netsh__run_netsh('wlan', 'show', 'hostednetwork', timeout=10)
            results['hosted_network'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['hosted_network'] = str(e)
        return jsonify({'ok': True, 'results': results})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_netsh_135():
    """Get detailed Wi-Fi profile info by name."""
    name = None
    try:
        from flask import request
        name = request.args.get('name', '')
    except Exception:
        pass
    if not name:
        return _missing_field('name (query param)')
    try:
        stdout, stderr, rc = _netsh__run_netsh('wlan', 'show', 'profile', f'name={name}', 'key=clear', timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or f"Wi-Fi profile '{name}' not found"}), 404)
        return jsonify({'ok': True, 'profile_name': name, 'details': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'netsh wlan profile timed out'}), 504)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_netsh_136():
    """Show Windows Firewall rules and state."""
    try:
        results = {}
        try:
            stdout, stderr, rc = _netsh__run_netsh('advfirewall', 'show', 'allprofiles', timeout=15)
            results['profiles_state'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['profiles_state'] = str(e)
        try:
            stdout, stderr, rc = _netsh__run_netsh('advfirewall', 'show', 'global', timeout=15)
            results['global_settings'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['global_settings'] = str(e)
        try:
            stdout, stderr, rc = _netsh__run_netsh('advfirewall', 'show', 'currentprofile', timeout=15)
            results['current_profile'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['current_profile'] = str(e)
        return jsonify({'ok': True, 'results': results})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_netsh_137():
    """Show DNS client cache and configuration."""
    try:
        results = {}
        try:
            stdout, stderr, rc = _netsh__run_netsh('dnsclient', 'show', 'state', timeout=15)
            results['cache_state'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['cache_state'] = str(e)
        try:
            stdout, stderr, rc = _netsh__run_netsh('dnsclient', 'show', 'dnssec', timeout=10)
            results['dnssec'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['dnssec'] = str(e)
        try:
            stdout, stderr, rc = _netsh__run_netsh('dnsclient', 'show', 'dohset', timeout=10)
            results['doh'] = stdout.strip() if rc == 0 else stderr.strip()
        except Exception as e:
            results['doh'] = str(e)
        return jsonify({'ok': True, 'results': results})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_netsh_138():
    """Show WinHTTP proxy settings."""
    try:
        stdout, stderr, rc = _netsh__run_netsh('winhttp', 'show', 'proxy', timeout=10)
        return jsonify({'ok': rc == 0, 'proxy_config': stdout.strip() if rc == 0 else stderr.strip(), 'exit_code': rc})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'netsh winhttp proxy timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_netsh_139():
    """Run an arbitrary read-only netsh command. Only 'show' and 'dump' subcommands allowed for safety."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    context = str(body.get('context', '')).strip()
    command = str(body.get('command', '')).strip()
    if not context:
        return (jsonify({'ok': False, 'error': 'Missing required field: context'}), 400)
    try:
        context = _netsh__clean_context(context)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    if not command:
        return (jsonify({'ok': False, 'error': 'Missing required field: command'}), 400)
    cmd_parts = command.split()
    if not cmd_parts:
        return (jsonify({'ok': False, 'error': 'Missing required field: command'}), 400)
    allowed = _netsh_READONLY_CONTEXTS.get(context)
    if not allowed or cmd_parts[0].lower() not in allowed:
        return (jsonify({'ok': False, 'error': f"Context '{context}' only allows read-only subcommands: {', '.join(allowed or ['show'])}"}), 400)
    try:
        stdout, stderr, rc = _netsh__run_netsh(context, *cmd_parts, timeout=20)
        return jsonify({'ok': rc == 0, 'context': context, 'command': command, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'netsh command timed out'}), 504)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

_nmap_SAFE_SCAN_TYPES = {'ping': '-sn', 'tcp_syn': '-sS', 'tcp_connect': '-sT', 'version': '-sV', 'os': '-O', 'aggressive': '-A'}

_nmap_SPEED_TEMPLATES = {'paranoid': '-T0', 'sneaky': '-T1', 'polite': '-T2', 'normal': '-T3', 'aggressive': '-T4', 'insane': '-T5'}

def _nmap__run_nmap(args, timeout=120):
    """Run nmap with args and return (stdout, stderr, exit_code)."""
    exe = _find_tool('nmap')
    if not exe:
        raise RuntimeError('nmap not found')
    nargs = [exe] + args
    result = subprocess.run(nargs, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _nmap__validate_target(target):
    """Validate a scan target (hostname, IP, CIDR, range) to prevent injection."""
    if not target or not isinstance(target, str):
        raise ValueError('target must be a non-empty string')
    if len(target) > 256:
        raise ValueError('target too long (max 256 chars)')
    allowed = re.compile('^[a-zA-Z0-9.\\-:/_\\[\\]*,]+$')
    if not allowed.match(target):
        raise ValueError(f'target contains disallowed characters: {target!r}')
    if re.search('[;&|`$(){}!<>~]', target):
        raise ValueError('target contains shell metacharacters')
    return target

def _nmap__parse_nmap_grepable(stdout):
    """Parse nmap grepable (-oG) output into structured data."""
    hosts = []
    current_host = {}
    port_lines = []
    for line in stdout.split('\n'):
        line = line.strip()
        if line.startswith('#'):
            continue
        if line.startswith('Host:'):
            if current_host and current_host.get('host'):
                current_host['ports'] = port_lines
                hosts.append(current_host)
                port_lines = []
            current_host = {'host': '', 'status': '', 'os': ''}
            parts = line.split('Status:')
            host_part = parts[0].replace('Host:', '').strip() if parts else ''
            ip_match = re.search('([0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+)', host_part)
            if ip_match:
                current_host['host'] = ip_match.group(1)
            hname_match = re.search('\\(([^)]+)\\)', host_part) if parts else None
            if hname_match:
                current_host['hostname'] = hname_match.group(1)
            current_host['status'] = parts[1].strip() if len(parts) > 1 else ''
            ports_match = re.search('Ports:\\s+(.+)', line)
            if ports_match:
                port_lines = [p.strip() for p in ports_match.group(1).split(',') if p.strip()]
            os_match = re.search('OS:\\s+(.+?)(?:\\s+//|$)', line)
            if os_match:
                current_host['os'] = os_match.group(1).strip()
        elif current_host and 'Ports:' in line:
            ports_match = re.search('Ports:\\s+(.+)', line)
            if ports_match:
                port_lines = [p.strip() for p in ports_match.group(1).split(',') if p.strip()]
        elif current_host:
            pass
    if current_host and current_host.get('host'):
        current_host['ports'] = port_lines
        hosts.append(current_host)
    return hosts

def _h_nmap_140():
    """Run a basic nmap scan against a target."""
    body = _json_body()
    if body is None:
        return (jsonify({'ok': False, 'error': 'request body must be JSON'}), 400)
    target = body.get('target', '')
    scan_type = body.get('scan_type', 'ping')
    speed = body.get('speed', 'normal')
    ports = body.get('ports', '')
    extra_args = body.get('extra_args', '')
    if not target:
        return _missing_field('target')
    try:
        target = _nmap__validate_target(target)
        args = []
        if scan_type in _nmap_SAFE_SCAN_TYPES:
            args.append(_nmap_SAFE_SCAN_TYPES[scan_type])
        else:
            return (jsonify({'ok': False, 'error': f"unsupported scan_type '{scan_type}'. Valid: {', '.join(_nmap_SAFE_SCAN_TYPES.keys())}"}), 400)
        if speed in _nmap_SPEED_TEMPLATES:
            args.append(_nmap_SPEED_TEMPLATES[speed])
        else:
            return (jsonify({'ok': False, 'error': f"unsupported speed '{speed}'. Valid: {', '.join(_nmap_SPEED_TEMPLATES.keys())}"}), 400)
        if ports:
            port_re = re.compile('^[0-9,\\-]+$')
            if not port_re.match(ports):
                return (jsonify({'ok': False, 'error': 'ports must be comma/dash separated numbers'}), 400)
            args.append('-p')
            args.append(ports)
        if extra_args:
            safe_extra_re = re.compile('^-[a-zA-Z0-9]+(?:\\s+-[a-zA-Z0-9]+)*$')
            if not safe_extra_re.match(extra_args.strip()):
                return (jsonify({'ok': False, 'error': 'extra_args must be simple dash-prefixed flags'}), 400)
            args.extend(extra_args.strip().split())
        args.append('-oG')
        args.append('-')
        args.append(target)
        _log(f'nmap: Scanning {target} ({scan_type}, {speed})')
        stdout, stderr, code = _nmap__run_nmap(args, timeout=120)
        hosts = _nmap__parse_nmap_grepable(stdout) if stdout else []
        summary = {'target': target, 'scan_type': scan_type, 'speed': speed, 'ports': ports or 'default', 'hosts_found': len(hosts), 'hosts': hosts, 'raw_stdout': stdout.strip()[:5000] if stdout else '', 'stderr': stderr.strip()[:2000] if stderr else '', 'exit_code': code}
        if code != 0:
            summary['warning'] = f'nmap exited with code {code}'
        return jsonify(summary)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'scan timed out (120s max)'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)

def _h_nmap_141():
    """Quick ping scan to discover live hosts on a subnet."""
    body = _json_body()
    if body is None:
        return (jsonify({'ok': False, 'error': 'request body must be JSON'}), 400)
    target = body.get('target', '')
    if not target:
        return _missing_field('target')
    try:
        target = _nmap__validate_target(target)
        args = ['-sn', '-T4', '-oG', '-', target]
        _log(f'nmap: Quick ping scan: {target}')
        stdout, stderr, code = _nmap__run_nmap(args, timeout=60)
        hosts = _nmap__parse_nmap_grepable(stdout) if stdout else []
        up_hosts = [h for h in hosts if 'Up' in h.get('status', '')]
        return jsonify({'ok': True, 'target': target, 'hosts_up': len(up_hosts), 'total_hosts': len(hosts), 'hosts': up_hosts, 'exit_code': code, 'stderr': stderr.strip()[:1000] if stderr else ''})
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'quick scan timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)

def _h_nmap_142():
    """Version detection scan — identifies service versions on open ports."""
    body = _json_body()
    if body is None:
        return (jsonify({'ok': False, 'error': 'request body must be JSON'}), 400)
    target = body.get('target', '')
    ports = body.get('ports', '')
    if not target:
        return _missing_field('target')
    try:
        target = _nmap__validate_target(target)
        args = ['-sV', '-T4', '--version-intensity', '5', '-oG', '-']
        if ports:
            port_re = re.compile('^[0-9,\\-]+$')
            if not port_re.match(ports):
                return (jsonify({'ok': False, 'error': 'ports must be comma/dash separated numbers'}), 400)
            args.extend(['-p', ports])
        args.append(target)
        _log(f'nmap: Version scan: {target}')
        stdout, stderr, code = _nmap__run_nmap(args, timeout=180)
        hosts = _nmap__parse_nmap_grepable(stdout) if stdout else []
        return jsonify({'ok': True, 'target': target, 'hosts_found': len(hosts), 'hosts': hosts, 'exit_code': code, 'raw_stdout': stdout.strip()[:8000] if stdout else '', 'stderr': stderr.strip()[:2000] if stderr else ''})
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'version scan timed out (180s max)'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)

_ollama__DEFAULT_BASE = 'http://127.0.0.1:11434'

_ollama__PULL_LOCK = threading.Lock()

def _ollama__server_base():
    """Return the base URL of a reachable ollama server, or None."""
    base = os.environ.get('OLLAMA_HOST', '').strip()
    if not base:
        base = _ollama__DEFAULT_BASE
    if not base.startswith(('http://', 'https://')):
        base = 'http://' + base
    return base.rstrip('/')

def _ollama__http(method, path, payload=None, timeout=120):
    """Small urllib helper returning (status, parsed_json_or_none, raw_text)."""
    url = _ollama__server_base() + path
    data = None
    headers = {'Content-Type': 'application/json'}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            try:
                return (resp.status, json.loads(raw), raw)
            except json.JSONDecodeError:
                return (resp.status, None, raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            return (e.code, json.loads(raw), raw)
        except json.JSONDecodeError:
            return (e.code, None, raw)
    except urllib.error.URLError as e:
        return (0, None, str(e.reason))
    except OSError as e:
        # socket.timeout / connection reset raised during resp.read() on slow responses
        return (0, None, str(e))

def _h_ollama_143():
    status, j, _ = _ollama__http('GET', '/api/tags', timeout=10)
    if status == 200 and isinstance(j, dict):
        models = j.get('models') or []
        return jsonify({'count': len(models), 'models': [{'name': m.get('name'), 'model': m.get('model'), 'size': m.get('size'), 'modified_at': m.get('modified_at'), 'quantization_level': m.get('details', {}).get('quantization_level') if isinstance(m.get('details'), dict) else None} for m in models]})
    return (jsonify({'error': 'ollama server unreachable', 'hint': "Install with: winget install Ollama.Ollama, then run 'ollama serve'", 'detail': j if j is not None else 'connection failed'}), 503)

def _h_ollama_144():
    status, j, _ = _ollama__http('GET', '/api/ps', timeout=10)
    if status == 200 and isinstance(j, dict):
        models = j.get('models') or []
        return jsonify({'running': len(models), 'models': models})
    return (jsonify({'error': 'ollama server unreachable', 'running': 0}), 503)

def _h_ollama_145():
    name = request.args.get('model') or request.args.get('name')
    if not name:
        return (jsonify({'error': "missing query param 'model'"}), 400)
    status, j, _ = _ollama__http('POST', '/api/show', {'name': name}, timeout=15)
    if status == 200 and isinstance(j, dict):
        return jsonify({'model': name, 'details': j.get('details'), 'parameters': j.get('parameters'), 'template': j.get('template'), 'system': j.get('system'), 'license': j.get('license'), 'modelfile': j.get('modelfile')})
    return (jsonify({'error': f'could not show model {name!r}', 'detail': j}), 404)

def _h_ollama_146():
    body = _json_body()
    name = body.get('model') or body.get('name')
    if not name:
        return _missing_field('model')
    name = str(name).strip()
    if not name or any((c in name for c in ('\n', '\r', ' '))):
        return (jsonify({'error': 'invalid model name'}), 400)
    _insecure = body.get('insecure', False)
    insecure = _insecure is True or str(_insecure).strip().lower() in ('true', '1', 'yes', 'on')
    if not _ollama__PULL_LOCK.acquire(blocking=False):
        return (jsonify({'error': 'a pull is already in progress', 'success': False}), 409)
    try:
        _log(f'ollama_pull: {name}')
        payload = {'name': name, 'stream': False}
        if insecure:
            payload['insecure'] = True
        status, j, raw = _ollama__http('POST', '/api/pull', payload, timeout=1800)
        ok = status == 200 and (isinstance(j, dict) and j.get('status') == 'success')
        return (jsonify({'success': ok, 'model': name, 'http_status': status, 'result': j if j is not None else raw}), 200 if ok else 502)
    except Exception as e:
        _log(f'ollama_pull: Error: {e}')
        return (jsonify({'error': str(e), 'success': False}), 500)
    finally:
        _ollama__PULL_LOCK.release()

def _h_ollama_147():
    body = _json_body()
    model = body.get('model')
    prompt = body.get('prompt')
    if not model:
        return _missing_field('model')
    if prompt is None:
        return _missing_field('prompt')
    payload = {'model': str(model), 'prompt': str(prompt), 'stream': False}
    if body.get('options') and isinstance(body['options'], dict):
        payload['options'] = body['options']
    if body.get('system'):
        payload['system'] = str(body['system'])
    if body.get('template'):
        payload['template'] = str(body['template'])
    if body.get('raw') is not None:
        raw = body['raw']
        if isinstance(raw, bool):
            payload['raw'] = raw
        else:
            payload['raw'] = str(raw).strip().lower() in ('true', '1', 'yes', 'on')
    if body.get('keep_alive') is not None:
        payload['keep_alive'] = body['keep_alive']
    status, j, _ = _ollama__http('POST', '/api/generate', payload, timeout=600)
    if status == 200 and isinstance(j, dict):
        return jsonify({'model': model, 'response': j.get('response'), 'done': j.get('done'), 'context_length': j.get('prompt_eval_count'), 'generated_tokens': j.get('eval_count'), 'total_duration_ns': j.get('total_duration')})
    return (jsonify({'error': f'generate failed (status {status})', 'detail': j}), 502)

def _h_ollama_148():
    body = _json_body()
    model = body.get('model')
    messages = body.get('messages')
    if not model:
        return _missing_field('model')
    if not isinstance(messages, list) or not messages:
        return _missing_field('messages')
    payload = {'model': str(model), 'messages': messages, 'stream': False}
    if body.get('options') and isinstance(body['options'], dict):
        payload['options'] = body['options']
    if body.get('keep_alive') is not None:
        payload['keep_alive'] = body['keep_alive']
    status, j, _ = _ollama__http('POST', '/api/chat', payload, timeout=600)
    if status == 200 and isinstance(j, dict):
        msg = j.get('message') or {}
        return jsonify({'model': model, 'message': msg, 'done': j.get('done'), 'prompt_eval_count': j.get('prompt_eval_count'), 'eval_count': j.get('eval_count')})
    return (jsonify({'error': f'chat failed (status {status})', 'detail': j}), 502)

def _h_ollama_149():
    body = _json_body()
    model = body.get('model')
    prompt = body.get('prompt')
    if not model:
        return _missing_field('model')
    if prompt is None:
        return _missing_field('prompt')
    payload = {'model': str(model), 'prompt': str(prompt)}
    if body.get('options') and isinstance(body['options'], dict):
        payload['options'] = body['options']
    status, j, _ = _ollama__http('POST', '/api/embeddings', payload, timeout=300)
    if status == 200 and isinstance(j, dict):
        emb = j.get('embedding')
        return jsonify({'model': model, 'dimensions': len(emb) if isinstance(emb, list) else None, 'embedding': emb})
    return (jsonify({'error': f'embeddings failed (status {status})', 'detail': j}), 502)

_pe_sieve__DMODE_WHITELIST = {'A', 'D', 'V', 'U', 'R', 'N'}

def _pe_sieve__as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return default

def _pe_sieve__find_pesieve():
    """Locate pe-sieve.exe on this system."""
    for name in ('pe-sieve.exe', 'pe-sieve'):
        exe = shutil.which(name)
        if exe:
            return exe
    candidates = ['C:\\tools\\pe-sieve\\pe-sieve.exe', 'C:\\pe-sieve\\pe-sieve.exe', os.path.expandvars('%USERPROFILE%\\Downloads\\pe-sieve\\pe-sieve.exe'), os.path.expandvars('%USERPROFILE%\\Downloads\\pe-sieve64\\pe-sieve.exe'), os.path.expandvars('%USERPROFILE%\\Desktop\\pe-sieve\\pe-sieve.exe'), os.path.expandvars('%LOCALAPPDATA%\\pe-sieve\\pe-sieve.exe')]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

def _h_pe_sieve_150():
    """Scan a live process for implants/injections.
        Body: {"pid": 1234, "json": true, "dmode": "A", "quiet": false, "minidump": false, "dir": "C:\\out"}
        """
    body = _json_body()
    if not isinstance(body, dict):
        return _missing_field('pid')
    pid = body.get('pid')
    if pid is None:
        return _missing_field('pid')
    try:
        pid = int(pid)
    except (ValueError, TypeError):
        return (jsonify({'error': f'Invalid PID: {pid}'}), 400)
    if pid <= 0:
        return (jsonify({'error': 'PID must be a positive integer'}), 400)
    json_out = _pe_sieve__as_bool(body.get('json'), True)
    quiet = _pe_sieve__as_bool(body.get('quiet'), False)
    minidump = _pe_sieve__as_bool(body.get('minidump'), False)
    dmode = str(body.get('dmode') or 'A').strip().upper()
    out_dir = body.get('dir', '')
    if out_dir is not None:
        out_dir = str(out_dir)
        if any((ord(c) < 32 for c in out_dir)):
            return (jsonify({'error': 'dir cannot contain control characters'}), 400)
        if out_dir.startswith('-') or out_dir.startswith('/'):
            return (jsonify({'error': 'dir must be a directory path, not a CLI flag'}), 400)
    if dmode and dmode not in _pe_sieve__DMODE_WHITELIST:
        return (jsonify({'error': f"Invalid dmode '{dmode}'. Allowed: {', '.join(sorted(_pe_sieve__DMODE_WHITELIST))}"}), 400)
    exe = _pe_sieve__find_pesieve()
    if not exe:
        return (jsonify({'error': 'pe-sieve not installed', 'hint': 'Download from https://github.com/hasherezade/pe-sieve/releases and place pe-sieve.exe on PATH'}), 503)
    try:
        cmd = [exe, '/pid', str(pid)]
        if json_out:
            cmd.append('/json')
        if dmode:
            cmd.extend(['/dmode', dmode])
        if quiet:
            cmd.append('/quiet')
        if minidump:
            cmd.append('/minidmp')
        if out_dir:
            cmd.extend(['/dir', str(out_dir)])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        output = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
        return jsonify({'pid': pid, 'exit_code': r.returncode, 'dmode': dmode, 'json_requested': json_out, 'minidump': minidump, 'report': output.strip() or '(no output)'})
    except subprocess.TimeoutExpired:
        _log(f"[pe_sieve_scan] {f'scan of PID {pid} timed out'}")
        return (jsonify({'error': 'pe-sieve scan timed out after 90s', 'pid': pid}), 504)
    except Exception as e:
        _log(f"[pe_sieve_scan] {f'Error scanning PID {pid}: {e}'}")
        return (jsonify({'error': str(e), 'pid': pid}), 500)

def _photoshop_mcp__clean_script(value):
    script = str(value or '').strip()
    if not script:
        raise ValueError('script must be a non-empty string')
    if '\x00' in script:
        raise ValueError('script cannot contain null bytes')
    if len(script) > 50000:
        raise ValueError('script exceeds maximum length (50000 chars)')
    return script

def _photoshop_mcp__run_photoshop_mcp(cmd, payload, timeout):
    """Run the MCP process; .cmd/.bat launchers must go through the shell on Windows."""
    if cmd[0].lower().endswith(('.cmd', '.bat')):
        return subprocess.run(subprocess.list2cmdline(cmd), input=payload, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, shell=True)
    return subprocess.run(cmd, input=payload, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, shell=False)

def _photoshop_mcp__clean_string(value, field):
    s = str(value or '').strip()
    if not s:
        raise ValueError(f'{field} must be a non-empty string')
    if '\x00' in s:
        raise ValueError(f'{field} cannot contain null bytes')
    return s

def _h_photoshop_mcp_151():
    """Execute a Photoshop action via the MCP server.
        
        Body: {
            "action": "createDocument",
            "params": {"width": 1920, "height": 1080, "resolution": 72, "fill": "white"}
        }
        """
    data = _json_body()
    if 'action' not in data:
        return _missing_field('action')
    cmd = _find_tool('photoshop_mcp')
    if not cmd:
        return (jsonify({'ok': False, 'error': 'Photoshop MCP server not found', 'hint': 'Install with `npm install -g @photoshops/mcp-server`'}), 503)
    try:
        action = _photoshop_mcp__clean_string(data.get('action'), 'action')
        params = data.get('params', {})
        timeout = max(1, min(int(data.get('timeout', 120)), 600))
    except (ValueError, TypeError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    if not isinstance(params, dict):
        return (jsonify({'ok': False, 'error': "'params' must be a JSON object"}), 400)
    import json as _json
    try:
        result = _photoshop_mcp__run_photoshop_mcp(cmd, _json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': action, 'arguments': params}, 'id': 1}), timeout)
    except subprocess.TimeoutExpired as exc:
        _log(f'[photoshop_mcp] Action timed out after {timeout}s action={action}')
        return (jsonify({'ok': False, 'error': f'Photoshop action timed out after {timeout}s', 'stdout': exc.stdout or '', 'stderr': exc.stderr or ''}), 504)
    except OSError as exc:
        _log(f'[photoshop_mcp] Launch failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[photoshop_mcp] exit={result.returncode} action={action}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'action': action, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

def _h_photoshop_mcp_152():
    """Run a raw ExtendScript in Photoshop via the MCP server.
        
        Body: {
            "script": "app.activeDocument.resizeImage(800, 600, 72, ResampleMethod.BICUBIC);"
        }
        """
    data = _json_body()
    if 'script' not in data:
        return _missing_field('script')
    cmd = _find_tool('photoshop_mcp')
    if not cmd:
        return (jsonify({'ok': False, 'error': 'Photoshop MCP server not found', 'hint': 'Install with `npm install -g @photoshops/mcp-server`'}), 503)
    try:
        script = _photoshop_mcp__clean_script(data.get('script'))
        timeout = max(1, min(int(data.get('timeout', 120)), 600))
    except (ValueError, TypeError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    import json as _json
    try:
        result = _photoshop_mcp__run_photoshop_mcp(cmd, _json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': 'runScript', 'arguments': {'script': script}}, 'id': 1}), timeout)
    except subprocess.TimeoutExpired as exc:
        _log(f'[photoshop_mcp] runScript timed out after {timeout}s')
        return (jsonify({'ok': False, 'error': f'Photoshop script timed out after {timeout}s', 'stdout': exc.stdout or '', 'stderr': exc.stderr or ''}), 504)
    except OSError as exc:
        _log(f'[photoshop_mcp] Launch failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[photoshop_mcp] runScript exit={result.returncode}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

_powercfg_AC_VALUE_PATTERN = re.compile('Current AC Power Setting Index:\\s+(0x[0-9a-fA-F]+)')

_powercfg_POWER_PATTERN = re.compile('Power Scheme GUID:\\s+(\\S+)\\s+\\(([^)]+)\\)')

_powercfg_DC_VALUE_PATTERN = re.compile('Current DC Power Setting Index:\\s+(0x[0-9a-fA-F]+)')

_powercfg_SUBGROUP_PATTERN = re.compile('Subgroup GUID:\\s+(\\S+)\\s+\\(([^)]*)\\)')

_powercfg_SETTING_PATTERN = re.compile('Power Setting GUID:\\s+(\\S+)\\s+\\(([^)]*)\\)')

def _powercfg__run_powercfg(args, timeout=15):
    """Run powercfg with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('powercfg')
    if not exe:
        raise RuntimeError('powercfg not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, errors='replace')
    return (result.stdout, result.stderr, result.returncode)

def _powercfg__parse_query(text):
    """Parse powercfg /QUERY output into structured settings tree."""
    sections = []
    current_subgroup = None
    current_setting = None
    for line in text.splitlines():
        m = _powercfg_SUBGROUP_PATTERN.search(line)
        if m:
            current_subgroup = {'guid': m.group(1), 'name': m.group(2).strip() if m.group(2) else '', 'settings': []}
            sections.append(current_subgroup)
            current_setting = None
            continue
        m = _powercfg_SETTING_PATTERN.search(line)
        if m:
            current_setting = {'guid': m.group(1), 'name': m.group(2).strip() if m.group(2) else '', 'ac_value': None, 'dc_value': None}
            if current_subgroup:
                current_subgroup['settings'].append(current_setting)
            continue
        if current_setting:
            mac = _powercfg_AC_VALUE_PATTERN.search(line)
            if mac:
                current_setting['ac_value'] = mac.group(1)
            mdc = _powercfg_DC_VALUE_PATTERN.search(line)
            if mdc:
                current_setting['dc_value'] = mdc.group(1)
    return sections

def _powercfg__parse_schemes(text):
    """Parse powercfg /LIST output into structured scheme list."""
    schemes = []
    for line in text.splitlines():
        m = _powercfg_POWER_PATTERN.search(line)
        if m:
            guid, name = (m.group(1), m.group(2).strip())
            active = line.strip().endswith('*') or ' *' in line
            schemes.append({'guid': guid, 'name': name, 'active': active})
    return schemes

def _h_powercfg_153():
    """List all power schemes with active indicator."""
    try:
        stdout, stderr, rc = _powercfg__run_powercfg(['/LIST'])
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'powercfg /LIST failed'}), 502)
        schemes = _powercfg__parse_schemes(stdout)
        active = next((s for s in schemes if s['active']), None)
        return jsonify({'ok': True, 'schemes': schemes, 'active_scheme': active, 'count': len(schemes)})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'powercfg list timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_powercfg_154():
    """Query current active power scheme settings in detail."""
    try:
        stdout, stderr, rc = _powercfg__run_powercfg(['/QUERY'])
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'powercfg /QUERY failed'}), 502)
        sections = _powercfg__parse_query(stdout)
        return jsonify({'ok': True, 'sections': sections, 'count': len(sections)})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'powercfg query timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_powercfg_155():
    """Set the active power scheme by GUID."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    if not isinstance(body, dict):
        return (jsonify({'ok': False, 'error': 'JSON body must be an object'}), 400)
    guid = body.get('guid', '')
    if not isinstance(guid, str):
        return (jsonify({'ok': False, 'error': 'guid must be a string'}), 400)
    guid = guid.strip()
    if not guid:
        return _missing_field('guid')
    guid_pattern = '^\\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\\}?$'
    if not re.match(guid_pattern, guid):
        return (jsonify({'ok': False, 'error': 'invalid GUID format'}), 400)
    try:
        stdout, stderr, rc = _powercfg__run_powercfg(['/S', guid])
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'powercfg /S failed'}), 502)
        return jsonify({'ok': True, 'guid': guid, 'stdout': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'powercfg set_active timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_powercfg_156():
    """Generate energy efficiency report (runs for 60s)."""
    try:
        stdout, stderr, rc = _powercfg__run_powercfg(['/ENERGY'], timeout=75)
        return jsonify({'ok': rc == 0, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip(), 'note': 'Full report saved to energy-report.html in working directory'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'powercfg energy report timed out (takes ~60s to sample)'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_powercfg_157():
    """Generate battery life report (laptops only)."""
    try:
        stdout, stderr, rc = _powercfg__run_powercfg(['/BATTERYREPORT'], timeout=30)
        return jsonify({'ok': rc == 0, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip(), 'note': 'Full report saved to battery-report.html in working directory'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'powercfg battery report timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_powercfg_158():
    """Enable or disable hibernation."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    enable = body.get('enable', None)
    if enable is None:
        return _missing_field('enable')
    if isinstance(enable, bool):
        enable_flag = enable
    else:
        enable_flag = str(enable).strip().lower() in ('on', 'true', 'yes', '1', 'enable')
    try:
        args = ['/H', 'ON' if enable_flag else 'OFF']
        stdout, stderr, rc = _powercfg__run_powercfg(args, timeout=15)
        return jsonify({'ok': rc == 0, 'enable': enable_flag, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'powercfg hibernate command timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _procs__parse_procs_json(raw_json):
    """Parse procs JSON output into a list of process dicts with selected fields."""
    try:
        processes = json.loads(raw_json)
        if not isinstance(processes, list):
            _log(f'procs_parse: unexpected JSON shape: {type(processes).__name__}')
            return []
        result = []
        for p in processes:
            if not isinstance(p, dict):
                continue
            entry = {'pid': p.get('pid'), 'ppid': p.get('ppid'), 'name': p.get('name'), 'exe': p.get('exe'), 'cpu_usage': p.get('cpu_usage'), 'mem_usage': p.get('mem_usage'), 'vms': p.get('vms'), 'rss': p.get('rss'), 'status': p.get('status'), 'user': p.get('user'), 'read_bytes': p.get('read_bytes'), 'write_bytes': p.get('write_bytes'), 'start_time': p.get('start_time'), 'tcp_sockets': p.get('tcp_sockets'), 'udp_sockets': p.get('udp_sockets')}
            entry = {k: v for k, v in entry.items() if v is not None}
            result.append(entry)
        return result
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        _log(f'procs_parse: JSON parse error: {e}')
        return []

def _h_procs_159():
    """List processes as JSON. Optional query params: name, pid, user, limit."""
    exe = _find_tool('procs')
    if not exe:
        return (jsonify({'error': 'procs not installed. Install: winget install procs', 'processes': [], 'count': 0}), 200)
    name_filter = request.args.get('name', '')
    pid_filter = request.args.get('pid', '')
    user_filter = request.args.get('user', '')
    sort = request.args.get('sort', 'cpu')
    limit = request.args.get('limit', '')
    try:
        cmd = [exe, '--json']
        if name_filter:
            cmd.extend(['--only-name', name_filter])
        if sort in ('cpu', 'mem'):
            cmd.extend(['--sorta', sort])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            _log(f'procs_list: procs exited {r.returncode}: {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip(), 'processes': [], 'count': 0}), 500)
        processes = _procs__parse_procs_json(r.stdout)
        if pid_filter:
            try:
                target_pid = int(pid_filter)
                processes = [p for p in processes if p.get('pid') == target_pid]
            except ValueError:
                pass
        if user_filter:
            processes = [p for p in processes if user_filter.lower() in str(p.get('user') or '').lower()]
        total = len(processes)
        if limit:
            try:
                lim_int = int(limit)
            except ValueError:
                return (jsonify({'error': f'Invalid limit: {limit}', 'processes': [], 'count': 0}), 400)
            if lim_int <= 0:
                return (jsonify({'error': 'limit must be positive', 'processes': [], 'count': 0}), 400)
            processes = processes[:lim_int]
        return jsonify({'processes': processes, 'count': len(processes), 'total_matched': total, 'filters': {'name': name_filter or None, 'pid': pid_filter or None, 'user': user_filter or None}})
    except subprocess.TimeoutExpired:
        _log('procs_list: procs --json timed out')
        return (jsonify({'error': 'procs timed out', 'processes': [], 'count': 0}), 504)
    except Exception as e:
        _log(f'procs_list: Error: {e}')
        return (jsonify({'error': str(e), 'processes': [], 'count': 0}), 500)

def _h_procs_160():
    """Show processes in tree view with parent-child relationships."""
    exe = _find_tool('procs')
    if not exe:
        return (jsonify({'error': 'procs not installed. Install: winget install procs', 'processes': [], 'count': 0}), 200)
    name_filter = request.args.get('name', '')
    try:
        cmd = [exe, '--tree', '--json']
        if name_filter:
            cmd.extend(['--only-name', name_filter])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            _log(f'procs_tree: procs --tree exited {r.returncode}: {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip(), 'processes': [], 'count': 0}), 500)
        processes = _procs__parse_procs_json(r.stdout)
        by_pid = {p.get('pid'): p for p in processes if p.get('pid')}
        roots = []
        for p in processes:
            ppid = p.get('ppid')
            if ppid and ppid in by_pid:
                parent = by_pid[ppid]
                parent.setdefault('children', []).append(p)
            else:
                roots.append(p)
        return jsonify({'processes': roots, 'count': len(roots), 'total': len(processes)})
    except subprocess.TimeoutExpired:
        _log('procs_tree: procs --tree timed out')
        return (jsonify({'error': 'procs timed out', 'processes': [], 'count': 0}), 504)
    except Exception as e:
        _log(f'procs_tree: Error: {e}')
        return (jsonify({'error': str(e), 'processes': [], 'count': 0}), 500)

def _h_procs_161():
    """Find a specific process by name or PID. Returns detailed info."""
    exe = _find_tool('procs')
    if not exe:
        return (jsonify({'error': 'procs not installed. Install: winget install procs', 'found': False}), 200)
    name = request.args.get('name', '')
    pid_str = request.args.get('pid', '')
    if not name and (not pid_str):
        return (jsonify({'error': 'Provide ?name=<process> or ?pid=<number>'}), 400)
    try:
        cmd = [exe, '--json']
        if name:
            cmd.extend(['--only-name', name])
            cmd.append('--or')
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return (jsonify({'error': r.stderr.strip(), 'found': False}), 500)
        processes = _procs__parse_procs_json(r.stdout)
        if pid_str:
            try:
                target_pid = int(pid_str)
                processes = [p for p in processes if p.get('pid') == target_pid]
            except ValueError:
                return (jsonify({'error': f'Invalid PID: {pid_str}', 'found': False}), 400)
        if not processes:
            return jsonify({'found': False, 'query': {'name': name or None, 'pid': pid_str or None}, 'message': 'No matching process found'})
        return jsonify({'found': True, 'process': processes[0], 'count': len(processes)})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'procs timed out', 'found': False}), 504)
    except Exception as e:
        _log(f'procs_find: Error: {e}')
        return (jsonify({'error': str(e), 'found': False}), 500)

def _h_procs_162():
    """Kill a process by PID. Optionally force-kill with ?force=1."""
    body = _json_body()
    if body is None:
        body = {}
    pid = body.get('pid') or request.args.get('pid')
    if not pid:
        return (jsonify({'error': "Provide 'pid' in JSON body or ?pid=<number>"}), 400)
    try:
        pid_int = int(pid)
    except (ValueError, TypeError):
        return (jsonify({'error': f'Invalid PID: {pid}'}), 400)
    if pid_int <= 4 or pid_int in (os.getpid(), os.getppid()):
        return (jsonify({'error': f'Refusing to kill protected PID {pid_int}', 'pid': pid_int, 'success': False}), 400)
    force = body.get('force', False) or request.args.get('force') in ('1', 'true', 'yes')
    try:
        if force:
            r = subprocess.run(['taskkill', '/f', '/pid', str(pid_int)], capture_output=True, text=True, timeout=10)
        else:
            r = subprocess.run(['taskkill', '/pid', str(pid_int)], capture_output=True, text=True, timeout=10)
        success = r.returncode == 0
        return jsonify({'success': success, 'pid': pid_int, 'force': force, 'detail': r.stdout.strip() or r.stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'taskkill timed out', 'pid': pid_int, 'success': False}), 504)
    except Exception as e:
        _log(f'procs_kill: Error killing PID {pid_int}: {e}')
        return (jsonify({'error': str(e), 'pid': pid_int, 'success': False}), 500)

def _rapidocr__clean_bool(value):
    if isinstance(value, bool):
        return value
    if value in (None, ''):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)

def _rapidocr__clean_image(value):
    image = str(value or '').strip()
    if not image:
        raise ValueError('image must not be empty')
    if '\x00' in image:
        raise ValueError('image cannot contain null bytes')
    return image

def _h_rapidocr_163():
    data = _json_body()
    missing = _missing_field(data, 'image')
    if missing:
        return missing
    exe = _find_tool('rapidocr')
    if not exe:
        return (jsonify({'ok': False, 'error': 'rapidocr command not found on PATH', 'hint': 'Install RapidOCR with `pip install rapidocr onnxruntime`.'}), 503)
    try:
        image = _rapidocr__clean_image(data.get('image'))
        visualize = _rapidocr__clean_bool(data.get('visualize'))
        timeout = max(1, min(int(data.get('timeout', 60)), 300))
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    command = [exe, '-img', image]
    if visualize:
        command.append('--vis_res')
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as exc:
        _log(f'[rapidocr] OCR timed out after {timeout}s image={image}')
        return (jsonify({'ok': False, 'error': f'rapidocr OCR timed out after {timeout}s', 'stdout': exc.stdout or '', 'stderr': exc.stderr or ''}), 504)
    except OSError as exc:
        _log(f'[rapidocr] launch failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[rapidocr] OCR exit={result.returncode} image={image}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'image': image, 'visualize': visualize, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

_reg_HIVE_MAP = {'HKCR': 'HKEY_CLASSES_ROOT', 'HKCU': 'HKEY_CURRENT_USER', 'HKLM': 'HKEY_LOCAL_MACHINE', 'HKU': 'HKEY_USERS', 'HKCC': 'HKEY_CURRENT_CONFIG'}

def _reg__parse_query_output(text):
    """Parse 'reg query' output into structured key/value data."""
    entries = {}
    current_key = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if any((line.startswith(h) for h in ['HKEY_', 'HKCR', 'HKCU', 'HKLM', 'HKU', 'HKCC'])):
            current_key = line.strip()
            entries[current_key] = []
            i += 1
            continue
        if not line.strip() or line.strip().startswith('---') or line.strip().startswith('End'):
            i += 1
            continue
        if current_key and line.strip():
            stripped = line.strip()
            parts = stripped.split(None, 2)
            if len(parts) >= 2 and parts[1].startswith('REG_'):
                name = parts[0]
                val_type = parts[1]
                data = parts[2] if len(parts) > 2 else ''
                entries[current_key].append({'name': name if name != '(Default)' else '(Default)', 'type': val_type, 'data': data})
            else:
                pass
        i += 1
    return entries

def _reg__run_reg(args, timeout=15):
    """Run reg.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('reg')
    if not exe:
        raise RuntimeError('reg.exe not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _reg__validate_hive_path(key_path):
    """Basic validation of a registry key path. Returns True if it looks valid."""
    if not key_path or not isinstance(key_path, str):
        return False
    key_path = key_path.strip()
    hive = key_path.split('\\')[0]
    if hive not in _reg_HIVE_MAP:
        return key_path.startswith('HKEY_')
    return True

def _reg__parse_comparison(text):
    """Parse reg compare output into structured diff-like result."""
    results = []
    current_section = None
    for line in text.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if 'differs' in stripped:
            results.append({'type': 'difference', 'line': stripped})
        elif stripped.startswith('Result Compared:'):
            results.append({'type': 'header', 'line': stripped})
        elif stripped.startswith('Current User'):
            current_section = 'user'
            results.append({'type': 'section', 'section': stripped})
        elif stripped.startswith('Local Machine'):
            current_section = 'machine'
            results.append({'type': 'section', 'section': stripped})
        else:
            results.append({'type': 'line', 'line': stripped})
    return results

def _h_reg_164():
    """Query a registry key: list its subkeys and values."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    key = str(body.get('key') or '').strip()
    if not key:
        return _missing_field('key')
    if not _reg__validate_hive_path(key):
        return (jsonify({'ok': False, 'error': 'invalid registry path'}), 400)
    value_name = str(body.get('value', '')).strip()
    recursive = body.get('recursive', False)
    try:
        args = ['query', key]
        if value_name:
            args.extend(['/v', value_name])
        if recursive:
            args.append('/s')
        stdout, stderr, rc = _reg__run_reg(args, timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'reg query failed (key may not exist)', 'exit_code': rc}), 502)
        parsed = _reg__parse_query_output(stdout)
        return jsonify({'ok': True, 'key': key, 'entries': parsed, 'value_name': value_name or None, 'recursive': recursive})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'reg query timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_reg_165():
    """Add a new registry key or value."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    key = str(body.get('key') or '').strip()
    if not key:
        return _missing_field('key')
    if not _reg__validate_hive_path(key):
        return (jsonify({'ok': False, 'error': 'invalid registry path'}), 400)
    value_name = body.get('value')
    value_data = body.get('data')
    value_type = str(body.get('type', 'REG_SZ')).strip().upper()
    force = body.get('force', False)
    if not value_type.startswith('REG_'):
        return (jsonify({'ok': False, 'error': 'invalid value type (must be REG_*)'}), 400)
    try:
        args = ['add', key]
        if value_name:
            args.extend(['/v', value_name])
        else:
            args.append('/ve')
        if value_data is not None:
            args.extend(['/d', str(value_data)])
        args.extend(['/t', value_type])
        if force:
            args.append('/f')
        stdout, stderr, rc = _reg__run_reg(args, timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'reg add failed', 'exit_code': rc}), 502)
        return jsonify({'ok': True, 'key': key, 'value': value_name or '(Default)', 'type': value_type, 'data': value_data, 'stdout': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'reg add timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_reg_166():
    """Delete a registry key or value."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    key = str(body.get('key') or '').strip()
    if not key:
        return _missing_field('key')
    if not _reg__validate_hive_path(key):
        return (jsonify({'ok': False, 'error': 'invalid registry path'}), 400)
    value_name = body.get('value')
    recursive = body.get('recursive', False)
    try:
        args = ['delete', key]
        if value_name:
            args.extend(['/v', value_name])
        args.append('/f')
        stdout, stderr, rc = _reg__run_reg(args, timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'reg delete failed', 'exit_code': rc}), 502)
        return jsonify({'ok': True, 'key': key, 'value': value_name or '(Default)', 'recursive': recursive, 'stdout': stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'reg delete timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_reg_167():
    """Export a registry key to .reg file format."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    key = str(body.get('key') or '').strip()
    if not key:
        return _missing_field('key')
    if not _reg__validate_hive_path(key):
        return (jsonify({'ok': False, 'error': 'invalid registry path'}), 400)
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix='.reg', delete=False) as tmp:
            export_path = tmp.name
        args = ['export', key, export_path, '/y']
        stdout, stderr, rc = _reg__run_reg(args, timeout=15)
        if rc != 0:
            try:
                os.unlink(export_path)
            except OSError:
                pass
            return (jsonify({'ok': False, 'error': stderr.strip() or 'reg export failed', 'exit_code': rc}), 502)
        try:
            with open(export_path, 'r', encoding='utf-16', errors='replace') as f:
                reg_content = f.read()
        except UnicodeError:
            with open(export_path, 'r', encoding='utf-8', errors='replace') as f:
                reg_content = f.read()
        try:
            os.unlink(export_path)
        except OSError:
            pass
        return jsonify({'ok': True, 'key': key, 'reg_content': reg_content})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'reg export timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_reg_168():
    """Compare two registry keys."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    key1 = str(body.get('key1') or '').strip()
    key2 = str(body.get('key2') or '').strip()
    if not key1 or not key2:
        return _missing_field('key1 and key2')
    if not _reg__validate_hive_path(key1):
        return (jsonify({'ok': False, 'error': 'invalid registry path for key1'}), 400)
    if not _reg__validate_hive_path(key2):
        return (jsonify({'ok': False, 'error': 'invalid registry path for key2'}), 400)
    try:
        args = ['compare', key1, key2]
        stdout, stderr, rc = _reg__run_reg(args, timeout=15)
        if rc == 2:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'reg compare failed', 'exit_code': rc}), 502)
        parsed = _reg__parse_comparison(stdout)
        return jsonify({'ok': True, 'key1': key1, 'key2': key2, 'identical': rc == 0, 'differences_found': rc == 1, 'details': parsed})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'reg compare timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_ripgrep_169():
    """Execute ripgrep search with pattern and optional path."""
    exe = _find_tool('ripgrep')
    if not exe:
        return (jsonify({'error': 'ripgrep not installed', 'hint': 'Install with: winget install BurntSushi.ripgrep.MSVC'}), 503)
    body = _json_body()
    pattern = body.get('pattern')
    if not pattern:
        return _missing_field('pattern')
    search_path = body.get('path', '.')
    try:
        max_lines = int(body.get('max_lines', 200))
    except (TypeError, ValueError):
        return (jsonify({'error': 'max_lines must be an integer'}), 400)
    case_sensitive = body.get('case_sensitive', False)
    file_glob = body.get('file_glob', None)
    max_depth = body.get('max_depth', None)
    if max_depth is not None:
        try:
            max_depth = int(max_depth)
        except (TypeError, ValueError):
            return (jsonify({'error': 'max_depth must be an integer'}), 400)
    cmd = [exe, '--no-heading', '--line-number', '--color', 'never', '--max-count', str(max_lines)]
    if not case_sensitive:
        cmd.append('--ignore-case')
    if file_glob:
        cmd.extend(['--glob', file_glob])
    if max_depth is not None:
        cmd.extend(['--max-depth', str(max_depth)])
    cmd.extend(['--', pattern, search_path])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
        lines = [l for l in r.stdout.strip().split('\n') if l]
        truncated = len(lines) >= max_lines
        result = {'pattern': pattern, 'path': search_path, 'matches': lines[:max_lines], 'count': len(lines[:max_lines]), 'truncated': truncated}
        if r.returncode == 1:
            result['count'] = 0
            result['matches'] = []
        elif r.returncode > 1:
            return (jsonify({'error': r.stderr.strip()}), 400)
        return jsonify(result)
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'Search timed out after 30s'}), 504)

def _h_ripgrep_170():
    """Count matches for a pattern."""
    exe = _find_tool('ripgrep')
    if not exe:
        return (jsonify({'error': 'ripgrep not installed'}), 503)
    body = _json_body()
    pattern = body.get('pattern')
    if not pattern:
        return _missing_field('pattern')
    search_path = body.get('path', '.')
    file_glob = body.get('file_glob', None)
    cmd = [exe, '--count', '--no-heading']
    if file_glob:
        cmd.extend(['--glob', file_glob])
    cmd.extend(['--', pattern, search_path])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
        results = {}
        total = 0
        for line in r.stdout.strip().split('\n'):
            if ':' in line:
                fname, count_str = line.rsplit(':', 1)
                try:
                    count = int(count_str)
                    results[fname] = count
                    total += count
                except ValueError:
                    continue
        return jsonify({'pattern': pattern, 'path': search_path, 'file_counts': results, 'total_matches': total})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'Count timed out after 30s'}), 504)

def _h_ripgrep_171():
    """List files that would be searched (rg --files)."""
    exe = _find_tool('ripgrep')
    if not exe:
        return (jsonify({'error': 'ripgrep not installed'}), 503)
    body = _json_body() if request.is_json else {}
    search_path = body.get('path', '.')
    file_glob = body.get('file_glob', None)
    try:
        max_results = int(body.get('max_results', 500))
    except (TypeError, ValueError):
        return (jsonify({'error': 'max_results must be an integer'}), 400)
    cmd = [exe, '--files']
    if file_glob:
        cmd.extend(['--glob', file_glob])
    cmd.extend(['--', search_path])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=os.getcwd())
        files = [f for f in r.stdout.strip().split('\n') if f]
        return jsonify({'path': search_path, 'files': files[:max_results], 'count': len(files[:max_results])})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'File listing timed out'}), 504)

def _rufus__list_isos(search_paths=None):
    """Find ISO files on common download locations."""
    if search_paths is None:
        search_paths = [os.path.expanduser('~\\Desktop'), os.path.expanduser('~\\Downloads'), os.path.expanduser('~\\Documents'), os.path.expanduser('~\\ISOs'), 'C:\\ISOs']
    isos = []
    for base in search_paths:
        if not os.path.isdir(base):
            continue
        try:
            for f in os.listdir(base):
                if f.lower().endswith('.iso') or f.lower().endswith('.wim'):
                    path = os.path.join(base, f)
                    size_mb = round(os.path.getsize(path) / 1024 ** 2, 1)
                    isos.append({'path': path, 'name': f, 'size_mb': size_mb, 'location': base})
        except Exception:
            pass
    return isos

def _rufus__list_usb_drives():
    """List USB drives using Python stdlib + WMIC fallback."""
    drives = []
    if hasattr(os, 'listdrives'):
        drive_letters = list(os.listdrives())
    else:
        import string
        drive_letters = [f'{l}:\\' for l in string.ascii_uppercase if os.path.exists(f'{l}:\\')]
    for d in drive_letters:
        try:
            if not os.path.exists(d):
                continue
            drive_type = 0
            try:
                kernel32 = ctypes.windll.kernel32
                kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
                kernel32.GetDriveTypeW.restype = ctypes.c_uint
                drive_type = kernel32.GetDriveTypeW(d)
            except Exception:
                pass
            type_names = {2: 'removable', 3: 'fixed', 4: 'remote', 5: 'cdrom', 6: 'ramdisk'}
            dtype_name = type_names.get(drive_type, f'unknown({drive_type})')
            usage = shutil.disk_usage(d)
            drives.append({'drive': d, 'type': dtype_name, 'is_usb': drive_type == 2, 'total_gb': round(usage.total / 1024 ** 3, 1), 'free_gb': round(usage.free / 1024 ** 3, 1), 'used_gb': round((usage.total - usage.free) / 1024 ** 3, 1)})
        except Exception:
            pass
    return drives

def _h_rufus_172():
    """List available drives with type info (removable/fixed)."""
    try:
        drives = _rufus__list_usb_drives()
        return jsonify({'ok': True, 'drives': drives})
    except Exception as e:
        return (jsonify({'ok': False, 'error': str(e)}), 500)

def _h_rufus_173():
    """List ISO/WIM files found on common search paths."""
    try:
        isos = _rufus__list_isos()
        return jsonify({'ok': True, 'count': len(isos), 'isos': sorted(isos, key=lambda x: -x['size_mb'])})
    except Exception as e:
        return (jsonify({'ok': False, 'error': str(e)}), 500)

def _h_rufus_174():
    """Create a bootable USB drive using Rufus CLI."""
    rufus_path = _find_tool('rufus')
    if not rufus_path:
        return (jsonify({'ok': False, 'error': 'Rufus is not installed on this system. Download from https://rufus.ie'}), 503)
    try:
        body = _json_body()
        if body is None:
            return _missing_field('request body')
    except Exception:
        return _missing_field('request body')
    iso_path = body.get('iso_path', '')
    drive_letter = body.get('drive', '')
    volume_label = body.get('volume_label', '')
    target = body.get('target', '')
    if not iso_path or not os.path.isfile(iso_path):
        return (jsonify({'ok': False, 'error': 'iso_path must point to a valid ISO file'}), 400)
    if not drive_letter:
        return (jsonify({'ok': False, 'error': "Missing required field: drive (e.g. 'F')"}), 400)
    drive_letter = str(drive_letter).strip(':\\ ')
    if not re.fullmatch('[A-Za-z]', drive_letter):
        return (jsonify({'ok': False, 'error': "drive must be a single drive letter (e.g. 'F')"}), 400)
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetDriveTypeW.restype = ctypes.c_uint
        drive_type = kernel32.GetDriveTypeW(f'{drive_letter}:\\')
    except Exception:
        drive_type = 0
    if drive_type != 2:
        return (jsonify({'ok': False, 'error': f'drive {drive_letter}: is not removable — refusing to format'}), 400)
    for field_name, value in (('iso_path', iso_path), ('volume_label', volume_label)):
        if value is None:
            continue
        v = str(value)
        if '\x00' in v or '\r' in v or '\n' in v or ('"' in v):
            return (jsonify({'ok': False, 'error': f'{field_name} contains invalid characters'}), 400)
        if v.lstrip().startswith(('/', '-')):
            return (jsonify({'ok': False, 'error': f"{field_name} must not start with '/' or '-'"}), 400)
    if volume_label:
        volume_label = str(volume_label).strip()
        if len(volume_label) > 32:
            return (jsonify({'ok': False, 'error': 'volume_label too long (max 32 chars)'}), 400)
    cmd_parts = [rufus_path, '/create', f'/iso:{iso_path}', f'/drive:{drive_letter}']
    if volume_label:
        cmd_parts.append(f'/volume_label:{volume_label}')
    if target:
        allowed_targets = ['UEFI', 'BIOS', 'MBR', 'GPT', 'UEFI-CSM']
        if target not in allowed_targets:
            return (jsonify({'ok': False, 'error': f'target must be one of {allowed_targets}'}), 400)
        cmd_parts.append(f'/target:{target}')
    try:
        _log(f"[rufus] Running: {' '.join(cmd_parts)}")
        result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=300, errors='replace')
        return jsonify({'ok': result.returncode == 0, 'returncode': result.returncode, 'stdout': result.stdout[:2000], 'stderr': result.stderr[:2000]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'Command timed out (300s)'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)
    except Exception as e:
        return (jsonify({'ok': False, 'error': str(e)}), 500)

_sc_FLAGS_RE = re.compile('^\\s+FLAGS\\s+:\\s+(.+)$')

_sc_PID_RE = re.compile('^\\s+PID\\s+:\\s+(\\d+)$')

_sc_SERVICE_LINE_RE = re.compile('^\\s*SERVICE_NAME:\\s+(.+)$')

_sc_STATE_RE = re.compile('^\\s+STATE\\s+:\\s+(\\d+)\\s+(.+)$')

_sc_TYPE_RE = re.compile('^\\s+TYPE\\s+:\\s+(\\d+)\\s+(.+)$')

_sc_DISPLAY_NAME_RE = re.compile('^\\s*DISPLAY_NAME:\\s+(.+)$')

def _sc__parse_sc_query_output(text):
    """Parse 'sc query' output into a list of service dicts."""
    services = []
    current = {}
    lines = text.split('\n')
    for line in lines:
        stripped = line.strip()
        m = _sc_SERVICE_LINE_RE.match(line)
        if m:
            if current and 'service_name' in current:
                services.append(current)
            current = {'service_name': m.group(1).strip()}
            continue
        if not current or 'service_name' not in current:
            continue
        m = _sc_DISPLAY_NAME_RE.match(line)
        if m:
            current['display_name'] = m.group(1).strip()
            continue
        m = _sc_TYPE_RE.match(line)
        if m:
            current['type_code'] = int(m.group(1))
            current['type'] = m.group(2).strip()
            continue
        m = _sc_STATE_RE.match(line)
        if m:
            current['state_code'] = int(m.group(1))
            current['state'] = m.group(2).strip()
            continue
        m = _sc_PID_RE.match(line)
        if m:
            current['pid'] = int(m.group(1))
            continue
        m = _sc_FLAGS_RE.match(line)
        if m:
            current['flags'] = m.group(1).strip()
            continue
    if current and 'service_name' in current:
        services.append(current)
    return services

def _sc__parse_sc_qc_output(text):
    """Parse 'sc qc <service>' output into a structured dict."""
    result = {}
    lines = text.split('\n')
    mapping = {'SERVICE_NAME': 'service_name', 'DISPLAY_NAME': 'display_name', 'TYPE': 'type', 'START_TYPE': 'start_type', 'ERROR_CONTROL': 'error_control', 'BINARY_PATH_NAME': 'binary_path', 'LOAD_ORDER_GROUP': 'load_order_group', 'TAG': 'tag', 'DEPENDENCIES': 'dependencies_raw', 'SERVICE_START_NAME': 'service_start_name'}
    in_dependencies = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if ':' in stripped:
            key, _, value = stripped.partition(':')
            key = key.strip()
            value = value.strip()
            mapped = mapping.get(key)
            if not mapped:
                in_dependencies = False
                continue
            if mapped == 'start_type':
                if 'DEMAND_START' in value:
                    value = 'Manual'
                elif 'AUTO_START' in value:
                    value = 'Automatic'
                elif 'DISABLED' in value:
                    value = 'Disabled'
                elif 'BOOT_START' in value:
                    value = 'Boot'
                elif 'SYSTEM_START' in value:
                    value = 'System'
                result[mapped] = value
                in_dependencies = False
            elif mapped == 'dependencies_raw':
                result['dependencies'] = [value] if value else []
                in_dependencies = True
            else:
                result[mapped] = value
                in_dependencies = False
        elif in_dependencies:
            result.setdefault('dependencies', []).append(stripped)
    return result

def _sc__clean_service_name(name):
    """Validate a Windows service name."""
    n = str(name or '').strip()
    if not n:
        raise ValueError('service name must not be empty')
    if len(n) > 256:
        raise ValueError('service name too long (max 256 chars)')
    if '\x00' in n:
        raise ValueError('service name cannot contain null bytes')
    if '/' in n or '\\' in n:
        raise ValueError('service name cannot contain path separators')
    return n

def _sc__run_sc(args, timeout=15):
    """Run sc.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('sc')
    if not exe:
        raise RuntimeError('sc not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_sc_175():
    """List all Windows services with their current state."""
    exe = _find_tool('sc')
    if not exe:
        return (jsonify({'ok': False, 'error': 'sc not found'}), 503)
    state_filter = None
    try:
        from flask import request
        state_filter = request.args.get('state', None)
    except Exception:
        pass
    args = ['query']
    if state_filter:
        valid_states = {'active', 'inactive', 'all'}
        if state_filter.lower() not in valid_states:
            return (jsonify({'ok': False, 'error': f"invalid state filter '{state_filter}'. Use one of: {', '.join(sorted(valid_states))}"}), 400)
        args.extend(['state=', state_filter])
    args.extend(['type=', 'service'])
    try:
        stdout, stderr, rc = _sc__run_sc(args, timeout=30)
        if rc != 0 and 'No services' not in stdout and ('1060' not in str(rc)):
            return (jsonify({'ok': False, 'error': stderr.strip() or f'sc query failed (exit code {rc})'}), 502)
        services = _sc__parse_sc_query_output(stdout)
        running = sum((1 for s in services if 'RUNNING' in s.get('state', '')))
        stopped = sum((1 for s in services if 'STOPPED' in s.get('state', '')))
        return jsonify({'ok': True, 'count': len(services), 'running': running, 'stopped': stopped, 'filter': state_filter or 'all', 'services': services})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'sc query timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_sc_176():
    """Get detailed info about a specific service."""
    try:
        from flask import request
        name = request.args.get('name', '')
    except Exception:
        return _missing_field('name (query param)')
    try:
        name = _sc__clean_service_name(name)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('sc')
    if not exe:
        return (jsonify({'ok': False, 'error': 'sc not found'}), 503)
    try:
        stdout, stderr, rc = _sc__run_sc(['query', name], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or f"service '{name}' not found", 'exit_code': rc}), 404)
        parsed = _sc__parse_sc_query_output(stdout)
        service_info = parsed[0] if parsed else {'service_name': name}
        qc_stdout, qc_stderr, qc_rc = _sc__run_sc(['qc', name], timeout=15)
        if qc_rc == 0:
            config = _sc__parse_sc_qc_output(qc_stdout)
        else:
            config = {}
        return jsonify({'ok': True, 'service': service_info, 'config': config})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'sc query timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_sc_177():
    """Start, stop, pause, or resume a service."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    name = body.get('name', '')
    action = body.get('action', '')
    try:
        name = _sc__clean_service_name(name)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    action = str(action).strip().lower()
    valid_actions = {'start', 'stop', 'pause', 'continue'}
    if action not in valid_actions:
        return (jsonify({'ok': False, 'error': f"invalid action '{action}'. Use one of: {', '.join(sorted(valid_actions))}"}), 400)
    exe = _find_tool('sc')
    if not exe:
        return (jsonify({'ok': False, 'error': 'sc not found'}), 503)
    try:
        stdout, stderr, rc = _sc__run_sc([action, name], timeout=30)
        success = rc == 0
        message = stdout.strip()
        if not message and stderr.strip():
            message = stderr.strip()
        return jsonify({'ok': success, 'action': action, 'service': name, 'exit_code': rc, 'message': message})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': f'sc {action} timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_sc_178():
    """Configure a service (startup type, display name, etc.)."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    name = body.get('name', '')
    try:
        name = _sc__clean_service_name(name)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    startup = body.get('startup', None)
    exe = _find_tool('sc')
    if not exe:
        return (jsonify({'ok': False, 'error': 'sc not found'}), 503)
    args = ['config', name]
    if startup is not None:
        startup = str(startup).strip().lower()
        startup_map = {'auto': 'start= auto', 'automatic': 'start= auto', 'manual': 'start= demand', 'demand': 'start= demand', 'disabled': 'start= disabled', 'delayed-auto': 'start= delayed-auto'}
        if startup not in startup_map:
            return (jsonify({'ok': False, 'error': f"invalid startup type '{startup}'. Use: auto, manual, disabled, delayed-auto"}), 400)
        args.extend(startup_map[startup].split())
    if len(args) <= 2:
        return (jsonify({'ok': False, 'error': "no configuration changes specified (use 'startup' field)"}), 400)
    try:
        stdout, stderr, rc = _sc__run_sc(args, timeout=15)
        success = rc == 0
        return jsonify({'ok': success, 'service': name, 'exit_code': rc, 'message': stdout.strip() or stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'sc config timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_sc_179():
    """List services that depend on a given service."""
    try:
        from flask import request
        name = request.args.get('name', '')
    except Exception:
        return _missing_field('name (query param)')
    try:
        name = _sc__clean_service_name(name)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('sc')
    if not exe:
        return (jsonify({'ok': False, 'error': 'sc not found'}), 503)
    try:
        stdout, stderr, rc = _sc__run_sc(['EnumDepend', name], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or f"failed to enumerate dependencies for '{name}'"}), 502)
        dependents = _sc__parse_sc_query_output(stdout)
        return jsonify({'ok': True, 'service': name, 'dependents_count': len(dependents), 'dependents': dependents})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'sc EnumDepend timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _schtasks__run_schtasks(args, timeout=20):
    exe = _find_tool('schtasks')
    if not exe:
        raise RuntimeError('schtasks not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_schtasks_180():
    """List all scheduled tasks or filter by folder/task name."""
    try:
        from flask import request
        task_path = request.args.get('path', '\\')
        folder = request.args.get('folder', '')
        format_type = request.args.get('format', 'TABLE').upper()
    except Exception:
        task_path = '\\'
        folder = ''
        format_type = 'TABLE'
    if format_type not in ('TABLE', 'CSV', 'XML'):
        format_type = 'TABLE'
    args = ['Query', '/FO', format_type]
    if format_type in ('TABLE', 'CSV'):
        args.append('/NH')
    if folder:
        args.extend(['/TN', folder])
    elif task_path:
        args.extend(['/TN', task_path])
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(args, timeout=20)
        return jsonify({'ok': rc == 0, 'format': format_type, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks query timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_schtasks_181():
    """Get detailed information about a specific scheduled task."""
    try:
        from flask import request
        task_name = request.args.get('task', '').strip()
        verbose = request.args.get('verbose', 'false').lower() in ('true', '1', 'yes')
    except Exception:
        task_name = ''
        verbose = False
    if not task_name:
        return _missing_field('task (query param)')
    args = ['Query', '/V', '/FO', 'LIST', '/TN', task_name]
    if not verbose:
        args = ['Query', '/FO', 'LIST', '/TN', task_name]
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(args, timeout=20)
        return jsonify({'ok': rc == 0, 'task_name': task_name, 'verbose': verbose, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks query detail timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_schtasks_182():
    """List task scheduler folders."""
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(['Query', '/FO', 'LIST', '/NH'], timeout=20)
        return jsonify({'ok': rc == 0, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks folders query timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_schtasks_183():
    """Run a scheduled task immediately."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    task_name = str(body.get('task', '')).strip()
    if not task_name:
        return _missing_field('task')
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(['/Run', '/TN', task_name], timeout=30)
        return jsonify({'ok': rc == 0, 'task_name': task_name, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks run timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_schtasks_184():
    """Stop a running scheduled task."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    task_name = str(body.get('task', '')).strip()
    if not task_name:
        return _missing_field('task')
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(['/End', '/TN', task_name], timeout=15)
        return jsonify({'ok': rc == 0, 'task_name': task_name, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks end timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_schtasks_185():
    """Delete a scheduled task."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    task_name = str(body.get('task', '')).strip()
    force = body.get('force', False)
    if not task_name:
        return _missing_field('task')
    args = ['/Delete', '/TN', task_name, '/F']
    if not force:
        args = ['/Delete', '/TN', task_name]
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(args, timeout=15)
        return jsonify({'ok': rc == 0, 'task_name': task_name, 'force': force, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks delete timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_schtasks_186():
    """Create a task that runs a program every N hours."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    task_name = str(body.get('task', '')).strip()
    program = str(body.get('program', '')).strip()
    interval = body.get('interval', 1)
    if not task_name:
        return _missing_field('task')
    if not program:
        return _missing_field('program')
    try:
        interval = int(interval)
    except (ValueError, TypeError):
        return (jsonify({'ok': False, 'error': 'interval must be an integer'}), 400)
    if interval < 1 or interval > 999:
        return (jsonify({'ok': False, 'error': 'interval must be 1-999'}), 400)
    args = ['/Create', '/SC', 'HOURLY', '/MO', str(interval), '/TN', task_name, '/TR', program, '/F']
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(args, timeout=20)
        return jsonify({'ok': rc == 0, 'task_name': task_name, 'program': program, 'interval_hours': interval, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks create timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_schtasks_187():
    """Create a task that runs a program daily at a specific time."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    task_name = str(body.get('task', '')).strip()
    program = str(body.get('program', '')).strip()
    start_time = str(body.get('time', '09:00')).strip()
    interval_days = body.get('interval_days', 1)
    if not task_name:
        return _missing_field('task')
    if not program:
        return _missing_field('program')
    try:
        interval = int(interval_days)
    except (ValueError, TypeError):
        return (jsonify({'ok': False, 'error': 'interval_days must be an integer'}), 400)
    if interval < 1 or interval > 365:
        return (jsonify({'ok': False, 'error': 'interval_days must be 1-365'}), 400)
    args = ['/Create', '/SC', 'DAILY', '/MO', str(interval), '/TN', task_name, '/TR', program, '/ST', start_time, '/F']
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(args, timeout=20)
        return jsonify({'ok': rc == 0, 'task_name': task_name, 'program': program, 'start_time': start_time, 'interval_days': interval, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks create timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_schtasks_188():
    """Create a task that runs a program at system startup."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    task_name = str(body.get('task', '')).strip()
    program = str(body.get('program', '')).strip()
    delay = str(body.get('delay', 'PT0M')).strip()
    if not task_name:
        return _missing_field('task')
    if not program:
        return _missing_field('program')
    args = ['/Create', '/SC', 'ONSTART', '/TN', task_name, '/TR', program, '/DELAY', delay, '/F']
    try:
        stdout, stderr, rc = _schtasks__run_schtasks(args, timeout=20)
        return jsonify({'ok': rc == 0, 'task_name': task_name, 'program': program, 'delay': delay, 'exit_code': rc, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'schtasks create timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _scrcpy__find_adb():
    """Locate adb — scrcpy ships its own or uses system adb."""
    exe = shutil.which('adb')
    if exe:
        return exe
    scrcpy = _find_tool('scrcpy')
    if scrcpy:
        adb_dir = os.path.join(os.path.dirname(scrcpy), 'adb.exe')
        if os.path.isfile(adb_dir):
            return adb_dir
    candidates = [os.path.expandvars('%LOCALAPPDATA%\\Android\\Sdk\\platform-tools\\adb.exe'), os.path.expandvars('%USERPROFILE%\\scoop\\shims\\adb.exe')]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

def _h_scrcpy_189():
    """List connected Android devices via adb."""
    adb = _scrcpy__find_adb()
    if not adb:
        return (jsonify({'error': 'adb not found — install Android SDK platform-tools or install scrcpy', 'devices': [], 'count': 0}), 200)
    try:
        r = subprocess.run([adb, 'devices', '-l'], capture_output=True, text=True, timeout=10)
        lines = r.stdout.strip().split('\n')[1:]
        devices = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                serial = parts[0]
                status = parts[1]
                props = {}
                for p in parts[2:]:
                    if ':' in p:
                        k, v = p.split(':', 1)
                        props[k] = v
                devices.append({'serial': serial, 'status': status, 'properties': props})
        return jsonify({'devices': devices, 'count': len(devices), 'connected': any((d['status'] == 'device' for d in devices))})
    except subprocess.TimeoutExpired:
        _log(f"[scrcpy_devices] {'adb devices timed out'}")
        return (jsonify({'error': 'adb timed out', 'devices': [], 'count': 0}), 504)
    except Exception as e:
        _log(f"[scrcpy_devices] {f'Error: {e}'}")
        return (jsonify({'error': str(e), 'devices': [], 'count': 0}), 500)

def _h_scrcpy_190():
    """List available displays on the first connected device."""
    scrcpy = _find_tool('scrcpy')
    if not scrcpy:
        return (jsonify({'error': 'scrcpy not installed', 'displays': [], 'count': 0}), 200)
    try:
        r = subprocess.run([scrcpy, '--list-displays'], capture_output=True, text=True, timeout=15)
        output = r.stdout.strip()
        displays = []
        for line in output.split('\n'):
            line = line.strip()
            if line and 'display' in line.lower():
                displays.append(line)
        return jsonify({'displays': displays, 'count': len(displays), 'raw': output[:2000]})
    except subprocess.TimeoutExpired:
        _log(f"[scrcpy_displays] {'scrcpy --list-displays timed out (no device connected?)'}")
        return (jsonify({'error': 'Timed out — is a device connected and USB debugging enabled?', 'displays': [], 'count': 0}), 504)
    except Exception as e:
        _log(f"[scrcpy_displays] {f'Error: {e}'}")
        return (jsonify({'error': str(e), 'displays': [], 'count': 0}), 500)

def _h_scrcpy_191():
    """Start or stop headless screen recording.

        Body: {"action": "start"|"stop", "duration": <seconds>, "output": "<path>"}
        Start: launches scrcpy --no-window --record=<output> in the background.
        Stop: kills the running scrcpy recording process.
        """
    body = _json_body()
    if body is None:
        return (jsonify({'error': 'JSON body required'}), 400)
    action = body.get('action', '')
    if action not in ('start', 'stop'):
        return (jsonify({'error': "action must be 'start' or 'stop'"}), 400)
    scrcpy = _find_tool('scrcpy')
    if not scrcpy:
        return (jsonify({'error': 'scrcpy not installed'}), 500)
    adb = _scrcpy__find_adb()
    if adb:
        try:
            r = subprocess.run([adb, 'devices'], capture_output=True, text=True, timeout=5)
            device_lines = [l for l in r.stdout.strip().split('\n')[1:] if l.strip() and '\tdevice' in l]
            if not device_lines:
                return (jsonify({'error': 'No device connected — connect via USB and enable USB debugging'}), 400)
        except Exception:
            pass
    if action == 'start':
        raw_duration = body.get('duration', 30)
        try:
            duration = int(raw_duration)
        except (TypeError, ValueError):
            return (jsonify({'error': 'duration must be an integer number of seconds'}), 400)
        duration = max(1, min(duration, 3600))
        raw_output = body.get('output')
        output_name = os.path.basename(str(raw_output)) if raw_output else 'scrcpy_record.mp4'
        if output_name in ('', '.', '..'):
            output_name = 'scrcpy_record.mp4'
        output_path = os.path.join(tempfile.gettempdir(), output_name)
        try:
            cmd = [scrcpy, '--no-window', '--no-playback', f'--record={output_path}', f'--time-limit={duration}']
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
            _log(f"[scrcpy_record] {f'Started recording to {output_path} for {duration}s (PID {proc.pid})'}")
            return jsonify({'status': 'recording', 'pid': proc.pid, 'output': output_path, 'duration': duration, 'note': f'Recording will auto-stop after {duration}s. Kill PID {proc.pid} to stop early.'})
        except Exception as e:
            _log(f"[scrcpy_record] {f'Failed to start: {e}'}")
            return (jsonify({'error': f'Failed to start recording: {e}'}), 500)
    elif action == 'stop':
        try:
            if os.name == 'nt':
                r = subprocess.run(['taskkill', '/f', '/im', 'scrcpy.exe'], capture_output=True, text=True, timeout=10)
            else:
                r = subprocess.run(['pkill', '-f', 'scrcpy'], capture_output=True, text=True, timeout=10)
            _log(f"[scrcpy_record] {f'Stopped recording: {r.stdout.strip()}'}")
            return jsonify({'status': 'stopped', 'detail': r.stdout.strip() or 'scrcpy processes terminated'})
        except Exception as e:
            _log(f"[scrcpy_record] {f'Failed to stop: {e}'}")
            return (jsonify({'error': f'Failed to stop: {e}'}), 500)

def _h_sd_192():
    """Find & replace across a file, directory, or stdin text.

        Body (JSON):
            find (str, required): Pattern to find.
            replace (str, optional): Replacement text. Default "".
            path (str, optional): File or directory to edit in place. If omitted,
                `input` text is transformed via stdin and returned.
            input (str, optional): Text to transform via stdin (used when no path).
            preview (bool, optional): Dry-run — print changes without writing. Default True.
            fixed_strings (bool, optional): Treat `find` as a literal, not regex. Default False.
            flags (str, optional): Regex flags (e.g. "i" for case-insensitive). Default "".
        """
    body = _json_body()
    find = body.get('find')
    if find in (None, ''):
        return _missing_field(body, 'find')
    replace = body.get('replace', '')
    path = body.get('path') or None
    input_text = body.get('input')
    preview = str(body.get('preview', 'true')).lower() in ('1', 'true', 'yes')
    fixed_strings = str(body.get('fixed_strings', 'false')).lower() in ('1', 'true', 'yes')
    flags = str(body.get('flags', '') or '')
    if not path and input_text is None:
        return (jsonify({'error': "Either 'path' or 'input' is required"}), 400)
    exe = _find_tool('sd')
    if not exe:
        return (jsonify({'error': 'sd is not installed', 'hint': 'Install with: winget install chmln.sd'}), 503)
    cmd = [exe]
    if preview:
        cmd.append('--preview')
    if fixed_strings:
        cmd.append('--fixed-strings')
    if flags:
        cmd.extend(['--flags', flags])
    cmd.append(find)
    cmd.append(replace)
    if path:
        cmd.append(path)
    try:
        r = subprocess.run(cmd, input=input_text if not path else None, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            _log(f'auto_sd_replace: sd exited {r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'sd failed'}), 500)
        out = r.stdout
        if path:
            return jsonify({'preview': preview, 'path': path, 'changed': bool(out.strip()) if preview else True, 'output_lines': out.count('\n') + (1 if out else 0), 'sample': out[:4000]})
        return jsonify({'preview': preview, 'changed': out != input_text, 'output': out})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'sd timed out after 60s'}), 504)
    except Exception as e:
        _log(f'auto_sd_replace exception: {e}')
        return (jsonify({'error': str(e)}), 500)

def _sfc__run_sfc(args, timeout=120):
    """Run sfc.exe with given args, return parsed output or raise."""
    exe = _find_tool('sfc')
    if not exe:
        raise RuntimeError('sfc.exe not found on system')
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('SFC operation timed out (this can take a while for /scannow)')
    except OSError as e:
        raise RuntimeError(f'SFC execution failed: {e}')
    return result

def _sfc__parse_sfc_output(output):
    """Parse SFC output for key status indicators."""
    result = {'raw': output, 'summary': '', 'found_corruption': False, 'repaired': False, 'unable_to_repair': False, 'details': []}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        result['details'].append(stripped)
        if 'Windows Resource Protection' in stripped:
            result['summary'] = stripped
        if 'found corrupt files' in stripped.lower():
            result['found_corruption'] = True
        lowered = stripped.lower()
        if 'repaired' in lowered and 'unable' not in lowered and ('not repaired' not in lowered) and ('could not be repaired' not in lowered):
            result['repaired'] = True
        if 'unable to repair' in lowered or 'could not repair' in lowered:
            result['unable_to_repair'] = True
    return result

def _h_sfc_193():
    """Run sfc /scannow — full system file integrity check and repair."""
    try:
        result = _sfc__run_sfc(['/scannow'], timeout=300)
        parsed = _sfc__parse_sfc_output(result.stdout or result.stderr or '')
        return jsonify({'ok': True, 'returncode': result.returncode, 'summary': parsed['summary'], 'found_corruption': parsed['found_corruption'], 'repaired': parsed['repaired'], 'unable_to_repair': parsed['unable_to_repair'], 'output': parsed['raw']})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_sfc_194():
    """Run sfc /verifyonly — quick integrity check without repair."""
    try:
        result = _sfc__run_sfc(['/verifyonly'], timeout=180)
        parsed = _sfc__parse_sfc_output(result.stdout or result.stderr or '')
        return jsonify({'ok': True, 'returncode': result.returncode, 'summary': parsed['summary'], 'found_corruption': parsed['found_corruption'], 'clean': not parsed['found_corruption'], 'output': parsed['raw']})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_sfc_195():
    """Verify a specific file's integrity (must be a protected system file)."""
    body = _json_body()
    filepath = str(body.get('file') or '').strip()
    if not filepath:
        return _missing_field('file')
    if len(filepath) > 260:
        return (jsonify({'ok': False, 'error': 'File path too long (max 260 chars)'}), 400)
    try:
        result = _sfc__run_sfc(['/VERIFYFILE=' + filepath], timeout=60)
        parsed = _sfc__parse_sfc_output(result.stdout or result.stderr or '')
        return jsonify({'ok': True, 'file': filepath, 'summary': parsed['summary'], 'found_corruption': parsed['found_corruption'], 'output': parsed['raw']})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'file': filepath, 'error': str(e)}), 503)

def _h_sfc_196():
    """Check last SFC scan log from CBS.log for previous results."""
    try:
        cbs_log = 'C:\\Windows\\Logs\\CBS\\CBS.log'
        if not os.path.isfile(cbs_log):
            return jsonify({'ok': True, 'info': 'CBS log not found — no prior SFC scan data'})
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', f"Get-Content '{cbs_log}' -Tail 100 -ErrorAction SilentlyContinue | Select-String 'SFC|sfc|System File Checker|Windows Resource Protection'"], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': f"CBS log read failed: {result.stderr.strip() or 'unknown error'}"}), 503)
        entries = [l.strip() for l in (result.stdout or '').splitlines() if l.strip()]
        return jsonify({'ok': True, 'log_entries': entries[-20:], 'count': len(entries)})
    except (subprocess.TimeoutExpired, OSError) as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _sharex__run_sharex_action(action, file_path=None):
    """Run a ShareX CLI action and return result."""
    exe = _find_tool('sharex')
    if not exe:
        return (None, 'ShareX not installed')
    cmd = [exe, f'-{action}']
    if file_path:
        cmd.append(file_path)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (result, None)
    except subprocess.TimeoutExpired:
        return (None, 'Operation timed out (60s)')
    except OSError as e:
        return (None, f'OS error: {str(e)}')

def _sharex__format_bytes(size):
    """Format byte size to human-readable string."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024:
            return f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} PB'

def _h_sharex_197():
    """Capture full screen or region using ShareX or Python fallback (mss)."""
    try:
        body = _json_body()
    except Exception:
        body = {}
    region = body.get('region', None)
    exe = _find_tool('sharex')
    if exe:
        try:
            action = 'PrintScreen' if not region else 'RectangleRegion'
            result, err = _sharex__run_sharex_action(action)
            if result and result.returncode == 0:
                screenshots_dir = os.path.expanduser('~\\Pictures\\ShareX\\Screenshots')
                if not os.path.isdir(screenshots_dir):
                    screenshots_dir = os.path.expanduser('~\\Pictures\\Screenshots')
                latest = None
                latest_time = 0
                if os.path.isdir(screenshots_dir):
                    for f in os.listdir(screenshots_dir):
                        fpath = os.path.join(screenshots_dir, f)
                        if os.path.isfile(fpath) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                            mtime = os.path.getmtime(fpath)
                            if mtime > latest_time:
                                latest_time = mtime
                                latest = fpath
                if latest:
                    return jsonify({'ok': True, 'tool': 'ShareX', 'file': latest, 'size_bytes': os.path.getsize(latest), 'captured_at': datetime.fromtimestamp(latest_time).isoformat()})
            return jsonify({'ok': True, 'tool': 'ShareX', 'action_triggered': action, 'note': 'Screenshot captured via ShareX. Check ShareX output folder for result.'})
        except Exception as e:
            _log(f'ShareX screenshot failed: {e}')
    try:
        import mss
        import mss.tools
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = _STATE.screenshots_dir if hasattr(_STATE, 'screenshots_dir') else tempfile.gettempdir()
        os.makedirs(output_dir, exist_ok=True)
        with mss.mss() as sct:
            if region is None:
                monitor = sct.monitors[0]
                output_path = os.path.join(output_dir, f'sharex_screen_{timestamp}.png')
                sct_img = sct.grab(monitor)
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)
            elif isinstance(region, str) and region.startswith('monitor_'):
                try:
                    idx = int(region.split('_')[1])
                except (ValueError, IndexError):
                    return (jsonify({'ok': False, 'error': 'invalid monitor region (expected monitor_N)'}), 400)
                if 0 < idx < len(sct.monitors):
                    monitor = sct.monitors[idx]
                else:
                    monitor = sct.monitors[1]
                output_path = os.path.join(output_dir, f'sharex_monitor{idx}_{timestamp}.png')
                sct_img = sct.grab(monitor)
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)
            elif isinstance(region, dict):
                try:
                    mon = {'top': int(region.get('top', 0)), 'left': int(region.get('left', 0)), 'width': int(region.get('width', 800)), 'height': int(region.get('height', 600))}
                except (TypeError, ValueError):
                    return (jsonify({'ok': False, 'error': 'invalid region coordinates (top/left/width/height must be integers)'}), 400)
                output_path = os.path.join(output_dir, f'sharex_region_{timestamp}.png')
                sct_img = sct.grab(mon)
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)
            else:
                output_path = os.path.join(output_dir, f'sharex_screen_{timestamp}.png')
                sct_img = sct.grab(sct.monitors[0])
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)
        return jsonify({'ok': True, 'tool': 'Python mss (fallback)', 'file': output_path, 'size_bytes': os.path.getsize(output_path), 'captured_at': datetime.now().isoformat()})
    except ImportError:
        return (jsonify({'ok': False, 'error': 'Neither ShareX nor mss (Python) is available. Install mss: pip install mss'}), 503)

def _h_sharex_198():
    """Upload a file using ShareX or Python fallback (simulate)."""
    body = _json_body()
    file_path = body.get('file', '')
    if not file_path:
        return _missing_field('file')
    if not os.path.isfile(file_path):
        return (jsonify({'ok': False, 'error': f'File not found: {file_path}'}), 400)
    exe = _find_tool('sharex')
    if exe:
        result, err = _sharex__run_sharex_action('FileUpload', file_path)
        if result and result.returncode == 0:
            return jsonify({'ok': True, 'tool': 'ShareX', 'file': file_path, 'action': 'FileUpload triggered'})
        return (jsonify({'ok': False, 'error': f'ShareX upload failed: {err or result.stderr.strip()}'}), 502)
    file_size = os.path.getsize(file_path)
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    file_hash = h.hexdigest()
    return jsonify({'ok': True, 'tool': 'Python fallback', 'file': file_path, 'file_size_bytes': file_size, 'sha256': file_hash, 'note': 'ShareX not installed. File hash computed for verification. Install ShareX for actual upload.'})

def _h_sharex_199():
    """Compute file hash using ShareX or Python fallback."""
    body = _json_body()
    file_path = body.get('file', '')
    algorithm = body.get('algorithm', 'sha256').lower()
    if not file_path:
        return _missing_field('file')
    if not os.path.isfile(file_path):
        return (jsonify({'ok': False, 'error': f'File not found: {file_path}'}), 400)
    supported = {'md5', 'sha1', 'sha256', 'sha384', 'sha512', 'crc32'}
    if algorithm not in supported:
        return (jsonify({'ok': False, 'error': f"Unsupported algorithm '{algorithm}'. Supported: {', '.join(sorted(supported))}"}), 400)
    exe = _find_tool('sharex')
    if exe:
        result, err = _sharex__run_sharex_action('HashCheck', file_path)
        if result and result.returncode == 0:
            return jsonify({'ok': True, 'file': file_path, 'hash': result.stdout.strip(), 'algorithm': algorithm, 'tool': 'ShareX'})
    h = hashlib.new(algorithm)
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    hexdigest = h.hexdigest()
    return jsonify({'ok': True, 'file': file_path, 'hash': hexdigest, 'algorithm': algorithm, 'tool': 'Python hashlib (fallback)'})

def _h_sharex_200():
    """Open ShareX color picker or return pixel color info from a point."""
    try:
        body = _json_body()
    except Exception:
        body = {}
    x = body.get('x', None)
    y = body.get('y', None)
    exe = _find_tool('sharex')
    if not x or not y:
        if exe:
            result, err = _sharex__run_sharex_action('ScreenColorPicker')
            if result and result.returncode == 0:
                return jsonify({'ok': True, 'tool': 'ShareX', 'action': 'ScreenColorPicker triggered'})
        return jsonify({'ok': True, 'tool': 'Python fallback', 'note': 'ShareX not installed. Provide x and y coordinates to sample pixel color.'})
    return jsonify({'ok': True, 'tool': 'Python fallback', 'note': 'Full pixel color sampling requires ShareX. Provide coordinates for coordinate-only result.', 'x': x, 'y': y})

def _h_sharex_201():
    """Open image in ShareX image editor or provide Python Pillow fallback info."""
    body = _json_body()
    file_path = body.get('file', '')
    if not file_path:
        return _missing_field('file')
    if not os.path.isfile(file_path):
        return (jsonify({'ok': False, 'error': f'File not found: {file_path}'}), 400)
    exe = _find_tool('sharex')
    if exe:
        result, err = _sharex__run_sharex_action('ImageEditor', file_path)
        if result and result.returncode == 0:
            return jsonify({'ok': True, 'tool': 'ShareX', 'file': file_path, 'action': 'ImageEditor opened'})
    try:
        from PIL import Image
        with Image.open(file_path) as img:
            width, height = img.size
            mode = img.mode
            fmt = img.format
        return jsonify({'ok': True, 'tool': 'Python Pillow (fallback)', 'file': file_path, 'width': width, 'height': height, 'mode': mode, 'format': fmt})
    except ImportError:
        return jsonify({'ok': True, 'tool': 'os.stat (fallback)', 'file': file_path, 'size_bytes': os.path.getsize(file_path), 'note': 'Install Pillow (pip install Pillow) for image metadata.'})

def _h_sharex_202():
    """Run OCR on an image using ShareX or Python fallback (pytesseract)."""
    body = _json_body()
    file_path = body.get('file', '')
    if not file_path:
        return _missing_field('file')
    if not os.path.isfile(file_path):
        return (jsonify({'ok': False, 'error': f'File not found: {file_path}'}), 400)
    exe = _find_tool('sharex')
    if exe:
        result, err = _sharex__run_sharex_action('OCR', file_path)
        if result and result.returncode == 0:
            return jsonify({'ok': True, 'tool': 'ShareX OCR', 'text': result.stdout.strip()})
    tesseract = shutil.which('tesseract.exe')
    if tesseract:
        try:
            result = subprocess.run([tesseract, file_path, 'stdout'], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return jsonify({'ok': True, 'tool': 'Tesseract OCR (fallback)', 'text': result.stdout.strip()})
        except (subprocess.TimeoutExpired, OSError):
            pass
    return (jsonify({'ok': False, 'error': 'No OCR engine available. Install ShareX, Tesseract (tesseract.exe), or pytesseract.'}), 503)

def _h_sharex_203():
    """Extract file metadata using ShareX or Python fallback."""
    body = _json_body()
    file_path = body.get('file', '')
    if not file_path:
        return _missing_field('file')
    if not os.path.isfile(file_path):
        return (jsonify({'ok': False, 'error': f'File not found: {file_path}'}), 400)
    exe = _find_tool('sharex')
    if exe:
        result, err = _sharex__run_sharex_action('Metadata', file_path)
        if result and result.returncode == 0:
            return jsonify({'ok': True, 'tool': 'ShareX', 'metadata': result.stdout.strip()})
    stat = os.stat(file_path)
    filename, ext = os.path.splitext(os.path.basename(file_path))
    file_size = stat.st_size
    exif_data = {}
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        with Image.open(file_path) as img:
            exif = img._getexif()
            if exif:
                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if isinstance(value, bytes):
                        try:
                            value = value.decode('utf-8', errors='replace')
                        except Exception:
                            value = str(value)
                    exif_data[str(tag)] = str(value)
    except (ImportError, Exception):
        pass
    return jsonify({'ok': True, 'tool': 'Python (fallback)', 'file': file_path, 'filename': filename, 'extension': ext, 'size_bytes': file_size, 'size_readable': _sharex__format_bytes(file_size), 'created': datetime.fromtimestamp(stat.st_ctime).isoformat(), 'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(), 'accessed': datetime.fromtimestamp(stat.st_atime).isoformat(), 'exif': exif_data if exif_data else None})

_sharpdxscreencapture_SCREENSHOTS_DIR = COAGENT_DIR / 'screenshots'

def _sharpdxscreencapture__optional_int(value, field, default, minimum, maximum):
    if value in (None, ''):
        return default
    number = int(value)
    if number < minimum or number > maximum:
        raise ValueError(f'{field} must be between {minimum} and {maximum}')
    return number

def _sharpdxscreencapture__clean_output_path(value):
    output = str(value or '').strip()
    if not output:
        raise ValueError('output must not be empty')
    if '\x00' in output:
        raise ValueError('output cannot contain null bytes')
    if any((ord(c) < 32 for c in output)):
        raise ValueError('output cannot contain control characters')
    suffix = Path(output).suffix.lower()
    if suffix not in {'.png', '.jpg', '.jpeg', '.bmp'}:
        raise ValueError('output must end with .png, .jpg, .jpeg, or .bmp')
    candidate = Path(output)
    root = _sharpdxscreencapture_SCREENSHOTS_DIR.resolve()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (_sharpdxscreencapture_SCREENSHOTS_DIR / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError('output path must be within screenshots directory')
    return str(resolved)

def _sharpdxscreencapture__find_sharpdx_capture():
    configured = os.environ.get('SHARPDXSCREENCAPTURE_EXE', '').strip()
    if configured and Path(configured).is_file():
        return configured
    return shutil.which('SharpDxScreenCapture.exe') or shutil.which('SharpDxScreenCapture') or shutil.which('sharpdxscreencapture.exe') or shutil.which('sharpdxscreencapture')

def _h_sharpdxscreencapture_204():
    data = _json_body()
    missing = _missing_field(data, 'output')
    if missing:
        return missing
    exe = _sharpdxscreencapture__find_sharpdx_capture()
    if not exe:
        return (jsonify({'ok': False, 'error': 'SharpDxScreenCapture command not found on PATH', 'hint': 'Build the project and set SHARPDXSCREENCAPTURE_EXE to the executable path, or add it to PATH.'}), 503)
    try:
        output = _sharpdxscreencapture__clean_output_path(data.get('output'))
        adapter = _sharpdxscreencapture__optional_int(data.get('adapter'), 'adapter', 0, 0, 16)
        display = _sharpdxscreencapture__optional_int(data.get('display'), 'display', 0, 0, 16)
        timeout = _sharpdxscreencapture__optional_int(data.get('timeout'), 'timeout', 15, 1, 120)
    except (TypeError, ValueError) as exc:
        return (jsonify({'ok': False, 'error': str(exc)}), 400)
    command = [exe, '--output', output, '--adapter', str(adapter), '--display', str(display)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as exc:
        _log(f'[sharpdxscreencapture] timed out after {timeout}s output={output}')
        return (jsonify({'ok': False, 'error': f'SharpDxScreenCapture timed out after {timeout}s', 'stdout': exc.stdout or '', 'stderr': exc.stderr or ''}), 504)
    except OSError as exc:
        _log(f'[sharpdxscreencapture] launch failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    ok = result.returncode == 0
    _log(f'[sharpdxscreencapture] exit={result.returncode} output={output}')
    return (jsonify({'ok': ok, 'exit_code': result.returncode, 'output': output, 'stdout': result.stdout, 'stderr': result.stderr}), 200 if ok else 502)

def _shutdown__parse_delay(value, default=30):
    try:
        d = int(value)
    except (TypeError, ValueError):
        raise ValueError('delay must be an integer number of seconds')
    if d < 0 or d > 315360000:
        raise ValueError('delay must be between 0 and 315360000 seconds (10 years)')
    return d

def _shutdown__is_shutdown_available():
    exe = _find_tool('shutdown')
    if not exe:
        return False
    try:
        result = subprocess.run([exe, '/?'], capture_output=True, text=True, timeout=10)
        return result.returncode in (0, 1)
    except (subprocess.TimeoutExpired, OSError):
        return False

def _shutdown__parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return default

def _shutdown__validate_reason_code(reason):
    """Validate a shutdown reason code in the Windows /d format '[p|u:]xx:yy'."""
    r = str(reason or '').strip()
    if not r:
        return None
    parts = r.split(':')
    if len(parts) == 3:
        prefix, major_s, minor_s = parts
        if prefix.lower() not in ('p', 'u'):
            raise ValueError("reason prefix must be 'p' (planned) or 'u' (unplanned)")
    elif len(parts) == 2:
        major_s, minor_s = parts
    else:
        raise ValueError("reason code must be in format '[p|u:]xx:yy' (e.g., 'p:0:0' or '0:0')")
    try:
        major = int(major_s)
        minor = int(minor_s)
    except ValueError:
        raise ValueError('reason code parts must be integers')
    if major < 0 or major > 255:
        raise ValueError('major reason must be 0-255')
    if minor < 0 or minor > 65535:
        raise ValueError('minor reason must be 0-65535')
    return r

def _shutdown__run_shutdown(args, timeout=30):
    """Run shutdown.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('shutdown')
    if not exe:
        raise RuntimeError('shutdown not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_shutdown_205():
    """Shutdown the system."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    try:
        delay = _shutdown__parse_delay(body.get('delay', 30))
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    force = _shutdown__parse_bool(body.get('force', False))
    message = str(body.get('message', ''))
    reason = body.get('reason', None)
    remote = str(body.get('remote', ''))
    exe = _find_tool('shutdown')
    if not exe:
        return (jsonify({'ok': False, 'error': 'shutdown not found'}), 503)
    args = ['/s', f'/t', str(delay)]
    if force:
        args.append('/f')
    if message:
        if len(message) > 4096:
            return (jsonify({'ok': False, 'error': 'message too long (max 4096 chars)'}), 400)
        args.extend(['/c', message])
    if reason:
        try:
            r = _shutdown__validate_reason_code(reason)
            if r:
                args.extend(['/d', r])
        except ValueError as e:
            return (jsonify({'ok': False, 'error': str(e)}), 400)
    if remote:
        remote = str(remote).strip()
        if not remote.startswith('\\\\'):
            remote = f'\\\\{remote}'
        args.extend(['/m', remote])
    try:
        stdout, stderr, rc = _shutdown__run_shutdown(args, timeout=60)
        success = rc == 0
        return jsonify({'ok': success, 'action': 'shutdown', 'delay': delay, 'force': force, 'remote': remote or 'local', 'exit_code': rc, 'message': stdout.strip() or stderr.strip() or f'Shutdown initiated with {delay}s delay'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'shutdown timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_shutdown_206():
    """Restart the system."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    try:
        delay = _shutdown__parse_delay(body.get('delay', 30))
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    force = _shutdown__parse_bool(body.get('force', False))
    message = str(body.get('message', ''))
    reason = body.get('reason', None)
    remote = str(body.get('remote', ''))
    boot_to_firmware = _shutdown__parse_bool(body.get('boot_to_firmware', False))
    exe = _find_tool('shutdown')
    if not exe:
        return (jsonify({'ok': False, 'error': 'shutdown not found'}), 503)
    args = ['/r', f'/t', str(delay)]
    if force:
        args.append('/f')
    if boot_to_firmware:
        args.append('/fw')
    if message:
        if len(message) > 4096:
            return (jsonify({'ok': False, 'error': 'message too long (max 4096 chars)'}), 400)
        args.extend(['/c', message])
    if reason:
        try:
            r = _shutdown__validate_reason_code(reason)
            if r:
                args.extend(['/d', r])
        except ValueError as e:
            return (jsonify({'ok': False, 'error': str(e)}), 400)
    if remote:
        remote = str(remote).strip()
        if not remote.startswith('\\\\'):
            remote = f'\\\\{remote}'
        args.extend(['/m', remote])
    try:
        stdout, stderr, rc = _shutdown__run_shutdown(args, timeout=60)
        success = rc == 0
        return jsonify({'ok': success, 'action': 'restart', 'delay': delay, 'force': force, 'boot_to_firmware': boot_to_firmware, 'remote': remote or 'local', 'exit_code': rc, 'message': stdout.strip() or stderr.strip() or f'Restart initiated with {delay}s delay'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'restart timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_shutdown_207():
    """Log off the current user session."""
    exe = _find_tool('shutdown')
    if not exe:
        return (jsonify({'ok': False, 'error': 'shutdown not found'}), 503)
    try:
        stdout, stderr, rc = _shutdown__run_shutdown(['/l'], timeout=30)
        success = rc == 0
        return jsonify({'ok': success, 'action': 'logoff', 'exit_code': rc, 'message': stdout.strip() or stderr.strip() or 'Logoff initiated'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'logoff timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_shutdown_208():
    """Hibernate the system."""
    exe = _find_tool('shutdown')
    if not exe:
        return (jsonify({'ok': False, 'error': 'shutdown not found'}), 503)
    try:
        stdout, stderr, rc = _shutdown__run_shutdown(['/h'], timeout=30)
        success = rc == 0
        return jsonify({'ok': success, 'action': 'hibernate', 'exit_code': rc, 'message': stdout.strip() or stderr.strip() or 'Hibernate initiated'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'hibernate timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_shutdown_209():
    """Abort a pending shutdown or restart."""
    exe = _find_tool('shutdown')
    if not exe:
        return (jsonify({'ok': False, 'error': 'shutdown not found'}), 503)
    try:
        stdout, stderr, rc = _shutdown__run_shutdown(['/a'], timeout=15)
        success = rc == 0
        return jsonify({'ok': success, 'action': 'abort', 'exit_code': rc, 'message': stdout.strip() or stderr.strip() or 'Pending shutdown aborted'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'abort timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_shutdown_210():
    """Power off the system immediately (no delay, no warning)."""
    exe = _find_tool('shutdown')
    if not exe:
        return (jsonify({'ok': False, 'error': 'shutdown not found'}), 503)
    try:
        stdout, stderr, rc = _shutdown__run_shutdown(['/p'], timeout=30)
        success = rc == 0
        return jsonify({'ok': success, 'action': 'poweroff', 'exit_code': rc, 'message': stdout.strip() or stderr.strip() or 'Power off initiated'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'poweroff timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_shutdown_211():
    """Hybrid shutdown (fast startup) — prepares for faster boot."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    try:
        delay = _shutdown__parse_delay(body.get('delay', 0))
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    force = _shutdown__parse_bool(body.get('force', False))
    exe = _find_tool('shutdown')
    if not exe:
        return (jsonify({'ok': False, 'error': 'shutdown not found'}), 503)
    args = ['/s', '/hybrid', f'/t', str(delay)]
    if force:
        args.append('/f')
    try:
        stdout, stderr, rc = _shutdown__run_shutdown(args, timeout=60)
        success = rc == 0
        return jsonify({'ok': success, 'action': 'hybrid_shutdown', 'delay': delay, 'force': force, 'exit_code': rc, 'message': stdout.strip() or stderr.strip() or f'Hybrid shutdown initiated'})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'hybrid shutdown timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_shutdown_212():
    """Check if a shutdown is pending, and list last shutdown info."""
    import subprocess as sp
    exe = _find_tool('shutdown')
    available = _shutdown__is_shutdown_available()
    pending = False
    last_shutdown = None
    wevtutil = shutil.which('wevtutil') or shutil.which('wevtutil.exe')
    if wevtutil:
        try:
            result = sp.run([wevtutil, 'qe', 'System', '/q', '*[System[(EventID=1074)]]', '/rd', 'true', '/c', '1', '/format:text'], capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                last_shutdown = result.stdout.strip()[:500]
        except Exception:
            pass
    return jsonify({'status': 'ok', 'available': available, 'command': exe or 'shutdown.exe', 'shutdown_pending': pending, 'last_shutdown_event': last_shutdown, 'feature': 'microsoft/windows'})

_systeminfo_KEY_VALUE_RE = re.compile('^(.+?):\\s+(.+)$')

_systeminfo_TARGET_KEYS = {'OS Name': 'os_name', 'OS Version': 'os_version', 'OS Manufacturer': 'os_manufacturer', 'OS Configuration': 'os_configuration', 'OS Build Type': 'os_build_type', 'Registered Owner': 'registered_owner', 'Registered Organization': 'registered_organization', 'System Manufacturer': 'system_manufacturer', 'System Model': 'system_model', 'System Type': 'system_type', 'Processor(s)': 'processors', 'BIOS Version': 'bios_version', 'Windows Directory': 'windows_dir', 'System Directory': 'system_dir', 'Boot Device': 'boot_device', 'System Locale': 'system_locale', 'Input Locale': 'input_locale', 'Time Zone': 'time_zone', 'Total Physical Memory': 'total_physical_mb', 'Available Physical Memory': 'available_physical_mb', 'Virtual Memory: Max Size': 'virtual_memory_max_mb', 'Virtual Memory: Available': 'virtual_memory_available_mb', 'Virtual Memory: In Use': 'virtual_memory_in_use_mb', 'Page File Location(s)': 'page_file_location', 'Domain': 'domain', 'Logon Server': 'logon_server', 'Hotfix(s)': 'hotfix_count', 'Network Card(s)': 'network_cards'}

def _systeminfo__parse_systeminfo_output(text):
    """Parse systeminfo key: value output into structured dict."""
    result = {}
    hotfixes = []
    networks = []
    current_section = None
    lines = text.split('\n')
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        if line_stripped.startswith('Hotfix(s):'):
            current_section = 'hotfixes'
            parts = line_stripped.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                try:
                    result['hotfix_count'] = int(parts[1].strip())
                except ValueError:
                    result['hotfix_count'] = parts[1].strip()
            continue
        if line_stripped.startswith('Network Card(s):'):
            current_section = 'network'
            parts = line_stripped.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                try:
                    result['network_card_count'] = int(parts[1].strip())
                except ValueError:
                    result['network_card_count'] = parts[1].strip()
            continue
        if current_section == 'hotfixes':
            if ']' in line_stripped and 'KB' in line_stripped:
                hotfixes.append(line_stripped)
                continue
            current_section = None
        if current_section == 'network':
            if ']' in line_stripped and ':' in line_stripped:
                networks.append(line_stripped)
                continue
            current_section = None
        mapped = None
        key = None
        value = None
        for candidate in sorted(_systeminfo_TARGET_KEYS, key=len, reverse=True):
            prefix = candidate + ':'
            if line_stripped.startswith(prefix):
                key = candidate
                value = line_stripped[len(prefix):].strip()
                mapped = _systeminfo_TARGET_KEYS[candidate]
                break
        if mapped is None:
            m = _systeminfo_KEY_VALUE_RE.match(line_stripped)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                mapped = _systeminfo_TARGET_KEYS.get(key)
        if mapped:
            if 'Memory' in key or 'Virtual Memory' in key:
                try:
                    num_str = value.split()[0].replace(',', '')
                    result[mapped] = int(num_str)
                except (ValueError, IndexError):
                    result[mapped] = value
            elif key == 'Hotfix(s)':
                try:
                    result[mapped] = int(value)
                except ValueError:
                    result[mapped] = value
            else:
                result[mapped] = value
    if hotfixes:
        result['hotfix_list'] = hotfixes
    if networks:
        result['network_card_list'] = networks
    return result

def _systeminfo__parse_uptime(text):
    """Extract uptime from systeminfo output."""
    m = re.search('System Boot Time:\\s+(.+)$', text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None

def _systeminfo__run_systeminfo(args, timeout=30):
    """Run systeminfo with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('systeminfo')
    if not exe:
        raise RuntimeError('systeminfo not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_systeminfo_213():
    """Get full system information as structured data."""
    exe = _find_tool('systeminfo')
    if not exe:
        return (jsonify({'ok': False, 'error': 'systeminfo not found'}), 503)
    try:
        stdout, stderr, rc = _systeminfo__run_systeminfo(['/FO', 'LIST'], timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'systeminfo failed'}), 502)
        parsed = _systeminfo__parse_systeminfo_output(stdout)
        boot_time = _systeminfo__parse_uptime(stdout)
        return jsonify({'ok': True, 'system': parsed, 'boot_time': boot_time})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'systeminfo timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_systeminfo_214():
    """Get OS-specific information only."""
    exe = _find_tool('systeminfo')
    if not exe:
        return (jsonify({'ok': False, 'error': 'systeminfo not found'}), 503)
    try:
        stdout, stderr, rc = _systeminfo__run_systeminfo(['/FO', 'LIST'], timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'systeminfo failed'}), 502)
        parsed = _systeminfo__parse_systeminfo_output(stdout)
        os_info = {k: parsed.get(k) for k in ['os_name', 'os_version', 'os_manufacturer', 'os_configuration', 'os_build_type', 'registered_owner', 'registered_organization', 'boot_device', 'time_zone'] if k in parsed}
        return jsonify({'ok': True, 'os_info': os_info})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'systeminfo timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_systeminfo_215():
    """Get hardware-specific information only."""
    exe = _find_tool('systeminfo')
    if not exe:
        return (jsonify({'ok': False, 'error': 'systeminfo not found'}), 503)
    try:
        stdout, stderr, rc = _systeminfo__run_systeminfo(['/FO', 'LIST'], timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'systeminfo failed'}), 502)
        parsed = _systeminfo__parse_systeminfo_output(stdout)
        hw_info = {k: parsed.get(k) for k in ['system_manufacturer', 'system_model', 'system_type', 'processors', 'bios_version', 'total_physical_mb', 'available_physical_mb', 'virtual_memory_max_mb', 'virtual_memory_available_mb', 'virtual_memory_in_use_mb', 'page_file_location'] if k in parsed}
        if 'total_physical_mb' in hw_info and 'available_physical_mb' in hw_info:
            total = hw_info['total_physical_mb']
            avail = hw_info['available_physical_mb']
            if total and total > 0:
                hw_info['memory_used_pct'] = round((total - avail) / total * 100, 1)
        return jsonify({'ok': True, 'hardware': hw_info})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'systeminfo timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_systeminfo_216():
    """Get list of installed hotfixes/updates."""
    exe = _find_tool('systeminfo')
    if not exe:
        return (jsonify({'ok': False, 'error': 'systeminfo not found'}), 503)
    try:
        stdout, stderr, rc = _systeminfo__run_systeminfo(['/FO', 'LIST'], timeout=30)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'systeminfo failed'}), 502)
        parsed = _systeminfo__parse_systeminfo_output(stdout)
        return jsonify({'ok': True, 'hotfix_count': parsed.get('hotfix_count', 0), 'hotfixes': parsed.get('hotfix_list', [])})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'systeminfo timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _takeown__run_takeown(args, timeout=30):
    """Run takeown with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('takeown')
    if not exe:
        raise RuntimeError('takeown not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _h_takeown_217():
    """Check what takeown.exe is available for."""
    try:
        stdout, stderr, rc = _takeown__run_takeown(['/?'])
        return jsonify({'ok': rc == 0, 'exit_code': rc, 'available': True})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'takeown check timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_takeown_218():
    """Take ownership of a file or directory.
        
        Body:
          path (required): File or directory path
          recursive (optional, bool): Apply recursively to subdirectories
          admins (optional, bool): Give ownership to Administrators group instead of current user
          default_answer (optional, str): 'Y' or 'N' — default answer when no list-folder permission
          skipsl (optional, bool): Do not follow symbolic links (only with recursive)
        """
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    filepath = body.get('path', '')
    if not isinstance(filepath, str):
        return (jsonify({'ok': False, 'error': 'path must be a string'}), 400)
    filepath = filepath.strip()
    if not filepath:
        return _missing_field('path')
    if filepath.startswith(('/', '-')) or '\x00' in filepath or '\n' in filepath or ('\r' in filepath) or ('"' in filepath):
        return (jsonify({'ok': False, 'error': 'path must not contain flags, quotes, or newlines'}), 400)
    args = ['/F', filepath]
    if body.get('recursive', False):
        args.append('/R')
        da = body.get('default_answer', '')
        if da and str(da).upper() in ('Y', 'N'):
            args.extend(['/D', str(da).upper()])
        else:
            args.extend(['/D', 'Y'])
    if body.get('admins', False):
        args.append('/A')
    if body.get('skipsl', False):
        args.append('/SKIPSL')
    try:
        stdout, stderr, rc = _takeown__run_takeown(args)
        return jsonify({'ok': rc == 0, 'exit_code': rc, 'path': filepath, 'args': args, 'stdout': stdout.strip(), 'stderr': stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'takeown timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _taskkill__parse_taskkill_output(result):
    """Parse taskkill stdout/stderr into structured result."""
    parsed = {'exit_code': result.returncode, 'success': result.returncode == 0, 'message': '', 'errors': []}
    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    if stdout:
        parsed['message'] = stdout
    if stderr:
        for line in stderr.splitlines():
            stripped = line.strip()
            if stripped:
                parsed['errors'].append(stripped)
    return parsed

def _taskkill__run_taskkill(args, timeout=15):
    """Run taskkill.exe with given args, return result object or raise."""
    exe = _find_tool('taskkill')
    if not exe:
        raise RuntimeError('taskkill.exe not found on system')
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('taskkill operation timed out')
    except OSError as e:
        raise RuntimeError(f'taskkill execution failed: {e}')
    return result

def _h_taskkill_219():
    """Kill a process by PID. Optionally force (-f) and kill subtree (-t)."""
    body = _json_body()
    pid = body.get('pid')
    force = bool(body.get('force', False))
    tree = bool(body.get('tree', False))
    if not pid:
        return _missing_field('pid')
    if not isinstance(pid, int) or isinstance(pid, bool):
        return (jsonify({'ok': False, 'error': f'Invalid pid: {pid} (must be an integer)'}), 400)
    if pid <= 0:
        return (jsonify({'ok': False, 'error': 'pid must be positive'}), 400)
    args = ['/pid', str(pid)]
    if force:
        args.append('/f')
    if tree:
        args.append('/t')
    try:
        result = _taskkill__run_taskkill(args)
        parsed = _taskkill__parse_taskkill_output(result)
        return jsonify({'ok': parsed['success'], 'pid': pid, 'force': force, 'tree': tree, 'message': parsed['message'], 'errors': parsed['errors']})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'pid': pid, 'error': str(e)}), 503)

def _h_taskkill_220():
    """Kill process(es) by image name (e.g., 'notepad.exe'). Optionally force and subtree."""
    body = _json_body()
    name = str(body.get('name') or '').strip()
    force = bool(body.get('force', False))
    tree = bool(body.get('tree', False))
    if not name:
        return _missing_field('name')
    if len(name) > 256:
        return (jsonify({'ok': False, 'error': 'Image name too long (max 256 chars)'}), 400)
    args = ['/im', name]
    if force:
        args.append('/f')
    if tree:
        args.append('/t')
    try:
        result = _taskkill__run_taskkill(args)
        parsed = _taskkill__parse_taskkill_output(result)
        return jsonify({'ok': parsed['success'], 'name': name, 'force': force, 'tree': tree, 'message': parsed['message'], 'errors': parsed['errors']})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'name': name, 'error': str(e)}), 503)

def _h_taskkill_221():
    """Kill processes matching one or more filters. Uses /fi parameters.
        Filter format: 'FILTERNAME eq VALUE' (e.g., 'USERNAME eq admin', 'STATUS eq running')
        Common filters: USERNAME, IMAGENAME, PID, SESSION, CPUTIME, MEMUSAGE, STATUS, WINDOWTITLE, SERVICES, MODULES"""
    body = _json_body()
    filters = body.get('filters')
    if not filters or not isinstance(filters, list):
        return _missing_field('filters (list)')
    force = bool(body.get('force', False))
    tree = bool(body.get('tree', False))
    if len(filters) > 10:
        return (jsonify({'ok': False, 'error': 'Maximum 10 filters allowed'}), 400)
    _filter_re = re.compile('^(IMAGENAME|PID|SESSION|CPUTIME|MEMUSAGE|USERNAME|SERVICES|WINDOWTITLE|MODULES|STATUS)\\s+(eq|ne|gt|lt|ge|le)\\s+\\S.*$', re.IGNORECASE)
    args = []
    for f in filters:
        f_str = str(f).strip()
        if not f_str:
            continue
        if not _filter_re.match(f_str):
            return (jsonify({'ok': False, 'error': f'Invalid filter format: {f_str!r}. Expected: FILTERNAME eq VALUE'}), 400)
        args.append('/fi')
        args.append(f_str)
    if not args:
        return (jsonify({'ok': False, 'error': 'At least one valid filter required'}), 400)
    args.append('/im')
    args.append('*')
    if force:
        args.append('/f')
    if tree:
        args.append('/t')
    try:
        result = _taskkill__run_taskkill(args, timeout=15)
        parsed = _taskkill__parse_taskkill_output(result)
        return jsonify({'ok': parsed['success'], 'filters': filters, 'force': force, 'tree': tree, 'message': parsed['message'], 'errors': parsed['errors']})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'filters': filters, 'error': str(e)}), 503)

def _h_taskkill_222():
    """Kill all processes by image name (wrapper for name endpoint with force+tree)."""
    body = _json_body()
    name = str(body.get('name') or '').strip()
    if not name:
        return _missing_field('name')
    if len(name) > 256:
        return (jsonify({'ok': False, 'error': 'Image name too long (max 256 chars)'}), 400)
    args = ['/im', name, '/f', '/t']
    try:
        result = _taskkill__run_taskkill(args)
        parsed = _taskkill__parse_taskkill_output(result)
        return jsonify({'ok': parsed['success'], 'name': name, 'force': True, 'tree': True, 'all': True, 'message': parsed['message'], 'errors': parsed['errors']})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'name': name, 'error': str(e)}), 503)

_tasklist_TASKLIST_LINE_RE = re.compile('^(.+?)\\s+(\\d+)\\s+(\\S+(?:\\s+\\S+)*?)\\s+(\\d+)\\s+(\\d[\\d,]*\\s*K)')

_tasklist_TASKLIST_HEADER_RE = re.compile('^Image Name\\s+PID\\s+Session Name\\s+Session#\\s+Mem Usage')

def _tasklist__run_tasklist(args, timeout=15):
    """Run tasklist with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tool('tasklist')
    if not exe:
        raise RuntimeError('tasklist not found')
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _tasklist__clean_image_name(name):
    """Validate an image/process name."""
    n = str(name or '').strip()
    if not n:
        raise ValueError('image name must not be empty')
    if len(n) > 260:
        raise ValueError('image name too long (max 260 chars)')
    if '\x00' in n:
        raise ValueError('image name cannot contain null bytes')
    forbidden = set('<>"|?*\x00')
    if any((c in n for c in forbidden)):
        raise ValueError(f'image name contains forbidden characters: {forbidden & set(n)}')
    return n

def _tasklist__clean_pid(pid_str):
    """Validate and return a PID integer."""
    try:
        pid = int(str(pid_str).strip())
    except (ValueError, TypeError):
        raise ValueError('PID must be a valid integer')
    if pid < 0 or pid > 4194304:
        raise ValueError('PID must be between 0 and 4194304')
    return pid

def _tasklist__clean_filter(filter_str):
    """Validate a tasklist filter string for injection safety."""
    f = str(filter_str or '').strip()
    if not f:
        raise ValueError('filter must not be empty')
    if len(f) > 200:
        raise ValueError('filter too long (max 200 chars)')
    if '\x00' in f:
        raise ValueError('filter cannot contain null bytes')
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-'eqnltg*.,:\\")
    for c in f:
        if c not in allowed_chars:
            raise ValueError(f"filter contains disallowed character: {repr(c)}. Use basic alphanumeric filters like 'PID eq 1234' or 'IMAGENAME eq notepad.exe'")
    return f

def _tasklist__find_taskkill():
    """Locate taskkill.exe — always in system32 on Windows."""
    exe = shutil.which('taskkill') or shutil.which('taskkill.exe')
    if exe:
        return exe
    for p in ['C:\\Windows\\system32\\taskkill.exe', 'C:\\Windows\\SysWOW64\\taskkill.exe']:
        if os.path.isfile(p):
            return p
    return None

def _h_tasklist_223():
    """List all running processes with standard output."""
    tl = _find_tool('tasklist')
    if not tl:
        return (jsonify({'ok': False, 'error': 'tasklist not found'}), 503)
    try:
        stdout, stderr, rc = _tasklist__run_tasklist(['/V'], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'tasklist failed'}), 502)
        lines = stdout.strip().split('\n')
        processes = []
        header_found = False
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or '===' in line_stripped:
                continue
            if _tasklist_TASKLIST_HEADER_RE.match(line_stripped):
                header_found = True
                continue
            if header_found:
                m = _tasklist_TASKLIST_LINE_RE.match(line_stripped)
                if m:
                    processes.append({'image_name': m.group(1).strip(), 'pid': int(m.group(2)), 'session_name': m.group(3).strip(), 'session_num': int(m.group(4)), 'mem_usage': m.group(5).strip()})
        return jsonify({'ok': True, 'count': min(len(processes), 500), 'processes': processes[:500], 'total_found': len(processes)})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'tasklist timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_tasklist_224():
    """List processes matching specific filters."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    filters_list = body.get('filters', [])
    if not isinstance(filters_list, list):
        return (jsonify({'ok': False, 'error': 'filters must be a list'}), 400)
    tl = _find_tool('tasklist')
    if not tl:
        return (jsonify({'ok': False, 'error': 'tasklist not found'}), 503)
    args = []
    for f in filters_list:
        try:
            clean_f = _tasklist__clean_filter(str(f))
        except ValueError as e:
            return (jsonify({'ok': False, 'error': f"invalid filter '{f}': {e}"}), 400)
        args.append('/FI')
        args.append(clean_f)
    try:
        stdout, stderr, rc = _tasklist__run_tasklist(args + ['/V'], timeout=15)
        if rc != 0:
            return (jsonify({'ok': False, 'error': stderr.strip() or 'tasklist filter failed'}), 502)
        lines = stdout.strip().split('\n')
        processes = []
        header_found = False
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or '===' in line_stripped:
                continue
            if _tasklist_TASKLIST_HEADER_RE.match(line_stripped):
                header_found = True
                continue
            if header_found:
                m = _tasklist_TASKLIST_LINE_RE.match(line_stripped)
                if m:
                    processes.append({'image_name': m.group(1).strip(), 'pid': int(m.group(2)), 'session_name': m.group(3).strip(), 'session_num': int(m.group(4)), 'mem_usage': m.group(5).strip()})
        return jsonify({'ok': True, 'filters': filters_list, 'count': len(processes), 'processes': processes})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'tasklist filter timed out'}), 504)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_tasklist_225():
    """Kill a process by PID or image name."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    pid_raw = body.get('pid', None)
    name_raw = body.get('name', None)
    force = body.get('force', False)
    if pid_raw is None and (not name_raw):
        return (jsonify({'ok': False, 'error': 'pid or name (at least one required)'}), 400)
    tk = _tasklist__find_taskkill()
    if not tk:
        return (jsonify({'ok': False, 'error': 'taskkill not found'}), 503)
    args = []
    if force:
        args.append('/F')
    target = None
    if pid_raw is not None:
        try:
            pid = _tasklist__clean_pid(pid_raw)
        except ValueError as e:
            return (jsonify({'ok': False, 'error': str(e)}), 400)
        args.append('/PID')
        args.append(str(pid))
        target = f'PID {pid}'
    else:
        try:
            name = _tasklist__clean_image_name(name_raw)
        except ValueError as e:
            return (jsonify({'ok': False, 'error': str(e)}), 400)
        args.append('/IM')
        args.append(name)
        target = name
    try:
        result = subprocess.run([tk] + args, capture_output=True, text=True, timeout=15)
        return jsonify({'ok': result.returncode == 0, 'target': target, 'force': force, 'exit_code': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'taskkill timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_tasklist_226():
    """Kill all processes with a given image name."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    name = body.get('name', '')
    force = body.get('force', True)
    try:
        name = _tasklist__clean_image_name(name)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    tk = _tasklist__find_taskkill()
    if not tk:
        return (jsonify({'ok': False, 'error': 'taskkill not found'}), 503)
    args = ['/F'] if force else []
    args.extend(['/IM', name])
    try:
        result = subprocess.run([tk] + args, capture_output=True, text=True, timeout=15)
        return jsonify({'ok': result.returncode == 0, 'name': name, 'force': force, 'exit_code': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'taskkill by name timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

_topgrade__RUN_LOCK = threading.Lock()

_topgrade__STEP_RE = re.compile('^[a-z0-9_-]+$')

def _topgrade__find_config():
    candidates = [os.path.expandvars('%APPDATA%\\topgrade.toml'), os.path.expandvars('%USERPROFILE%\\.config\\topgrade.toml'), os.path.expandvars('%USERPROFILE%\\topgrade.toml')]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

def _topgrade__validate_steps(steps):
    """Reject step names with control chars or flag-like values.

    Steps are joined into a single --only/--disable argument and written to
    the log; allowing newlines or leading '-' enables log injection and
    confusing topgrade flag parsing.
    """
    if not steps:
        return None
    for s in steps:
        if not _topgrade__STEP_RE.match(s):
            return f'invalid step name: {s!r}'
    return None

def _topgrade__split_steps(value):
    """Normalize a step list that may be a list, comma string, or single string."""
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
    else:
        parts = [p.strip() for p in str(value).split(',') if p.strip()]
    return parts or None

def _h_topgrade_227():
    """Preview what topgrade would upgrade, without applying anything."""
    exe = _find_tool('topgrade')
    if not exe:
        return (jsonify({'error': 'topgrade not installed', 'hint': 'Install with: winget install topgrade-rs.topgrade'}), 503)
    try:
        r = subprocess.run([exe, '--dry-run'], capture_output=True, text=True, timeout=60)
        output = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
        return jsonify({'success': r.returncode == 0, 'exit_code': r.returncode, 'output': output.strip()})
    except subprocess.TimeoutExpired:
        _log('topgrade_dry_run: timed out')
        return (jsonify({'error': 'topgrade --dry-run timed out'}), 504)
    except Exception as e:
        _log(f'topgrade_dry_run: Error: {e}')
        return (jsonify({'error': str(e)}), 500)

def _h_topgrade_228():
    """Run system-wide upgrades. Unattended by default (--yes --no-retry).

        Body (all optional):
          only:     list or comma-string of steps to run (e.g. "winget,scoop")
          disable:  list or comma-string of steps to skip
          cleanup:  bool — run --cleanup to remove temp/old files after upgrading
          timeout:  int seconds (default 600, max 1800)
        """
    body = _json_body()
    only_steps = _topgrade__split_steps(body.get('only'))
    disable_steps = _topgrade__split_steps(body.get('disable'))
    steps_err = _topgrade__validate_steps(only_steps) or _topgrade__validate_steps(disable_steps)
    if steps_err:
        return (jsonify({'error': steps_err}), 400)
    cleanup = bool(body.get('cleanup', False))
    timeout = body.get('timeout', 600)
    try:
        timeout = int(timeout)
    except (ValueError, TypeError):
        return (jsonify({'error': f"Invalid timeout: {body.get('timeout')}"}), 400)
    timeout = max(10, min(timeout, 1800))
    exe = _find_tool('topgrade')
    if not exe:
        return (jsonify({'error': 'topgrade not installed', 'hint': 'Install with: winget install topgrade-rs.topgrade'}), 503)
    cmd = [exe, '--yes', '--no-retry']
    if only_steps:
        cmd.extend(['--only', ','.join(only_steps)])
    if disable_steps:
        cmd.extend(['--disable', ','.join(disable_steps)])
    if cleanup:
        cmd.append('--cleanup')
    if not _topgrade__RUN_LOCK.acquire(blocking=False):
        return (jsonify({'error': 'a topgrade run is already in progress', 'success': False}), 409)
    _log(f"topgrade_run: {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
        return jsonify({'success': r.returncode == 0, 'exit_code': r.returncode, 'only': only_steps, 'disable': disable_steps, 'cleanup': cleanup, 'output': output.strip()})
    except subprocess.TimeoutExpired:
        _log(f'topgrade_run: timed out after {timeout}s')
        return (jsonify({'error': f'topgrade timed out after {timeout}s (it may still be running upgrades)', 'timeout': timeout, 'success': False}), 504)
    except Exception as e:
        _log(f'topgrade_run: Error: {e}')
        return (jsonify({'error': str(e), 'success': False}), 500)
    finally:
        _topgrade__RUN_LOCK.release()

def _h_topgrade_229():
    """Return the path to the topgrade config file, if it exists."""
    cfg = _topgrade__find_config()
    if not cfg:
        return jsonify({'config': None, 'message': 'No topgrade.toml found. Create one to customize which steps run.'})
    try:
        with open(cfg, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read(65536)
        return jsonify({'config': cfg, 'content': content, 'truncated': len(content) >= 65536})
    except Exception as e:
        _log(f'topgrade_config: Error reading {cfg}: {e}')
        return (jsonify({'config': cfg, 'error': str(e)}), 500)

def _trippy__run_trip(target, mode='json', cycles=5, protocol='icmp', timeout=30, extra_args=None):
    """Run trippy and return parsed output."""
    exe = _trippy__find_trip()
    if not exe:
        return (None, 'trippy not installed')
    args = [exe, '-m', mode, '-C', str(cycles), '-p', protocol, '--unprivileged']
    if extra_args:
        args.extend(extra_args)
    args.append('--')
    args.append(target)
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=min(timeout, 60))
        return ({'stdout': r.stdout, 'stderr': r.stderr, 'exit_code': r.returncode}, None)
    except subprocess.TimeoutExpired:
        return (None, f'Trace timed out after {timeout}s')
    except FileNotFoundError:
        return (None, 'trip executable not found')
    except Exception as e:
        return (None, str(e))

def _trippy__find_trip():
    """Locate the trip executable on this system."""
    exe = shutil.which('trip')
    if exe:
        return exe
    import os
    cargo_bin = os.path.expanduser('~\\.cargo\\bin\\trip.exe')
    if os.path.isfile(cargo_bin):
        return cargo_bin
    return None

def _h_trippy_230():
    """Run a network trace to the specified target.
        Body: {"target": "google.com", "mode": "json", "cycles": 5, "protocol": "icmp", "timeout": 30}
        Returns: trace output in the requested format.
        """
    body = _json_body()
    if not body:
        return (jsonify({'error': 'JSON body required'}), 400)
    target = body.get('target', '')
    if not isinstance(target, str):
        return (jsonify({'error': 'target must be a string'}), 400)
    target = target.strip()
    if not target:
        return _missing_field('target')
    if target.startswith('-'):
        return (jsonify({'error': 'target must not look like a CLI flag'}), 400)
    mode = body.get('mode', 'json')
    protocol = body.get('protocol', 'icmp')
    if not isinstance(mode, str) or not isinstance(protocol, str):
        return (jsonify({'error': 'mode and protocol must be strings'}), 400)
    raw_cycles = body.get('cycles', 5)
    raw_timeout = body.get('timeout', 30)
    if isinstance(raw_cycles, bool) or isinstance(raw_timeout, bool):
        return (jsonify({'error': 'cycles and timeout must be integers, not booleans'}), 400)
    try:
        cycles = int(raw_cycles)
        timeout = int(raw_timeout)
    except (ValueError, TypeError):
        return (jsonify({'error': 'cycles and timeout must be integers'}), 400)
    if not 1 <= cycles <= 100:
        return (jsonify({'error': 'cycles must be between 1 and 100'}), 400)
    if not 1 <= timeout <= 60:
        return (jsonify({'error': 'timeout must be between 1 and 60'}), 400)
    valid_modes = {'pretty', 'markdown', 'csv', 'json', 'dot', 'flows'}
    if mode not in valid_modes:
        return (jsonify({'error': f"Invalid mode '{mode}'. Valid: {sorted(valid_modes)}"}), 400)
    valid_protocols = {'icmp', 'udp', 'tcp'}
    if protocol not in valid_protocols:
        return (jsonify({'error': f"Invalid protocol '{protocol}'. Valid: {sorted(valid_protocols)}"}), 400)
    result, error = _trippy__run_trip(target, mode=mode, cycles=cycles, protocol=protocol, timeout=timeout)
    if error:
        if 'not installed' in error:
            return (jsonify({'error': error, 'install_hint': 'winget install fujiapple852.trippy'}), 503)
        return (jsonify({'error': error}), 500)
    response = {'target': target, 'mode': mode, 'protocol': protocol, 'cycles': cycles, 'exit_code': result['exit_code']}
    if mode == 'json':
        try:
            parsed = json_lib.loads(result['stdout'])
            response['data'] = parsed
        except json_lib.JSONDecodeError:
            response['raw'] = result['stdout']
            response['parse_error'] = 'Failed to parse JSON output'
    elif mode in ('csv', 'pretty', 'markdown', 'dot'):
        response['data'] = result['stdout']
    else:
        response['data'] = result['stdout']
    if result['stderr']:
        response['stderr'] = result['stderr']
    return jsonify(response)

def _h_trippy_231():
    """Quick multi-target trace (predefined diagnostic targets).
        Returns JSON report for common targets: google.com, cloudflare.com, github.com.
        Query: ?targets=google.com,1.1.1.1  (comma-separated, max 5)
        """
    targets_str = request.args.get('targets', 'google.com,cloudflare.com,github.com')
    targets = [t.strip() for t in targets_str.split(',') if t.strip()][:5]
    targets = [t for t in targets if not t.startswith('-')]
    if not targets:
        return (jsonify({'error': 'No valid targets'}), 400)
    results = {}
    errors = {}
    for target in targets:
        result, error = _trippy__run_trip(target, mode='json', cycles=3, timeout=25)
        if error:
            errors[target] = error
        else:
            try:
                results[target] = json_lib.loads(result['stdout'])
            except (json_lib.JSONDecodeError, KeyError):
                results[target] = {'raw': result.get('stdout', '')}
    return jsonify({'results': results, 'errors': errors, 'targets_requested': targets})

def _ventoy__list_volumes():
    """List available volumes/drives using Python stdlib."""
    volumes = []
    if hasattr(os, 'listdrives'):
        for d in os.listdrives():
            try:
                usage = shutil.disk_usage(d)
                volumes.append({'drive': d, 'total_gb': round(usage.total / 1024 ** 3, 1), 'free_gb': round(usage.free / 1024 ** 3, 1), 'used_gb': round((usage.total - usage.free) / 1024 ** 3, 1)})
            except Exception:
                volumes.append({'drive': d, 'error': 'cannot query'})
    else:
        import string
        for letter in string.ascii_uppercase:
            d = f'{letter}:\\'
            if os.path.exists(d):
                try:
                    usage = shutil.disk_usage(d)
                    volumes.append({'drive': d, 'total_gb': round(usage.total / 1024 ** 3, 1), 'free_gb': round(usage.free / 1024 ** 3, 1), 'used_gb': round((usage.total - usage.free) / 1024 ** 3, 1)})
                except Exception:
                    volumes.append({'drive': d, 'error': 'cannot query'})
    return volumes

def _h_ventoy_232():
    """List available disk volumes/drives that Ventoy could target."""
    try:
        volumes = _ventoy__list_volumes()
        return jsonify({'ok': True, 'volumes': volumes})
    except Exception as e:
        return (jsonify({'ok': False, 'error': str(e)}), 500)

def _h_ventoy_233():
    """Check if a disk looks like a Ventoy drive by looking for the Ventoy partition label."""
    ventoy_path = _find_tool('ventoy')
    volumes = _ventoy__list_volumes()
    ventoy_disks = []
    for vol in volumes:
        d = vol['drive']
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            volume_buf = ctypes.create_unicode_buffer(256)
            fs_buf = ctypes.create_unicode_buffer(256)
            success = kernel32.GetVolumeInformationW(d, volume_buf, 256, None, None, None, fs_buf, 256)
            if success:
                label = volume_buf.value
                fs = fs_buf.value
                if 'VENTOY' in label.upper():
                    ventoy_disks.append({'drive': d, 'label': label, 'filesystem': fs})
        except Exception:
            pass
    return jsonify({'ok': True, 'installed': ventoy_path is not None, 'ventoy_path': ventoy_path, 'ventoy_disks_found': len(ventoy_disks), 'ventoy_disks': ventoy_disks if ventoy_disks else None})

def _h_ventoy_234():
    """Install Ventoy to a target disk using Ventoy2Disk.exe CLI."""
    ventoy_path = _find_tool('ventoy')
    if not ventoy_path:
        return (jsonify({'ok': False, 'error': 'Ventoy is not installed on this system. Download from https://github.com/ventoy/Ventoy/releases'}), 503)
    try:
        body = _json_body()
        if body is None:
            return _missing_field('request body')
    except Exception:
        return _missing_field('request body')
    disk = body.get('disk', '')
    cmd = body.get('cmd', 'I')
    gpt = body.get('gpt', False)
    no_sb = body.get('no_secure_boot', False)
    if not disk:
        return _missing_field('disk (e.g. /Drive:F: or /PhyDrive:1)')
    if not isinstance(disk, str) or not re.match('^(/Drive:[A-Za-z]:|/PhyDrive:\\d{1,3})$', disk):
        return (jsonify({'ok': False, 'error': 'disk must be /Drive:X: or /PhyDrive:N'}), 400)
    if body.get('confirm') is not True:
        return (jsonify({'ok': False, 'error': 'confirm must be true to reformat a disk'}), 400)
    if disk == '/PhyDrive:0':
        return (jsonify({'ok': False, 'error': 'Refusing to target /PhyDrive:0 (system disk)'}), 400)
    if not isinstance(cmd, str):
        return (jsonify({'ok': False, 'error': "cmd must be 'I' or 'U'"}), 400)
    if cmd.upper() not in ('I', 'U'):
        return (jsonify({'ok': False, 'error': "cmd must be 'I' (install) or 'U' (update)"}), 400)
    cmd_parts = [ventoy_path, 'VTOYCLI', f'/{cmd.upper()}', str(disk)]
    if gpt:
        cmd_parts.append('/GPT')
    if no_sb:
        cmd_parts.append('/NOSB')
    try:
        _log(f"[ventoy] Running: {' '.join(cmd_parts)}")
        result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=120)
        return jsonify({'ok': result.returncode == 0, 'returncode': result.returncode, 'stdout': result.stdout[:2000], 'stderr': result.stderr[:2000]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'Command timed out (120s)'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': f'OS error: {e}'}), 502)
    except Exception as e:
        return (jsonify({'ok': False, 'error': str(e)}), 500)

_vssadmin_VOLUME_NAME_RE = re.compile('^\\s*Volume Name:\\s*(.+)$')

_vssadmin_PROVIDER_NAME_RE = re.compile("^\\s*Provider name:\\s*'(.*)'")

_vssadmin_VOLUME_PATH_RE = re.compile('^\\s*Volume Path:\\s*(.+)$')

_vssadmin_WRITER_STATE_RE = re.compile('^\\s*Writer State:\\s*(.+)$')

_vssadmin_PROVIDER_ID_RE = re.compile('^\\s*Provider ID:\\s*{(.+)}')

_vssadmin_MAX_SIZE_PATTERN = re.compile('^\\d+(?:%|[KMGT]B)?$', re.IGNORECASE)

_vssadmin_WRITER_NAME_RE = re.compile("^\\s*Writer name:\\s*'(.+)'")

_vssadmin_WRITER_ID_RE = re.compile('^\\s*Writer Id:\\s*{(.+)}')

_vssadmin_SHADOW_SET_RE = re.compile('^\\s*Shadow Copy Set:\\s*(.+)$')

_vssadmin_SHADOW_ID_RE = re.compile('^\\s*Shadow Copy ID:\\s*(.+)$')

_vssadmin_SHADOW_ID_PATTERN = re.compile('^\\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\\}$')

_vssadmin_SHADOW_VOLUME_RE = re.compile('^\\s*Shadow Copy Volume:\\s*(.+)$')

_vssadmin_STORAGE_LIMIT_RE = re.compile('^\\s*Maximum Shadow Copy Storage space:\\s*(.+)$')

_vssadmin_STORAGE_ALLOC_RE = re.compile('^\\s*Allocated Shadow Copy Storage space:\\s*(.+)$')

_vssadmin_STORAGE_USED_RE = re.compile('^\\s*Used Shadow Copy Storage space:\\s*(.+)$')

_vssadmin_PROVIDER_TYPE_RE = re.compile('^\\s*Provider type:\\s*(.+)$')

def _vssadmin__run_vssadmin(args, timeout=30):
    """Run vssadmin.exe with given args, return parsed output or raise."""
    exe = _find_tool('vssadmin')
    if not exe:
        raise RuntimeError('vssadmin.exe not found on system')
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('vssadmin operation timed out')
    except OSError as e:
        raise RuntimeError(f'vssadmin execution failed: {e}')
    if result.returncode != 0:
        stderr = (result.stderr or '').strip()
        raise RuntimeError(stderr or 'vssadmin returned non-zero exit code')
    return result.stdout

def _vssadmin__parse_volumes(output):
    """Parse List Volumes output into structured list."""
    volumes = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                volumes.append(current)
                current = {}
            continue
        m = _vssadmin_VOLUME_PATH_RE.match(stripped)
        if m:
            current['volume_path'] = m.group(1).strip()
            continue
        m = _vssadmin_VOLUME_NAME_RE.match(stripped)
        if m:
            current['volume_name'] = m.group(1).strip()
            continue
        if current and ':' in stripped:
            parts = stripped.split(':', 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                current[key] = val
    if current:
        volumes.append(current)
    return volumes

def _vssadmin__parse_providers(output):
    """Parse List Providers output into structured list."""
    providers = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                providers.append(current)
                current = {}
            continue
        m = _vssadmin_PROVIDER_NAME_RE.match(stripped)
        if m:
            current['name'] = m.group(1).strip()
            continue
        m = _vssadmin_PROVIDER_TYPE_RE.match(stripped)
        if m:
            current['provider_type'] = m.group(1).strip()
            continue
        m = _vssadmin_PROVIDER_ID_RE.match(stripped)
        if m:
            current['provider_id'] = '{' + m.group(1).strip() + '}'
            continue
        if current and ':' in stripped:
            parts = stripped.split(':', 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                current[key] = val
    if current:
        providers.append(current)
    return providers

def _vssadmin__parse_shadow_copies(output):
    """Parse List Shadows output into structured list."""
    copies = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                copies.append(current)
                current = {}
            continue
        m = _vssadmin_SHADOW_ID_RE.match(stripped)
        if m:
            current['shadow_copy_id'] = m.group(1).strip()
            continue
        m = _vssadmin_SHADOW_VOLUME_RE.match(stripped)
        if m:
            current['shadow_copy_volume'] = m.group(1).strip()
            continue
        m = _vssadmin_SHADOW_SET_RE.match(stripped)
        if m:
            current['shadow_copy_set'] = m.group(1).strip()
            continue
        if current and ':' in stripped:
            parts = stripped.split(':', 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                current[key] = val
    if current:
        copies.append(current)
    return copies

def _vssadmin__parse_writers(output):
    """Parse List Writers output into structured list."""
    writers = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current and 'writer_name' in current:
                writers.append(current)
                current = {}
            continue
        m = _vssadmin_WRITER_NAME_RE.match(stripped)
        if m:
            current['writer_name'] = m.group(1).strip()
            continue
        m = _vssadmin_WRITER_ID_RE.match(stripped)
        if m:
            current['writer_id'] = '{' + m.group(1).strip() + '}'
            continue
        m = _vssadmin_WRITER_STATE_RE.match(stripped)
        if m:
            current['writer_state'] = m.group(1).strip()
            continue
    if current and 'writer_name' in current:
        writers.append(current)
    return writers

def _vssadmin__validate_flag_value(name, value, pattern=None):
    """Reject vssadmin flag values that could smuggle extra args or are malformed."""
    if any((ch.isspace() for ch in value)) or '/' in value:
        return (jsonify({'error': f"Invalid {name}: must not contain whitespace or '/'"}), 400)
    if pattern is not None and (not pattern.match(value)):
        return (jsonify({'error': f'Invalid {name} format'}), 400)
    return None

def _vssadmin__parse_storage(output):
    """Parse List ShadowStorage output into structured list."""
    storage_entries = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                storage_entries.append(current)
                current = {}
            continue
        m = _vssadmin_STORAGE_USED_RE.match(stripped)
        if m:
            current['used_space'] = m.group(1).strip()
            continue
        m = _vssadmin_STORAGE_ALLOC_RE.match(stripped)
        if m:
            current['allocated_space'] = m.group(1).strip()
            continue
        m = _vssadmin_STORAGE_LIMIT_RE.match(stripped)
        if m:
            current['max_space'] = m.group(1).strip()
            continue
        m = _vssadmin_VOLUME_PATH_RE.match(stripped)
        if m:
            current['volume_path'] = m.group(1).strip()
            continue
        m = _vssadmin_VOLUME_NAME_RE.match(stripped)
        if m:
            current['volume_name'] = m.group(1).strip()
            continue
        if current and ':' in stripped:
            parts = stripped.split(':', 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                current[key] = val
    if current:
        storage_entries.append(current)
    return storage_entries

def _h_vssadmin_235():
    """List all existing volume shadow copies."""
    try:
        output = _vssadmin__run_vssadmin(['list', 'shadows'], timeout=15)
        copies = _vssadmin__parse_shadow_copies(output)
        raw = output
        return jsonify({'ok': True, 'shadows': copies, 'count': len(copies), 'raw': raw})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_vssadmin_236():
    """Delete volume shadow copies. Optionally specify volume and shadow copy ID."""
    body = _json_body()
    if not isinstance(body, dict):
        return _missing_field('body')
    try:
        args = ['delete', 'shadows']
        vol = str(body.get('volume') or '').strip()
        shadow_id = str(body.get('shadow_id') or '').strip()
        if shadow_id:
            err = _vssadmin__validate_flag_value('shadow_id', shadow_id, _vssadmin_SHADOW_ID_PATTERN)
            if err:
                return err
            args.extend([f'/Shadow={shadow_id}'])
        elif vol:
            err = _vssadmin__validate_flag_value('volume', vol)
            if err:
                return err
            args.extend([f'/For={vol}'])
        elif body.get('all') is True:
            args.append('/All')
        else:
            return (jsonify({'error': 'Missing required field: volume or shadow_id (or set all=true to delete all shadow copies)'}), 400)
        args.append('/Quiet')
        output = _vssadmin__run_vssadmin(args, timeout=30)
        return jsonify({'ok': True, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_vssadmin_237():
    """List registered volume shadow copy providers."""
    try:
        output = _vssadmin__run_vssadmin(['list', 'providers'], timeout=15)
        providers = _vssadmin__parse_providers(output)
        return jsonify({'ok': True, 'providers': providers, 'count': len(providers), 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_vssadmin_238():
    """List volume shadow copy storage associations."""
    try:
        output = _vssadmin__run_vssadmin(['list', 'shadowstorage'], timeout=15)
        storage_entries = _vssadmin__parse_storage(output)
        return jsonify({'ok': True, 'storage': storage_entries, 'count': len(storage_entries), 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_vssadmin_239():
    """List volumes eligible for shadow copies."""
    try:
        output = _vssadmin__run_vssadmin(['list', 'volumes'], timeout=15)
        volumes = _vssadmin__parse_volumes(output)
        return jsonify({'ok': True, 'volumes': volumes, 'count': len(volumes), 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_vssadmin_240():
    """List subscribed volume shadow copy writers with their state."""
    try:
        output = _vssadmin__run_vssadmin(['list', 'writers'], timeout=15)
        writers = _vssadmin__parse_writers(output)
        return jsonify({'ok': True, 'writers': writers, 'count': len(writers), 'raw': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_vssadmin_241():
    """Resize shadow copy storage for a volume."""
    body = _json_body()
    if not isinstance(body, dict):
        return _missing_field('body')
    volume = str(body.get('volume') or '').strip()
    if not volume:
        return _missing_field('volume')
    err = _vssadmin__validate_flag_value('volume', volume)
    if err:
        return err
    max_size = str(body.get('max_size') or '').strip()
    if not max_size:
        return _missing_field('max_size')
    err = _vssadmin__validate_flag_value('max_size', max_size, _vssadmin_MAX_SIZE_PATTERN)
    if err:
        return err
    try:
        output = _vssadmin__run_vssadmin(['resize', 'shadowstorage', f'/For={volume}', f'/On={volume}', f'/MaxSize={max_size}'], timeout=30)
        return jsonify({'ok': True, 'volume': volume, 'max_size': max_size, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _wevtutil__run_wevtutil(args, timeout=30):
    """Run wevtutil.exe with given args, return output or raise."""
    exe = _find_tool('wevtutil')
    if not exe:
        raise RuntimeError('wevtutil.exe not found on system')
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('wevtutil operation timed out')
    except OSError as e:
        raise RuntimeError(f'wevtutil execution failed: {e}')
    if result.returncode != 0:
        stderr = (result.stderr or '').strip()
        raise RuntimeError(stderr or 'wevtutil returned non-zero exit code')
    return result.stdout

def _wevtutil__parse_log_lines(output):
    """Parse wevtutil output lines into a list of strings."""
    return [l.rstrip() for l in output.splitlines() if l.rstrip()]

def _h_wevtutil_242():
    """List all available event logs with metadata."""
    try:
        output = _wevtutil__run_wevtutil(['el'], timeout=15)
        logs = _wevtutil__parse_log_lines(output)
        return jsonify({'ok': True, 'logs': logs, 'count': len(logs)})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_wevtutil_243():
    """Get metadata for a specific event log (path, max size, retention, etc.)."""
    body = _json_body()
    logname = str(body.get('log') or '').strip()
    if not logname:
        return _missing_field('log')
    try:
        output = _wevtutil__run_wevtutil(['gl', logname], timeout=15)
        return jsonify({'ok': True, 'log': logname, 'metadata': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'log': logname, 'error': str(e)}), 503)

def _h_wevtutil_244():
    """Query events from a log with optional filters."""
    body = _json_body()
    logname = str(body.get('log') or '').strip()
    if not logname:
        return _missing_field('log')
    xpath = str(body.get('xpath') or '').strip()
    try:
        max_events = int(body.get('max_events', 50))
    except (TypeError, ValueError):
        return (jsonify({'ok': False, 'error': 'max_events must be an integer'}), 400)
    if max_events < 1:
        max_events = 50
    if max_events > 500:
        max_events = 500
    try:
        args = ['qe', logname, f'/count:{max_events}', '/f:text']
        if xpath:
            args.append('/q:' + xpath)
        output = _wevtutil__run_wevtutil(args, timeout=30)
        events = _wevtutil__parse_log_lines(output)
        return jsonify({'ok': True, 'log': logname, 'events': events, 'count': len(events), 'max_events': max_events})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'log': logname, 'error': str(e)}), 503)

def _h_wevtutil_245():
    """Export event log to an evtx file."""
    body = _json_body()
    logname = str(body.get('log') or '').strip()
    export_path = str(body.get('path') or '').strip()
    if not logname:
        return _missing_field('log')
    if not export_path:
        return _missing_field('path')
    if len(export_path) > 260:
        return (jsonify({'ok': False, 'error': 'Export path too long (max 260 chars)'}), 400)
    try:
        output = _wevtutil__run_wevtutil(['epl', logname, export_path], timeout=60)
        return jsonify({'ok': True, 'log': logname, 'export_path': export_path, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'log': logname, 'error': str(e)}), 503)

def _h_wevtutil_246():
    """Clear all events from a log (and optionally save backup)."""
    body = _json_body()
    logname = str(body.get('log') or '').strip()
    if not logname:
        return _missing_field('log')
    backup_path = str(body.get('backup') or '').strip()
    try:
        args = ['cl', logname]
        if backup_path:
            args += [f'/bu:{backup_path}']
        output = _wevtutil__run_wevtutil(args, timeout=30)
        return jsonify({'ok': True, 'log': logname, 'backup': backup_path if backup_path else None, 'output': output})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'log': logname, 'error': str(e)}), 503)

def _h_wevtutil_247():
    """List all event log publishers/providers."""
    try:
        output = _wevtutil__run_wevtutil(['ep'], timeout=15)
        publishers = _wevtutil__parse_log_lines(output)
        return jsonify({'ok': True, 'publishers': publishers, 'count': len(publishers)})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_wevtutil_248():
    """List configured event subscriptions."""
    try:
        output = _wevtutil__run_wevtutil(['es'], timeout=15)
        subs = _wevtutil__parse_log_lines(output)
        return jsonify({'ok': True, 'subscriptions': subs, 'count': len(subs)})
    except RuntimeError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_wevtutil_249():
    """Archive a log: export to evtx then optionally clear the original."""
    body = _json_body()
    logname = str(body.get('log') or '').strip()
    archive_path = str(body.get('path') or '').strip()
    clear_after = body.get('clear', False)
    if not logname:
        return _missing_field('log')
    if not archive_path:
        return _missing_field('path')
    try:
        export_output = _wevtutil__run_wevtutil(['epl', logname, archive_path], timeout=60)
        result = {'ok': True, 'log': logname, 'archive_path': archive_path}
        if clear_after:
            clear_output = _wevtutil__run_wevtutil(['cl', logname], timeout=30)
            result['cleared'] = True
        return jsonify(result)
    except RuntimeError as e:
        return (jsonify({'ok': False, 'log': logname, 'error': str(e)}), 503)

def _win11debloat__run_win11debloat_script(params, timeout=120):
    """Run Win11Debloat with given parameters via PowerShell.

    Returns (stdout, stderr, exit_code).
    """
    ps = _win11debloat__get_powershell_path()
    script = _find_tool('win11debloat')
    if not script:
        command_str = "& { [scriptblock]::Create((irm 'https://debloat.raphi.re/')) }"
        if params:
            command_str += ' ' + ' '.join(params)
        cmd = [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command_str]
    else:
        cmd = [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script]
        if params:
            cmd += params
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (result.stdout, result.stderr, result.returncode)

def _win11debloat__get_powershell_path():
    """Get path to Windows PowerShell 5.1."""
    exe = shutil.which('powershell.exe')
    if exe:
        return exe
    default = 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe'
    if os.path.isfile(default):
        return default
    return 'powershell.exe'

def _win11debloat__param(flag):
    """Convert parameter name to PowerShell switch flag."""
    return f'-{flag}'

def _h_win11debloat_250():
    """Run Win11Debloat in Default mode — quickly apply recommended changes."""
    try:
        body = _json_body()
    except Exception:
        body = {}
    confirm = body.get('confirm', False)
    if not confirm:
        return (jsonify({'ok': False, 'error': "Confirmation required — set 'confirm: true' to proceed. This modifies Windows settings, removes apps, and changes registry."}), 400)
    ps = _win11debloat__get_powershell_path()
    if not os.path.isfile(ps):
        return (jsonify({'ok': False, 'error': 'PowerShell 5.1 not found on system'}), 503)
    try:
        result_stdout, result_stderr, rc = _win11debloat__run_win11debloat_script([_win11debloat__param('RunDefaults'), _win11debloat__param('Silent')], timeout=180)
        if rc != 0 and 'already ran as' not in result_stderr.lower():
            return (jsonify({'ok': False, 'error': result_stderr.strip() or 'Win11Debloat run failed', 'exit_code': rc}), 502)
        return jsonify({'ok': True, 'exit_code': rc, 'output': result_stdout.strip()[:2000]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'Win11Debloat timed out (180s)'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_win11debloat_251():
    """Run Win11Debloat with custom parameters.

        Body: { "confirm": true, "params": ["-RemoveApps", "-DisableTelemetry", ...] }
        """
    body = _json_body()
    confirm = body.get('confirm', False)
    if not confirm:
        return (jsonify({'ok': False, 'error': "Confirmation required — set 'confirm: true' to proceed."}), 400)
    params = body.get('params', [])
    if not params:
        return _missing_field('params')
    if not isinstance(params, list):
        return (jsonify({'ok': False, 'error': 'params must be a list of strings'}), 400)
    allowed_prefixes = ['-RunDefaults', '-RunDefaultsLite', '-RemoveApps', '-RemoveGamingApps', '-RemoveHPApps', '-ForceRemoveEdge', '-DisableDVR', '-DisableGameBarIntegration', '-EnableWindowsSandbox', '-EnableWindowsSubsystemForLinux', '-DisableTelemetry', '-DisableSearchHistory', '-DisableFastStartup', '-DisableBitlockerAutoEncryption', '-DisableModernStandbyNetworking', '-DisableStorageSense', '-DisableUpdateASAP', '-PreventUpdateAutoReboot', '-DisableDeliveryOptimization', '-DisableDeviceAutoAppDownload', '-DisableBing', '-DisableNotifications', '-DisableStoreSearchSuggestions', '-DisableSearchHighlights', '-DisableDesktopSpotlight', '-DisableLockscreenTips', '-DisableSuggestions', '-DisableLocationServices', '-DisableFindMyDevice', '-DisableEdgeAds', '-DisableBraveBloat', '-DisableSettings365Ads', '-DisableSettingsHome', '-ShowHiddenFolders', '-ShowKnownFileExt', '-HideDupliDrive', '-EnableDarkMode', '-DisableTransparency', '-DisableAnimations', '-TaskbarAlignLeft', '-CombineTaskbarAlways', '-CombineTaskbarWhenFull', '-CombineTaskbarNever', '-HideSearchTb', '-ShowSearchIconTb', '-ShowSearchLabelTb', '-ShowSearchBoxTb', '-HideTaskview', '-DisableStartRecommended', '-DisableStartAllApps', '-StartAllAppsCategory', '-DisableStartPhoneLink', '-DisableCopilot', '-DisableRecall', '-DisableClickToDo', '-DisableAISvcAutoStart', '-DisablePaintAI', '-DisableNotepadAI', '-DisableEdgeAI', '-DisableWidgets', '-HideChat', '-EnableEndTask', '-EnableLastActiveClick', '-ClearStart', '-ReplaceStart', '-RevertContextMenu', '-DisableDragTray', '-DisableMouseAcceleration', '-DisableStickyKeys', '-DisableWindowSnapping', '-DisableSnapAssist', '-DisableSnapLayouts', '-HideHome', '-HideGallery', '-ExplorerToHome', '-ExplorerToThisPC', '-ExplorerToDownloads', '-HideOnedrive', '-Hide3dObjects', '-HideMusic', '-HideShare', '-ShowDriveLettersFirst', '-ShowDriveLettersLast', '-HideDriveLetters', '-Silent', '-LogPath']
    sanitized = []
    for p in params:
        p_str = str(p)
        is_allowed = any((p_str.startswith(prefix) for prefix in allowed_prefixes))
        if p_str.startswith('-Apps ') or p_str.startswith('-Apps\t'):
            is_allowed = True
        if p_str.startswith('-Config ') or p_str.startswith('-Config\t'):
            is_allowed = True
        if not is_allowed:
            return (jsonify({'ok': False, 'error': f"Parameter '{p_str}' is not in the allowed list"}), 400)
        sanitized.append(p_str)
    try:
        stdout, stderr, rc = _win11debloat__run_win11debloat_script(sanitized, timeout=180)
        return jsonify({'ok': rc == 0, 'exit_code': rc, 'output': stdout.strip()[:2000], 'stderr': stderr.strip()[:500]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'Win11Debloat timed out (180s)'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_win11debloat_252():
    """Check what Win11Debloat would do (dry-run / whatif mode)."""
    ps = _win11debloat__get_powershell_path()
    if not os.path.isfile(ps):
        return (jsonify({'ok': False, 'error': 'PowerShell 5.1 not found'}), 503)
    script = _find_tool('win11debloat')
    if not script:
        try:
            import urllib.request
            req = urllib.request.Request('https://debloat.raphi.re/', method='HEAD')
            resp = urllib.request.urlopen(req, timeout=10)
            return jsonify({'ok': True, 'script_installed': False, 'download_available': True, 'note': 'Win11Debloat is not downloaded but can be fetched on-demand via iex (irm ...)'})
        except Exception:
            return jsonify({'ok': True, 'script_installed': False, 'download_available': False, 'note': 'Win11Debloat not found and download URL unreachable'})
    stat = os.stat(script)
    import datetime
    mtime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
    try:
        ver_result = subprocess.run([ps, '-NoProfile', '-Command', "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion').ProductName"], capture_output=True, text=True, timeout=10)
        win_ver = ver_result.stdout.strip() if ver_result.returncode == 0 else 'unknown'
    except Exception:
        win_ver = 'unknown'
    return jsonify({'ok': True, 'script_installed': True, 'script_path': script, 'script_size_bytes': stat.st_size, 'last_modified': mtime, 'windows_version': win_ver, 'general_info': 'Run /auto/win11debloat/run-defaults for recommended changes'})

_windows_mcp__SERVER_PROCESS = None

_windows_mcp__DEFAULT_PORT = 8124

def _windows_mcp__get_mcp_server_url(port):
    return f'http://127.0.0.1:{port}/mcp'

def _windows_mcp__mcp_request(port, method, params=None):
    """Send a JSON-RPC request to the Windows-MCP SSE server."""
    url = _windows_mcp__get_mcp_server_url(port)
    body = json.dumps({'jsonrpc': '2.0', 'id': int(time.time() * 1000) % 1000000, 'method': method, 'params': params or {}}).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode('utf-8', errors='replace')[:500]
        return {'error': {'message': f'HTTP {exc.code}: {body_text}'}}
    except urllib.error.URLError as exc:
        return {'error': {'message': f'Connection failed: {exc.reason}'}}
    except (json.JSONDecodeError, OSError) as exc:
        return {'error': {'message': str(exc)}}

def _windows_mcp__is_windows_mcp_installed():
    """Check if Windows-MCP is available (pip-installed package or uvx)."""
    exe = _find_tool('windows_mcp')
    if exe:
        try:
            result = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
    uvx = shutil.which('uvx')
    if uvx:
        try:
            result = subprocess.run([uvx, 'windows-mcp', '--version'], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
    return False

def _windows_mcp__ping_mcp_server(port=_windows_mcp__DEFAULT_PORT):
    """Try to ping the MCP server by sending a lightweight request."""
    result = _windows_mcp__mcp_request(port, 'ping')
    return result.get('result') == 'pong' or 'result' in result

def _h_windows_mcp_253():
    global _windows_mcp__SERVER_PROCESS
    if _windows_mcp__SERVER_PROCESS and _windows_mcp__SERVER_PROCESS.poll() is None:
        return jsonify({'ok': True, 'message': 'Server is already running', 'pid': _windows_mcp__SERVER_PROCESS.pid})
    if not _windows_mcp__is_windows_mcp_installed():
        return (jsonify({'ok': False, 'error': 'Windows-MCP not installed', 'hint': 'Install via: pip install windows-mcp'}), 503)
    data = _json_body()
    port = _windows_mcp__DEFAULT_PORT
    if data:
        try:
            port = max(1024, min(int(data.get('port', _windows_mcp__DEFAULT_PORT)), 65535))
        except (TypeError, ValueError):
            port = _windows_mcp__DEFAULT_PORT
    exe = _find_tool('windows_mcp')
    if exe:
        cmd = [exe, 'serve', '--transport', 'sse', '--host', '127.0.0.1', '--port', str(port)]
    else:
        uvx = shutil.which('uvx')
        if not uvx:
            return (jsonify({'ok': False, 'error': 'Neither windows-mcp nor uvx found on PATH'}), 503)
        cmd = [uvx, 'windows-mcp', 'serve', '--transport', 'sse', '--host', '127.0.0.1', '--port', str(port)]
    try:
        _windows_mcp__SERVER_PROCESS = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
    except OSError as exc:
        _log(f'[windows_mcp] server start failed: {exc}')
        return (jsonify({'ok': False, 'error': str(exc)}), 500)
    time.sleep(1.5)
    running = _windows_mcp__SERVER_PROCESS.poll() is None
    _log(f'[windows_mcp] server start pid={_windows_mcp__SERVER_PROCESS.pid} running={running}')
    return jsonify({'ok': running, 'pid': _windows_mcp__SERVER_PROCESS.pid if running else None, 'port': port, 'server_url': _windows_mcp__get_mcp_server_url(port), 'message': 'Server started' if running else 'Server failed to start'})

def _h_windows_mcp_254():
    global _windows_mcp__SERVER_PROCESS
    if not _windows_mcp__SERVER_PROCESS or _windows_mcp__SERVER_PROCESS.poll() is not None:
        return jsonify({'ok': True, 'message': 'No running server to stop'})
    try:
        _windows_mcp__SERVER_PROCESS.terminate()
        _windows_mcp__SERVER_PROCESS.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _windows_mcp__SERVER_PROCESS.kill()
        try:
            _windows_mcp__SERVER_PROCESS.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    except OSError as exc:
        _log(f'[windows_mcp] server stop failed: {exc}')
    _log(f'[windows_mcp] server stopped (was pid={_windows_mcp__SERVER_PROCESS.pid})')
    _windows_mcp__SERVER_PROCESS = None
    return jsonify({'ok': True, 'message': 'Server stopped'})

def _h_windows_mcp_255():
    data = _json_body()
    missing = _missing_field(data, 'tool')
    if missing:
        return missing
    tool = str(data.get('tool', '')).strip()
    if not tool:
        return (jsonify({'ok': False, 'error': 'tool must not be empty'}), 400)
    params = data.get('params', {})
    if not isinstance(params, dict):
        return (jsonify({'ok': False, 'error': 'params must be a dict'}), 400)
    port = _windows_mcp__DEFAULT_PORT
    try:
        port = max(1024, min(int(data.get('port', _windows_mcp__DEFAULT_PORT)), 65535))
    except (TypeError, ValueError):
        port = _windows_mcp__DEFAULT_PORT
    if not _windows_mcp__ping_mcp_server(port):
        return (jsonify({'ok': False, 'error': 'Windows-MCP server is not running on port ' + str(port), 'hint': 'Start it via /auto/windows_mcp/server/start first'}), 503)
    result = _windows_mcp__mcp_request(port, 'tools/call', {'name': tool, 'arguments': params})
    if 'error' in result:
        _log(f"[windows_mcp] tool={tool} error={result['error']}")
        return (jsonify({'ok': False, 'error': result['error'].get('message', str(result['error']))}), 502)
    _log(f'[windows_mcp] tool={tool} ok')
    return jsonify({'ok': True, 'tool': tool, 'result': result.get('result')})

def _h_windows_mcp_256():
    """List available tools from the Windows-MCP server."""
    port = _windows_mcp__DEFAULT_PORT
    try:
        port = max(1024, min(int(request.args.get('port', _windows_mcp__DEFAULT_PORT, type=int)), 65535))
    except (TypeError, ValueError):
        port = _windows_mcp__DEFAULT_PORT
    if not _windows_mcp__ping_mcp_server(port):
        return (jsonify({'ok': False, 'error': f'Windows-MCP server not running on port {port}'}), 503)
    result = _windows_mcp__mcp_request(port, 'tools/list')
    if 'error' in result:
        return (jsonify({'ok': False, 'error': result['error'].get('message', str(result['error']))}), 502)
    tools = result.get('result', {}).get('tools', [])
    return jsonify({'ok': True, 'count': len(tools), 'tools': [{'name': t.get('name'), 'description': t.get('description', '')[:120]} for t in tools]})

def _h_windows_mcp_257():
    """Take a screenshot using Windows-MCP's Screenshot tool."""
    port = _windows_mcp__DEFAULT_PORT
    try:
        port = max(1024, min(int(request.args.get('port', _windows_mcp__DEFAULT_PORT, type=int)), 65535))
    except (TypeError, ValueError):
        port = _windows_mcp__DEFAULT_PORT
    display = request.args.get('display', '0')
    try:
        display = int(display)
    except (TypeError, ValueError):
        display = 0
    if not _windows_mcp__ping_mcp_server(port):
        return (jsonify({'ok': False, 'error': f'Windows-MCP server not running on port {port}', 'hint': 'Start it via /auto/windows_mcp/server/start first'}), 503)
    result = _windows_mcp__mcp_request(port, 'tools/call', {'name': 'Screenshot', 'arguments': {'display': [display]}})
    if 'error' in result:
        _log(f"[windows_mcp] screenshot error={result['error']}")
        return (jsonify({'ok': False, 'error': result['error'].get('message', str(result['error']))}), 502)
    _log('[windows_mcp] screenshot taken')
    return jsonify({'ok': True, 'result': result.get('result')})

def _winget_cli__clean_package_id(value):
    """Validate and sanitize a winget package identifier."""
    pid = str(value or '').strip()
    if not pid:
        raise ValueError('package identifier must not be empty')
    if len(pid) > 256:
        raise ValueError('package identifier too long (max 256 chars)')
    if '\x00' in pid:
        raise ValueError('package identifier cannot contain null bytes')
    forbidden = set('<>"|?*')
    if any((c in pid for c in forbidden)):
        raise ValueError(f'package identifier contains forbidden characters: {forbidden & set(pid)}')
    return pid

def _winget_cli__clean_query(value):
    """Validate a search query string."""
    q = str(value or '').strip()
    if not q:
        raise ValueError('query must not be empty')
    if len(q) > 200:
        raise ValueError('query too long (max 200 chars)')
    if '\x00' in q:
        raise ValueError('query cannot contain null bytes')
    return q

def _winget_cli__find_winget():
    """Locate winget.exe — typically in WindowsApps or system32."""
    exe = shutil.which('winget') or shutil.which('winget.exe')
    if exe:
        return exe
    for p in [os.path.expandvars('%LOCALAPPDATA%\\Microsoft\\WindowsApps\\winget.exe'), 'C:\\Windows\\system32\\winget.exe']:
        if os.path.isfile(p):
            return p
    return None

def _h_winget_cli_258():
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    query = body.get('query', '')
    try:
        query = _winget_cli__clean_query(query)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _winget_cli__find_winget()
    if not exe:
        return (jsonify({'ok': False, 'error': 'winget not found'}), 503)
    try:
        result = subprocess.run([exe, 'search', query, '--accept-source-agreements'], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'search failed'}), 502)
        lines = result.stdout.strip().split('\n')
        packages = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('Name') or line.startswith('---'):
                continue
            parts = [p.strip() for p in line.split() if p.strip()]
            if parts:
                packages.append({'name': parts[0] if len(parts) > 0 else '', 'id': parts[1] if len(parts) > 1 else parts[0], 'version': parts[2] if len(parts) > 2 else '', 'source': parts[3] if len(parts) > 3 else 'winget'})
        return jsonify({'ok': True, 'query': query, 'count': len(packages), 'packages': packages, 'raw_output': result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'winget search timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_winget_cli_259():
    exe = _winget_cli__find_winget()
    if not exe:
        return (jsonify({'ok': False, 'error': 'winget not found'}), 503)
    try:
        result = subprocess.run([exe, 'list', '--accept-source-agreements'], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'list failed'}), 502)
        lines = result.stdout.strip().split('\n')
        packages = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('Name') or line.startswith('---'):
                continue
            parts = [p.strip() for p in line.split() if p.strip()]
            if parts:
                packages.append({'name': parts[0] if len(parts) > 0 else '', 'id': parts[1] if len(parts) > 1 else parts[0], 'version': parts[2] if len(parts) > 2 else '', 'available': parts[3] if len(parts) > 3 else ''})
        return jsonify({'ok': True, 'count': len(packages), 'packages': packages})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'winget list timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_winget_cli_260():
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    package_id = body.get('package_id', '')
    try:
        package_id = _winget_cli__clean_package_id(package_id)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _winget_cli__find_winget()
    if not exe:
        return (jsonify({'ok': False, 'error': 'winget not found'}), 503)
    silent = body.get('silent', True)
    try:
        cmd = [exe, 'install', '--exact', '--id', package_id, '--accept-source-agreements', '--accept-package-agreements']
        if silent:
            cmd.append('--silent')
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return jsonify({'ok': result.returncode == 0, 'package_id': package_id, 'exit_code': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'winget install timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_winget_cli_261():
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    package_id = body.get('package_id', '')
    upgrade_all = body.get('all', False) is True
    try:
        package_id = _winget_cli__clean_package_id(package_id) if package_id else None
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    if not package_id and (not upgrade_all):
        return (jsonify({'ok': False, 'error': 'package_id is required (or set "all": true to upgrade every package)'}), 400)
    exe = _winget_cli__find_winget()
    if not exe:
        return (jsonify({'ok': False, 'error': 'winget not found'}), 503)
    try:
        cmd = [exe, 'upgrade', '--accept-source-agreements', '--accept-package-agreements']
        if package_id:
            cmd.extend(['--id', package_id])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return jsonify({'ok': result.returncode == 0, 'package_id': package_id or 'all', 'exit_code': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'winget upgrade timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_winget_cli_262():
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    package_id = body.get('package_id', '')
    try:
        package_id = _winget_cli__clean_package_id(package_id)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _winget_cli__find_winget()
    if not exe:
        return (jsonify({'ok': False, 'error': 'winget not found'}), 503)
    try:
        result = subprocess.run([exe, 'show', '--id', package_id, '--accept-source-agreements'], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or f"package '{package_id}' not found"}), 404)
        return jsonify({'ok': True, 'package_id': package_id, 'details': result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'winget show timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_winget_cli_263():
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    package_id = body.get('package_id', '')
    try:
        package_id = _winget_cli__clean_package_id(package_id)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _winget_cli__find_winget()
    if not exe:
        return (jsonify({'ok': False, 'error': 'winget not found'}), 503)
    try:
        result = subprocess.run([exe, 'uninstall', '--id', package_id, '--accept-source-agreements'], capture_output=True, text=True, timeout=60)
        return jsonify({'ok': result.returncode == 0, 'package_id': package_id, 'exit_code': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'winget uninstall timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

_xh__ALLOWED_METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}

def _xh__redact_url(url):
    """Strip credentials and query values from a URL for safe logging."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return '<invalid-url>'
    host = p.hostname or ''
    if p.username or p.password:
        host = '***:***@' + host
    query = ''
    if p.query:
        query = '?' + '&'.join((f'{k}=***' for k, _ in urllib.parse.parse_qsl(p.query, keep_blank_values=True)))
    return f'{p.scheme}://{host}{p.path}{query}'

def _xh__validate_url(url):
    """Validate an outgoing request URL for the xh client.

    Returns an error string on failure, or None if the URL is acceptable.
    Guards against argument injection (leading '-'), non-http schemes, and
    SSRF (loopback / link-local / private / multicast / unspecified targets,
    including DNS-rebinding where the hostname resolves to a blocked address).
    """
    if not isinstance(url, str):
        return 'url must be a string'
    url = url.strip()
    if not url:
        return 'url is required'
    if url.startswith('-'):
        return "url must not start with '-'"
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return 'invalid URL'
    if parsed.scheme.lower() not in ('http', 'https'):
        return 'only http/https URLs are allowed'
    host = parsed.hostname
    if not host:
        return 'URL has no hostname'
    host_l = host.lower().rstrip('.')
    if host_l in {'localhost', 'metadata', 'metadata.google.internal', '0.0.0.0'}:
        return 'host is blocked'
    try:
        ip = ipaddress.ip_address(host_l)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return None
        for info in infos:
            addr = info[4][0]
            try:
                a = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if _xh__is_blocked_ip(a):
                return f'host {host!r} resolves to a blocked address'
        return None
    if _xh__is_blocked_ip(ip):
        return 'IP address is blocked'
    return None

def _xh__is_blocked_ip(ip):
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified

def _xh__serialize_body(req_body):
    """Serialize a request body for xh's stdin.

    dict/list become JSON (matching the documented behaviour), everything else
    is passed through as a string. None means no body at all.
    """
    if req_body is None:
        return None
    if isinstance(req_body, (dict, list)):
        return json.dumps(req_body)
    return str(req_body)

def _xh__parse_xh_output(raw):
    """Parse xh's default (piped) output into status, headers, and body."""
    normalized = (raw or '').replace('\r\n', '\n')
    if '\n\n' in normalized:
        head, body = normalized.split('\n\n', 1)
    else:
        head, body = (normalized, '')
    lines = head.split('\n')
    status_code = None
    if lines and lines[0].startswith('HTTP/'):
        parts = lines[0].split()
        if len(parts) >= 2:
            try:
                status_code = int(parts[1])
            except ValueError:
                status_code = None
    headers = {}
    for line in lines[1:]:
        if ':' in line:
            k, v = line.split(':', 1)
            headers[k.strip()] = v.strip()
    return (status_code, headers, body)

def _xh__build_request_items(body):
    """Convert optional dicts into xh request-item tokens.

    Header/query keys and values are sanitised: CR/LF are stripped (they are
    the header-injection / request-smuggling vector) and empty keys are skipped.
    """
    items = []
    for k, v in (body.get('headers') or {}).items():
        key = str(k).replace('\r', '').replace('\n', '').strip()
        val = str(v).replace('\r', '').replace('\n', '')
        if not key:
            continue
        items.append(f'{key}:{val}')
    for k, v in (body.get('query') or {}).items():
        key = str(k).replace('\r', '').replace('\n', '').strip()
        val = str(v).replace('\r', '').replace('\n', '')
        if not key:
            continue
        items.append(f'{key}=={val}')
    return items

def _h_xh_264():
    """Send an HTTP request.

        Body:
          url:      string (required)
          method:   string (default "GET")
          headers:  dict — request headers (e.g. {"Authorization": "Bearer ..."})
          query:    dict — query-string params
          body:     string — request body (sent via stdin; JSON if content-type set)
          timeout:  int seconds (default 30, max 120)
          follow:   bool — follow redirects (default true)
          verify:   bool — verify TLS certs (default true)
          headers_only: bool — return only response headers
        """
    body = _json_body()
    missing = _missing_field(body, 'url')
    if missing:
        return missing
    url = body['url']
    url_err = _xh__validate_url(url)
    if url_err:
        return (jsonify({'error': f'Invalid url: {url_err}'}), 400)
    url = url.strip()
    method = str(body.get('method', 'GET')).upper()
    if method not in _xh__ALLOWED_METHODS:
        return (jsonify({'error': f'Unsupported method: {method}'}), 400)
    timeout = body.get('timeout', 30)
    follow = bool(body.get('follow', True))
    verify = bool(body.get('verify', True))
    headers_only = bool(body.get('headers_only', False))
    req_body = body.get('body')
    try:
        timeout = int(timeout)
    except (ValueError, TypeError):
        return (jsonify({'error': f"Invalid timeout: {body.get('timeout')}"}), 400)
    timeout = max(5, min(timeout, 120))
    exe = _find_tool('xh')
    if not exe:
        return (jsonify({'error': 'xh not installed', 'hint': 'Install with: winget install ducaale.xh'}), 503)
    cmd = [exe, method, url, '--timeout', str(timeout)]
    if follow:
        cmd.append('--follow')
    if not verify:
        cmd.append('--verify')
        cmd.append('no')
    if headers_only:
        cmd.append('--headers')
    cmd.extend(_xh__build_request_items(body))
    if req_body is None:
        cmd.append('--ignore-stdin')
    _log(f'xh_request: {method} {_xh__redact_url(url)}')
    try:
        start = time.time()
        r = subprocess.run(cmd, input=_xh__serialize_body(req_body), capture_output=True, text=True, timeout=timeout + 10)
        elapsed_ms = int((time.time() - start) * 1000)
        status_code, headers, parsed_body = _xh__parse_xh_output(r.stdout)
        result = {'method': method, 'url': url, 'exit_code': r.returncode, 'elapsed_ms': elapsed_ms, 'success': r.returncode == 0}
        if headers_only:
            status_code, headers, _ = _xh__parse_xh_output(r.stdout + '\n\n')
            result['status_code'] = status_code
            result['headers'] = headers
            result['raw_output'] = r.stdout.strip()
        else:
            result['status_code'] = status_code
            result['headers'] = headers
            result['body'] = parsed_body
            result['raw_output'] = r.stdout.strip()
        if r.stderr:
            result['stderr'] = r.stderr.strip()
        return jsonify(result)
    except subprocess.TimeoutExpired:
        _log(f'xh_request: timed out ({timeout}s): {method} {_xh__redact_url(url)}')
        return (jsonify({'error': f'xh timed out after {timeout}s', 'method': method, 'url': url, 'success': False}), 504)
    except Exception as e:
        _log(f'xh_request: Error: {e}')
        return (jsonify({'error': str(e), 'method': method, 'url': url, 'success': False}), 500)

def _h_xh_265():
    """Fetch only the response headers for a URL. Query: ?url=<url>&follow=1"""
    url = request.args.get('url', '')
    if not url:
        return (jsonify({'error': 'Provide ?url=<url>'}), 400)
    url_err = _xh__validate_url(url)
    if url_err:
        return (jsonify({'error': f'Invalid url: {url_err}'}), 400)
    url = url.strip()
    follow = request.args.get('follow', '1') in ('1', 'true', 'yes')
    timeout = request.args.get('timeout', '30')
    try:
        timeout = int(timeout)
    except ValueError:
        return (jsonify({'error': f'Invalid timeout: {timeout}'}), 400)
    timeout = max(5, min(timeout, 120))
    exe = _find_tool('xh')
    if not exe:
        return (jsonify({'error': 'xh not installed', 'hint': 'Install with: winget install ducaale.xh'}), 503)
    cmd = [exe, 'GET', url, '--headers', '--ignore-stdin', '--timeout', str(timeout)]
    if follow:
        cmd.append('--follow')
    try:
        start = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        elapsed_ms = int((time.time() - start) * 1000)
        status_code, headers, _ = _xh__parse_xh_output(r.stdout + '\n\n')
        return jsonify({'url': url, 'status_code': status_code, 'headers': headers, 'elapsed_ms': elapsed_ms, 'exit_code': r.returncode, 'raw_output': r.stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'xh timed out after {timeout}s', 'url': url}), 504)
    except Exception as e:
        _log(f'xh_headers: Error: {e}')
        return (jsonify({'error': str(e), 'url': url}), 500)

_yq__VALID_FORMATS = {'yaml', 'yml', 'json', 'xml', 'csv', 'tsv', 'toml', 'properties', 'props', 'auto'}

def _yq__normalize_fmt(fmt):
    """Normalize format aliases to yq's canonical names."""
    fmt = (fmt or '').lower()
    if fmt in ('yml',):
        return 'yaml'
    if fmt in ('props',):
        return 'properties'
    return fmt

def _h_yq_266():
    """Run a jq-style expression against structured input.

        Body (JSON):
            expression (str, required): jq-style expression, e.g. ".items[0].name".
            input (str, optional): Raw text to process via stdin.
            path (str, optional): File to read instead of `input`.
            input_format (str, optional): yaml|json|xml|csv|tsv|toml|properties|auto. Default "auto".
            output_format (str, optional): yaml|json|xml|... Default "json".
        """
    body = _json_body()
    expression = body.get('expression')
    if expression in (None, ''):
        return _missing_field(body, 'expression')
    input_text = body.get('input')
    path = body.get('path') or None
    if input_text is None and (not path):
        return (jsonify({'error': "Either 'input' or 'path' is required"}), 400)
    in_fmt = _yq__normalize_fmt(body.get('input_format') or 'auto')
    out_fmt = _yq__normalize_fmt(body.get('output_format') or 'json')
    if in_fmt not in _yq__VALID_FORMATS:
        return (jsonify({'error': f"Unsupported input_format '{in_fmt}'. Choose from {sorted(_yq__VALID_FORMATS)}"}), 400)
    if out_fmt not in _yq__VALID_FORMATS:
        return (jsonify({'error': f"Unsupported output_format '{out_fmt}'. Choose from {sorted(_yq__VALID_FORMATS)}"}), 400)
    exe = _find_tool('yq')
    if not exe:
        return (jsonify({'error': 'yq is not installed', 'hint': 'Install with: winget install mikefarah.yq'}), 503)
    args = ['--input-format', in_fmt, '--output-format', out_fmt, expression]
    if path:
        args.append(path)
    try:
        r = subprocess.run([exe] + args, input=input_text if not path else None, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            _log(f'auto_yq_query: yq exited {r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'yq query failed'}), 500)
        return jsonify({'expression': expression, 'input_format': in_fmt, 'output_format': out_fmt, 'output': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'yq timed out after 60s'}), 504)
    except Exception as e:
        _log(f'auto_yq_query exception: {e}')
        return (jsonify({'error': str(e)}), 500)

def _h_yq_267():
    """Convert structured data between formats.

        Body (JSON):
            input (str, optional): Raw text to convert via stdin.
            path (str, optional): File to read instead of `input`.
            from (str, required): Source format (yaml|json|xml|csv|tsv|toml|properties).
            to (str, required): Target format (yaml|json|xml|csv|tsv|toml|properties).
        """
    body = _json_body()
    input_text = body.get('input')
    path = body.get('path') or None
    if input_text is None and (not path):
        return (jsonify({'error': "Either 'input' or 'path' is required"}), 400)
    src = _yq__normalize_fmt(body.get('from'))
    dst = _yq__normalize_fmt(body.get('to'))
    if src in (None, '', 'auto') or src not in _yq__VALID_FORMATS:
        return (jsonify({'error': f"Invalid 'from' format '{body.get('from')}'. Choose from {sorted(_yq__VALID_FORMATS)}"}), 400)
    if dst in (None, '', 'auto') or dst not in _yq__VALID_FORMATS:
        return (jsonify({'error': f"Invalid 'to' format '{body.get('to')}'. Choose from {sorted(_yq__VALID_FORMATS)}"}), 400)
    exe = _find_tool('yq')
    if not exe:
        return (jsonify({'error': 'yq is not installed', 'hint': 'Install with: winget install mikefarah.yq'}), 503)
    args = ['--input-format', src, '--output-format', dst, '.']
    if path:
        args.append(path)
    try:
        r = subprocess.run([exe] + args, input=input_text if not path else None, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            _log(f'auto_yq_convert: yq exited {r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'yq convert failed'}), 500)
        return jsonify({'from': src, 'to': dst, 'output': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'yq timed out after 60s'}), 504)
    except Exception as e:
        _log(f'auto_yq_convert exception: {e}')
        return (jsonify({'error': str(e)}), 500)

def _yt_dlp__clean_url(value):
    """Validate and sanitize a URL for yt-dlp."""
    url = str(value or '').strip()
    if not url:
        raise ValueError('URL must not be empty')
    if len(url) > 4096:
        raise ValueError('URL too long (max 4096 chars)')
    if '\x00' in url:
        raise ValueError('URL cannot contain null bytes')
    if not re.match('^https?://', url):
        raise ValueError('URL must start with http:// or https://')
    return url

def _yt_dlp__clean_format(value):
    """Validate a youtube-dl format string."""
    fmt = str(value or '').strip()
    if fmt and len(fmt) > 200:
        raise ValueError('format string too long (max 200 chars)')
    return fmt or None

def _yt_dlp__format_duration(seconds):
    """Format duration in seconds to human-readable string."""
    if seconds is None:
        return None
    try:
        secs = int(seconds)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f'{h}h {m}m {s}s'
        elif m > 0:
            return f'{m}m {s}s'
        return f'{s}s'
    except (ValueError, TypeError):
        return str(seconds)

def _h_yt_dlp_268():
    """Get video metadata (title, duration, formats, etc.) without downloading."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    url = body.get('url', '')
    try:
        url = _yt_dlp__clean_url(url)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('yt_dlp')
    if not exe:
        return (jsonify({'ok': False, 'error': 'yt-dlp not found'}), 503)
    try:
        result = subprocess.run([exe, '--dump-json', '--no-download', url], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'failed to get video info'}), 502)
        import json as json_mod
        try:
            info = json_mod.loads(result.stdout.strip().split('\n')[0])
        except json_mod.JSONDecodeError:
            return (jsonify({'ok': False, 'error': 'failed to parse video metadata', 'raw': result.stdout.strip()[:1000]}), 502)
        return jsonify({'ok': True, 'url': url, 'title': info.get('title'), 'duration': info.get('duration'), 'duration_str': _yt_dlp__format_duration(info.get('duration')), 'uploader': info.get('uploader'), 'upload_date': info.get('upload_date'), 'view_count': info.get('view_count'), 'like_count': info.get('like_count'), 'description': (info.get('description') or '')[:500], 'formats_available': len(info.get('formats', [])), 'extractor': info.get('extractor')})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'yt-dlp timed out fetching video info'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_yt_dlp_269():
    """List all available formats for a given URL."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    url = body.get('url', '')
    try:
        url = _yt_dlp__clean_url(url)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('yt_dlp')
    if not exe:
        return (jsonify({'ok': False, 'error': 'yt-dlp not found'}), 503)
    try:
        result = subprocess.run([exe, '-F', url], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return (jsonify({'ok': False, 'error': result.stderr.strip() or 'failed to list formats'}), 502)
        return jsonify({'ok': True, 'url': url, 'formats_raw': result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'yt-dlp timed out listing formats'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_yt_dlp_270():
    """Download a video/audio. Returns command-line output — actual file writes to yt-dlp's configured output dir."""
    try:
        body = _json_body()
    except Exception:
        return (jsonify({'ok': False, 'error': 'invalid JSON body'}), 400)
    url = body.get('url', '')
    try:
        url = _yt_dlp__clean_url(url)
    except ValueError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 400)
    exe = _find_tool('yt_dlp')
    if not exe:
        return (jsonify({'ok': False, 'error': 'yt-dlp not found'}), 503)
    format_str = _yt_dlp__clean_format(body.get('format', ''))
    output_template = body.get('output', '%(title)s.%(ext)s')
    if not isinstance(output_template, str):
        return (jsonify({'ok': False, 'error': 'output template must be a string'}), 400)
    if '..' in output_template or output_template.startswith(('\\', '/')) or ':' in output_template.split('/')[0]:
        return (jsonify({'ok': False, 'error': 'output template must not contain path traversal or absolute paths'}), 400)
    extract_audio = body.get('extract_audio', False)
    playlist_start = body.get('playlist_start')
    playlist_end = body.get('playlist_end')
    write_subs = body.get('write_subs', False)
    sub_langs = body.get('sub_langs', '')
    cmd = [exe]
    if format_str:
        cmd.extend(['-f', format_str])
    elif extract_audio:
        cmd.extend(['-x', '--audio-format', body.get('audio_format', 'mp3')])
    cmd.extend(['-o', output_template])
    if write_subs:
        cmd.append('--write-subs')
        if sub_langs:
            cmd.extend(['--sub-langs', sub_langs])
    if playlist_start:
        cmd.extend(['--playlist-start', str(playlist_start)])
    if playlist_end:
        cmd.extend(['--playlist-end', str(playlist_end)])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return jsonify({'ok': result.returncode == 0, 'url': url, 'format': format_str or 'best', 'exit_code': result.returncode, 'stdout': result.stdout.strip()[-2000:], 'stderr': result.stderr.strip()[-1000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'yt-dlp download timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_yt_dlp_271():
    """Update yt-dlp to the latest version."""
    exe = _find_tool('yt_dlp')
    if not exe:
        return (jsonify({'ok': False, 'error': 'yt-dlp not found'}), 503)
    try:
        result = subprocess.run([exe, '-U'], capture_output=True, text=True, timeout=60)
        return jsonify({'ok': result.returncode == 0, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'ok': False, 'error': 'yt-dlp update timed out'}), 504)
    except OSError as e:
        return (jsonify({'ok': False, 'error': str(e)}), 503)

def _h_zoxide_272():
    """Query best-matching directory. Body: {"keywords": "project"}"""
    body = _json_body()
    keywords = body.get('keywords', '')
    if not keywords or not keywords.strip():
        return (jsonify({'error': "'keywords' is required"}), 400)
    exe = _find_tool('zoxide')
    if not exe:
        return (jsonify({'error': 'zoxide not installed', 'hint': 'Install with: winget install ajeetdsouza.zoxide'}), 503)
    try:
        r = subprocess.run([exe, 'query', str(keywords).strip()], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            err = r.stderr.strip() or 'No match found'
            _log(f"[zoxide query no match] {f'keywords={keywords}: {err}'}")
            return jsonify({'match': None, 'keywords': keywords, 'hint': err})
        match = r.stdout.strip()
        return jsonify({'match': match, 'keywords': keywords, 'exists': os.path.isdir(match) if match else False})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'zoxide query timed out'}), 504)
    except Exception as e:
        _log(f'[zoxide query exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _h_zoxide_273():
    """List all tracked directories ranked by frecency (most-used first)."""
    exe = _find_tool('zoxide')
    if not exe:
        return (jsonify({'error': 'zoxide not installed', 'hint': 'Install with: winget install ajeetdsouza.zoxide'}), 503)
    try:
        r = subprocess.run([exe, 'query', '-l'], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            _log(f'[zoxide list error] {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip() or 'zoxide list failed'}), 500)
        entries = []
        for line in r.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.strip().split(None, 1)
            if len(parts) >= 2:
                try:
                    score = float(parts[0])
                except (ValueError, TypeError):
                    score = 0
                entries.append({'score': score, 'path': parts[1]})
            else:
                entries.append({'score': 0, 'path': parts[0]})
        return jsonify({'entries': entries, 'total': len(entries)})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'zoxide list timed out'}), 504)
    except Exception as e:
        _log(f'[zoxide list exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)

def _h_zoxide_274():
    """Add a directory to zoxide's database. Body: {"path": "/some/dir"}"""
    body = _json_body()
    dir_path = body.get('path', '')
    if not dir_path or not dir_path.strip():
        return (jsonify({'error': "'path' is required"}), 400)
    exe = _find_tool('zoxide')
    if not exe:
        return (jsonify({'error': 'zoxide not installed', 'hint': 'Install with: winget install ajeetdsouza.zoxide'}), 503)
    dir_path = os.path.abspath(dir_path.strip())
    if not os.path.isdir(dir_path):
        return (jsonify({'error': f'Directory not found: {dir_path}'}), 404)
    try:
        r = subprocess.run([exe, 'add', dir_path], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            _log(f'[zoxide add error] {r.stderr.strip()}')
            return (jsonify({'error': r.stderr.strip() or 'zoxide add failed'}), 500)
        return jsonify({'added': dir_path, 'status': 'ok'})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'zoxide add timed out'}), 504)
    except Exception as e:
        _log(f'[zoxide add exception] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _ffmpeg__probe(exe, input_path):
    """Probe media via ffprobe (JSON); fall back to ffmpeg -i stderr parse."""
    ffprobe = shutil.which('ffprobe')
    if ffprobe:
        try:
            r = subprocess.run(
                [ffprobe, '-v', 'error', '-print_format', 'json',
                 '-show_format', '-show_streams', input_path],
                capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                return json.loads(r.stdout)
        except Exception:
            pass
    r = subprocess.run(
        [exe, '-hide_banner', '-i', input_path],
        capture_output=True, text=True, errors='replace', timeout=30)
    return {'format': {}, 'streams': [], 'raw': r.stderr}


def _ffmpeg__summary(data):
    streams = data.get('streams', []) or []
    fmt = data.get('format', {}) or {}
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    return {
        'duration': fmt.get('duration'),
        'size_bytes': fmt.get('size'),
        'bit_rate': fmt.get('bit_rate'),
        'format_name': fmt.get('format_name'),
        'n_streams': len(streams),
        'video': {
            'codec': video.get('codec_name'),
            'width': video.get('width'),
            'height': video.get('height'),
            'fps': video.get('avg_frame_rate'),
            'pix_fmt': video.get('pix_fmt'),
        } if video else None,
        'audio': {
            'codec': audio.get('codec_name'),
            'sample_rate': audio.get('sample_rate'),
            'channels': audio.get('channels'),
            'bit_rate': audio.get('bit_rate'),
        } if audio else None,
    }


def _h_ffmpeg_275():
    """Probe media file metadata — duration, codecs, resolution, bitrate.

        Body (JSON): {"path": "/abs/or/rel/media/file"}
        """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('ffmpeg')
    if not exe:
        return (jsonify({'error': 'ffmpeg not installed', 'hint': 'winget install Gyan.FFmpeg'}), 503)
    if not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    try:
        data = _ffmpeg__probe(exe, path)
        return jsonify({'ok': True, 'path': path,
                        'summary': _ffmpeg__summary(data),
                        'streams': data.get('streams', []),
                        'format': data.get('format', {})})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'probe timed out'}), 504)
    except Exception as e:
        _log(f'[ffmpeg probe] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_ffmpeg_276():
    """Transcode a media file.

        Body (JSON):
            path (str, required): Source media file.
            output (str, required): Destination file path.
            vcodec (str, optional): Video codec, default "libx264". "copy" to stream-copy.
            acodec (str, optional): Audio codec, default "aac". "copy" to stream-copy.
            crf (str, optional): Constant rate factor, default "23".
            preset (str, optional): x264 preset, default "medium".
            resolution (str, optional): e.g. "1280:720" to scale.
            audio_bitrate (str, optional): e.g. "128k".
        """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    output = str(body.get('output') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    if not output:
        return _missing_field(body, 'output')
    exe = _find_tool('ffmpeg')
    if not exe:
        return (jsonify({'error': 'ffmpeg not installed', 'hint': 'winget install Gyan.FFmpeg'}), 503)
    if not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    vcodec = str(body.get('vcodec') or 'libx264').strip()
    acodec = str(body.get('acodec') or 'aac').strip()
    crf = str(body.get('crf') or '23').strip()
    preset = str(body.get('preset') or 'medium').strip()
    resolution = str(body.get('resolution') or '').strip()
    audio_bitrate = str(body.get('audio_bitrate') or '').strip()
    cmd = [exe, '-hide_banner', '-y', '-i', path]
    if resolution:
        cmd.extend(['-vf', f'scale={resolution}'])
    if vcodec != 'copy':
        cmd.extend(['-c:v', vcodec, '-crf', crf, '-preset', preset])
    else:
        cmd.extend(['-c:v', 'copy'])
    if acodec != 'copy':
        cmd.extend(['-c:a', acodec])
        if audio_bitrate:
            cmd.extend(['-b:a', audio_bitrate])
    else:
        cmd.extend(['-c:a', 'copy'])
    cmd.append(output)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=3600)
        if r.returncode != 0:
            _log(f'[ffmpeg transcode] rc={r.returncode}: {r.stderr[-300:]}')
            return (jsonify({'error': (r.stderr.strip() or 'transcode failed')[-2000:]}), 500)
        ok = os.path.isfile(output)
        return jsonify({'ok': True, 'output': output, 'exists': ok,
                        'size_bytes': os.path.getsize(output) if ok else None})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'transcode timed out (3600s)'}), 504)
    except Exception as e:
        _log(f'[ffmpeg transcode] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_ffmpeg_277():
    """Extract the audio track from a media file.

        Body (JSON):
            path (str, required): Source media file.
            output (str, optional): Destination audio file. Defaults to source stem + format.
            format (str, optional): Output container ("mp3" or "m4a"), default "mp3".
        """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    fmt = str(body.get('format') or 'mp3').strip().lstrip('.')
    if fmt not in ('mp3', 'm4a', 'aac', 'wav', 'ogg'):
        return (jsonify({'error': f'Unsupported audio format: {fmt}'}), 400)
    output = str(body.get('output') or '').strip()
    if not output:
        output = os.path.splitext(path)[0] + '.' + fmt
    exe = _find_tool('ffmpeg')
    if not exe:
        return (jsonify({'error': 'ffmpeg not installed', 'hint': 'winget install Gyan.FFmpeg'}), 503)
    if not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    codec = {'mp3': 'libmp3lame', 'm4a': 'aac', 'aac': 'aac', 'wav': 'pcm_s16le', 'ogg': 'libvorbis'}[fmt]
    cmd = [exe, '-hide_banner', '-y', '-i', path, '-vn', '-c:a', codec, output]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=3600)
        if r.returncode != 0:
            _log(f'[ffmpeg extract_audio] rc={r.returncode}: {r.stderr[-300:]}')
            return (jsonify({'error': (r.stderr.strip() or 'extract failed')[-2000:]}), 500)
        ok = os.path.isfile(output)
        return jsonify({'ok': True, 'output': output, 'exists': ok,
                        'size_bytes': os.path.getsize(output) if ok else None})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'audio extraction timed out'}), 504)
    except Exception as e:
        _log(f'[ffmpeg extract_audio] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_ffmpeg_278():
    """Extract frames from a video.

        Body (JSON):
            path (str, required): Source video file.
            output_dir (str, required): Directory to write frames into.
            timestamp (str, optional): Extract a single frame at this time (e.g. "00:00:05").
            fps (str, optional): Extract frames at this rate (e.g. "1" = 1 per second).
            width (str, optional): Scale frame width (keeps aspect ratio).
        Exactly one of `timestamp` or `fps` is required.
        """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    output_dir = str(body.get('output_dir') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    if not output_dir:
        return _missing_field(body, 'output_dir')
    exe = _find_tool('ffmpeg')
    if not exe:
        return (jsonify({'error': 'ffmpeg not installed', 'hint': 'winget install Gyan.FFmpeg'}), 503)
    if not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    os.makedirs(output_dir, exist_ok=True)
    timestamp = str(body.get('timestamp') or '').strip()
    fps = str(body.get('fps') or '').strip()
    width = str(body.get('width') or '').strip()
    if timestamp:
        safe = timestamp.replace(':', '').replace('.', '')
        out_pattern = os.path.join(output_dir, f'frame_at_{safe}.png')
        cmd = [exe, '-hide_banner', '-y', '-ss', timestamp, '-i', path, '-frames:v', '1']
        if width:
            cmd.extend(['-vf', f'scale={width}:-1'])
        cmd.append(out_pattern)
    elif fps:
        out_pattern = os.path.join(output_dir, 'frame_%05d.jpg')
        cmd = [exe, '-hide_banner', '-y', '-i', path]
        vf = f'fps={fps}'
        if width:
            vf += f',scale={width}:-1'
        cmd.extend(['-vf', vf, out_pattern])
    else:
        return (jsonify({'error': "Either 'timestamp' or 'fps' is required"}), 400)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=3600)
        if r.returncode != 0:
            _log(f'[ffmpeg frames] rc={r.returncode}: {r.stderr[-300:]}')
            return (jsonify({'error': (r.stderr.strip() or 'frame extraction failed')[-2000:]}), 500)
        files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(output_dir, '*')) if os.path.isfile(f))
        return jsonify({'ok': True, 'output_dir': output_dir, 'frames': files, 'count': len(files)})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'frame extraction timed out'}), 504)
    except Exception as e:
        _log(f'[ffmpeg frames] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_ffmpeg_279():
    """Create an animated GIF from a video clip.

        Body (JSON):
            path (str, required): Source video file.
            output (str, optional): Destination .gif. Defaults to source stem + ".gif".
            start (str, optional): Start time (e.g. "00:00:02").
            duration (str, optional): Clip length (e.g. "5").
            fps (str, optional): GIF frame rate, default "10".
            width (str, optional): GIF width in pixels, default "480".
        """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    output = str(body.get('output') or '').strip()
    if not output:
        output = os.path.splitext(path)[0] + '.gif'
    exe = _find_tool('ffmpeg')
    if not exe:
        return (jsonify({'error': 'ffmpeg not installed', 'hint': 'winget install Gyan.FFmpeg'}), 503)
    if not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    start = str(body.get('start') or '').strip()
    duration = str(body.get('duration') or '').strip()
    fps = str(body.get('fps') or '10').strip()
    width = str(body.get('width') or '480').strip()
    filters = [f'fps={fps}', f'scale={width}:-1:flags=lanczos',
               'split[s0][s1]', '[s0]palettegen[p]', '[s1][p]paletteuse']
    cmd = [exe, '-hide_banner', '-y']
    if start:
        cmd.extend(['-ss', start])
    cmd.extend(['-i', path])
    if duration:
        cmd.extend(['-t', duration])
    cmd.extend(['-filter_complex', ';'.join(filters), output])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=3600)
        if r.returncode != 0:
            _log(f'[ffmpeg gif] rc={r.returncode}: {r.stderr[-300:]}')
            return (jsonify({'error': (r.stderr.strip() or 'gif creation failed')[-2000:]}), 500)
        ok = os.path.isfile(output)
        return jsonify({'ok': True, 'output': output, 'exists': ok,
                        'size_bytes': os.path.getsize(output) if ok else None})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'gif creation timed out'}), 504)
    except Exception as e:
        _log(f'[ffmpeg gif] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_hexyl_280():
    """Hex-dump a binary file.

        Body (JSON):
            path (str, required): File to dump.
            bytes_per_line (str, optional): Bytes per line, default 16.
            length (str, optional): Max bytes to read.
            offset (str, optional): Bytes to skip from the start.
            show_chars (bool, optional): Include the ASCII character panel. Default false.
        """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('hexyl')
    if not exe:
        return (jsonify({'error': 'hexyl not installed', 'hint': 'winget install sharkdp.hexyl'}), 503)
    if not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    cmd = [exe, '--color', 'never']
    if str(body.get('show_chars', 'false')).lower() not in ('1', 'true', 'yes'):
        cmd.append('--plain')
    for flag, key in (('--bytes', 'bytes_per_line'), ('--length', 'length'), ('--offset', 'offset')):
        v = str(body.get(key) or '').strip()
        if v:
            cmd.extend([flag, v])
    cmd.append(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'[hexyl view] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'hexyl failed'}), 500)
        return jsonify({'ok': True, 'path': path, 'dump': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'hexyl timed out'}), 504)
    except Exception as e:
        _log(f'[hexyl view] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_hexyl_281():
    """Hex-dump arbitrary bytes passed as text.

        Body (JSON):
            data (str, required): Text/binary content to hex-dump (fed via stdin).
            bytes_per_line (str, optional): Bytes per line, default 16.
            show_chars (bool, optional): Include the ASCII character panel. Default false.
        """
    body = _json_body()
    data = body.get('data')
    if data is None:
        return _missing_field(body, 'data')
    exe = _find_tool('hexyl')
    if not exe:
        return (jsonify({'error': 'hexyl not installed', 'hint': 'winget install sharkdp.hexyl'}), 503)
    cmd = [exe, '--color', 'never']
    if str(body.get('show_chars', 'false')).lower() not in ('1', 'true', 'yes'):
        cmd.append('--plain')
    bpl = str(body.get('bytes_per_line') or '').strip()
    if bpl:
        cmd.extend(['--bytes', bpl])
    try:
        r = subprocess.run(cmd, input=str(data), capture_output=True, text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'[hexyl decode] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'hexyl failed'}), 500)
        return jsonify({'ok': True, 'dump': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'hexyl timed out'}), 504)
    except Exception as e:
        _log(f'[hexyl decode] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_doggo_282():
    """Resolve DNS records with doggo.

        Body (JSON):
            name (str, required): Domain/hostname to resolve, e.g. 'example.com'.
            types (str|list, optional): Record type(s): A, AAAA, MX, TXT, CNAME, NS, SOA, etc.
                                        Comma-separated string or list. Default A.
            resolver (str, optional): DNS server, e.g. '9.9.9.9' or 'https://cloudflare-dns.com/dns-query'.
            json (bool, optional): Return machine-readable JSON. Default false.
            short (bool, optional): Short output (answers only). Default false.
            reverse (bool, optional): Reverse DNS lookup (name is treated as an IP). Default false.
        """
    body = _json_body() or {}
    name = str(body.get('name') or '').strip()
    if not name:
        return _missing_field(body, 'name')
    exe = _find_tool('doggo')
    if not exe:
        return (jsonify({'error': 'doggo not installed', 'hint': 'winget install doggo  (or scoop install doggo)'}), 503)
    cmd = [exe]
    if body.get('json'):
        cmd.append('--json')
    if body.get('short'):
        cmd.append('--short')
    if body.get('reverse'):
        cmd.append('--reverse')
    types = body.get('types')
    if isinstance(types, str):
        types = [t.strip().upper() for t in types.split(',') if t.strip()]
    elif isinstance(types, list):
        types = [str(t).strip().upper() for t in types if str(t).strip()]
    else:
        types = []
    cmd.extend(types)
    cmd.append(name)
    resolver = str(body.get('resolver') or '').strip()
    if resolver:
        cmd.append('@' + resolver.lstrip('@'))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=30)
        if r.returncode != 0:
            _log(f'[doggo query] rc={r.returncode}: {(r.stderr or "")[:300]}')
            return (jsonify({'error': (r.stderr or '').strip() or 'doggo failed', 'name': name}), 502)
        return jsonify({'ok': True, 'name': name, 'types': types or ['A'], 'stdout': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'doggo timed out after 30s', 'name': name}), 504)
    except Exception as e:
        _log(f'[doggo query] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_volatility3_283():
    """List available Volatility 3 plugins.

        Query params:
            filter (str, optional): Substring filter on plugin name (e.g. 'windows' or 'pslist').
        """
    exe = _find_tool('volatility3')
    if not exe:
        return (jsonify({'error': 'volatility3 not installed', 'hint': 'pip install volatility3'}), 503)
    try:
        r = subprocess.run([exe, '-h'], capture_output=True, text=True, errors='replace', timeout=30)
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'volatility3 help timed out'}), 504)
    except Exception as e:
        return (jsonify({'error': str(e)}), 500)
    out = r.stdout or r.stderr or ''
    plugins = []
    for line in out.splitlines():
        m = re.match(r'^\s+([a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*)\.[A-Z][A-Za-z0-9_]*\s', line)
        if m:
            plugins.append(m.group(1))
    plugins = sorted(set(plugins))
    filt = (request.args.get('filter') or '').strip().lower()
    if filt:
        plugins = [p for p in plugins if filt in p.lower()]
    return jsonify({'ok': True, 'count': len(plugins), 'plugins': plugins})


def _h_volatility3_284():
    """Run a Volatility 3 plugin against a memory image.

        Body (JSON):
            image (str, required): Path to the memory dump (.raw/.mem/.vmem/.dmp).
            plugin (str, required): Namespaced plugin, e.g. 'windows.info', 'windows.pslist',
                                    'windows.netscan', 'windows.malfind', 'linux.pslist'.
            args (list[str], optional): Extra plugin arguments (e.g. ['--pid', '1234']).
            timeout (int, optional): Max seconds (default 300, max 1800).
        """
    body = _json_body() or {}
    image = str(body.get('image') or '').strip()
    plugin = str(body.get('plugin') or '').strip()
    if not image:
        return _missing_field(body, 'image')
    if not plugin:
        return _missing_field(body, 'plugin')
    exe = _find_tool('volatility3')
    if not exe:
        return (jsonify({'error': 'volatility3 not installed', 'hint': 'pip install volatility3'}), 503)
    if not os.path.isfile(image):
        return (jsonify({'error': f'Memory image not found: {image}'}), 404)
    if not re.match(r'^[a-z][a-z0-9_.]*$', plugin):
        return (jsonify({'error': f'Invalid plugin name: {plugin}'}), 400)
    args = body.get('args') or []
    if isinstance(args, str):
        args = shlex.split(args)
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return (jsonify({'error': "'args' must be a list of strings"}), 400)
    timeout = body.get('timeout', 300)
    try:
        timeout = max(10, min(int(timeout), 1800))
    except (ValueError, TypeError):
        timeout = 300
    cmd = [exe, '-f', image, plugin] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout)
        ok = r.returncode == 0
        if not ok:
            _log(f'[volatility3 analyze] rc={r.returncode}: {(r.stderr or "")[:300]}')
        return jsonify({'ok': ok, 'returncode': r.returncode, 'image': image, 'plugin': plugin,
                        'stdout': (r.stdout or '')[-4000:], 'stderr': (r.stderr or '')[-4000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'volatility3 timed out after {timeout}s', 'plugin': plugin}), 504)
    except Exception as e:
        _log(f'[volatility3 analyze] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_hyperfine_285():
    """Benchmark one or more commands with hyperfine, returning JSON results.

        Body (JSON):
            commands (list[str], required): Command lines to benchmark (e.g.
                'python -V', 'curl -s http://localhost:9123/ping'). Each entry is a
                full command string.
            runs (int, optional): Number of runs per command. Default 10, max 100.
            warmup (int, optional): Warmup runs before timing. Default 3.
            shell (bool, optional): Run each command through the shell. Default False
                (uses --shell=none, which is more reliable on Windows for simple commands).
            time_limit (str, optional): Per-command time limit, e.g. '30s'. Optional.
            show_output (bool, optional): Capture command stdout. Default False.
            timeout (int, optional): Max seconds for the whole benchmark. Default 600, max 1800.
        """
    body = _json_body() or {}
    commands = body.get('commands')
    if not isinstance(commands, list) or not commands or not all(isinstance(c, str) and c.strip() for c in commands):
        return (jsonify({'error': "'commands' must be a non-empty list of command strings"}), 400)
    exe = _find_tool('hyperfine')
    if not exe:
        return (jsonify({'error': 'hyperfine is not installed',
                         'hint': 'Install with: winget install sharkdp.hyperfine'}), 503)
    try:
        runs = max(1, min(int(body.get('runs', 10)), 100))
    except (ValueError, TypeError):
        runs = 10
    try:
        warmup = max(0, min(int(body.get('warmup', 3)), 100))
    except (ValueError, TypeError):
        warmup = 3
    try:
        timeout = max(10, min(int(body.get('timeout', 600)), 1800))
    except (ValueError, TypeError):
        timeout = 600
    use_shell = str(body.get('shell', 'false')).lower() in ('1', 'true', 'yes')
    time_limit = str(body.get('time_limit') or '').strip()
    show_output = str(body.get('show_output', 'false')).lower() in ('1', 'true', 'yes')
    tmp = tempfile.NamedTemporaryFile(suffix='.json', prefix='hyperfine_', delete=False)
    tmp.close()
    cmd = [exe, '--export-json', tmp.name, '-w', str(warmup), '-r', str(runs)]
    if not use_shell:
        cmd.append('-N')
    if time_limit:
        cmd.extend(['--time-limit', time_limit])
    if show_output:
        cmd.append('--show-output')
    cmd.extend(commands)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout)
        results = None
        if os.path.isfile(tmp.name):
            try:
                with open(tmp.name, 'r', encoding='utf-8') as fh:
                    results = json_lib.load(fh)
            except Exception:
                results = None
        return jsonify({'ok': r.returncode == 0, 'returncode': r.returncode,
                        'commands': commands, 'results': results,
                        'summary': (r.stdout or '').strip(), 'stderr': (r.stderr or '').strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'hyperfine timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[auto_hyperfine_bench] {e}')
        return (jsonify({'error': str(e)}), 500)
    finally:
        try:
            if os.path.isfile(tmp.name):
                os.remove(tmp.name)
        except OSError:
            pass


def _h_duf_286():
    """Report disk usage across filesystems via duf (JSON).

        GET params or JSON body:
            all (bool, optional): Include pseudo/duplicate/inaccessible filesystems. Default False.
            only_fs (str, optional): Comma-separated filesystem types to include (e.g. 'ntfs,ext4').
            hide_fs (str, optional): Comma-separated filesystem types to hide.
            sort (str, optional): Sort column: mountpoint|size|used|avail|usage|inodes|
                inodes_used|inodes_avail|inodes_usage|type|filesystem. Default 'size'.
            threshold (int, optional): Only return mounts with usage% >= threshold (0-100). Default 0.
        """
    exe = _find_tool('duf')
    if not exe:
        return (jsonify({'error': 'duf is not installed',
                         'hint': 'Install with: winget install muesli.duf'}), 503)
    if request.method == 'POST':
        data = _json_body() or {}
    else:
        data = {k: v for k, v in request.args.items()}
    cmd = [exe, '--json']
    if str(data.get('all', 'false')).lower() in ('1', 'true', 'yes'):
        cmd.append('--all')
    only_fs = str(data.get('only_fs') or '').strip()
    if only_fs:
        cmd.extend(['--only-fs', only_fs])
    hide_fs = str(data.get('hide_fs') or '').strip()
    if hide_fs:
        cmd.extend(['--hide-fs', hide_fs])
    sort_col = str(data.get('sort') or 'size').strip().lower()
    valid_cols = {'mountpoint', 'size', 'used', 'avail', 'usage', 'inodes',
                  'inodes_used', 'inodes_avail', 'inodes_usage', 'type', 'filesystem'}
    if sort_col in valid_cols:
        cmd.extend(['--sort', sort_col])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=30)
        if r.returncode != 0:
            _log(f"[auto_duf_usage] rc={r.returncode}: {(r.stderr or '')[:300]}")
            return (jsonify({'error': (r.stderr or '').strip() or 'duf failed'}), 500)
        try:
            mounts = json_lib.loads(r.stdout)
        except Exception:
            mounts = []
        try:
            threshold = int(data.get('threshold', 0) or 0)
        except (ValueError, TypeError):
            threshold = 0
        # duf JSON exposes total/used bytes, not a usage% field — compute it here.
        for m in mounts:
            try:
                total = int(m.get('total') or 0)
                used = int(m.get('used') or 0)
                m['usage_pct'] = round(100.0 * used / total, 1) if total > 0 else None
            except (ValueError, TypeError):
                m['usage_pct'] = None
        if threshold > 0:
            mounts = [m for m in mounts if (m.get('usage_pct') or 0) >= threshold]
        return jsonify({'ok': True, 'count': len(mounts), 'mounts': mounts})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'duf timed out after 30s'}), 504)
    except Exception as e:
        _log(f'[auto_duf_usage] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_jq_287():
    """Run a jq filter against JSON input.

        Body (JSON):
            filter (str, required): The jq filter expression, e.g. '.items[] | {id, name}'.
            input (str|object, optional): JSON to process (a string is treated as raw JSON text;
                any other object is re-serialized). Provide this or 'path'.
            path (str, optional): Path to a JSON file to process. Ignored if 'input' is provided.
            raw_output (bool, optional): Emit raw strings without JSON quoting. Default False.
            compact_output (bool, optional): Emit compact JSON (no pretty-printing). Default False.
            slurp (bool, optional): Read the entire input as a single array. Default False.
            timeout (int, optional): Max seconds. Default 30, max 120.
        """
    body = _json_body() or {}
    filter_ = str(body.get('filter') or '').strip()
    if not filter_:
        return _missing_field(body, 'filter')
    exe = _find_tool('jq')
    if not exe:
        return (jsonify({'error': 'jq is not installed',
                         'hint': 'Install with: winget install jqlang.jq'}), 503)
    raw_input = body.get('input')
    path = str(body.get('path') or '').strip()
    if raw_input is None and not path:
        return (jsonify({'error': "Provide either 'input' (JSON string) or 'path' (file)"}), 400)
    if path and not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    try:
        timeout = max(5, min(int(body.get('timeout', 30)), 120))
    except (ValueError, TypeError):
        timeout = 30
    cmd = [exe]
    if str(body.get('raw_output', 'false')).lower() in ('1', 'true', 'yes'):
        cmd.append('-r')
    if str(body.get('compact_output', 'false')).lower() in ('1', 'true', 'yes'):
        cmd.append('-c')
    if str(body.get('slurp', 'false')).lower() in ('1', 'true', 'yes'):
        cmd.append('-s')
    cmd.append(filter_)
    if path:
        cmd.append(path)
    stdin_data = None
    if not path:
        stdin_data = raw_input if isinstance(raw_input, str) else json_lib.dumps(raw_input)
    try:
        r = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True,
                           errors='replace', timeout=timeout)
        if r.returncode != 0:
            _log(f"[auto_jq_query] rc={r.returncode}: {(r.stderr or '')[:300]}")
            return (jsonify({'error': (r.stderr or 'jq failed').strip()}), 400)
        return jsonify({'ok': True, 'filter': filter_, 'result': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'jq timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[auto_jq_query] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_jq_288():
    """Validate that input is well-formed JSON using jq.

        Body (JSON):
            input (str|object, optional): JSON to validate. Provide this or 'path'.
            path (str, optional): Path to a JSON file to validate.
        """
    body = _json_body() or {}
    raw_input = body.get('input')
    path = str(body.get('path') or '').strip()
    if raw_input is None and not path:
        return (jsonify({'error': "Provide either 'input' (JSON string) or 'path' (file)"}), 400)
    if path and not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    exe = _find_tool('jq')
    if not exe:
        return (jsonify({'error': 'jq is not installed',
                         'hint': 'Install with: winget install jqlang.jq'}), 503)
    cmd = [exe, '.']
    if path:
        cmd.append(path)
    stdin_data = None if path else (raw_input if isinstance(raw_input, str) else json_lib.dumps(raw_input))
    try:
        r = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True,
                           errors='replace', timeout=30)
        valid = r.returncode == 0
        return jsonify({'valid': valid,
                        'error': (r.stderr or '').strip() if not valid else None,
                        'parsed': r.stdout if valid else None})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'jq validate timed out after 30s'}), 504)
    except Exception as e:
        _log(f'[auto_jq_validate] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_difftastic_289():
    """Structural diff of two files or two inline strings.

        Body (JSON):
            left (str, required): Left-side content, or a file path when files=true.
            right (str, required): Right-side content, or a file path when files=true.
            files (bool, optional): Treat left/right as file paths. Default False.
            left_path (str, optional): Display name/path for the left side (used to infer language).
            right_path (str, optional): Display name/path for the right side.
            display (str, optional): 'inline' (default), 'side-by-side', or 'json'.
            language (str, optional): Force a language, e.g. 'python', 'javascript', 'rust'.
            timeout (int, optional): Max seconds. Default 30, max 120.
        """
    body = _json_body() or {}
    left = body.get('left')
    right = body.get('right')
    if left is None:
        return (jsonify({'error': "Missing required field: left"}), 400)
    if right is None:
        return (jsonify({'error': "Missing required field: right"}), 400)
    exe = _find_tool('difftastic')
    if not exe:
        return (jsonify({'error': 'difftastic is not installed',
                         'hint': 'Install with: winget install Wilfred.difftastic'}), 503)
    display = str(body.get('display') or 'inline').strip().lower()
    if display not in ('inline', 'side-by-side', 'side-by-side-show-both', 'json'):
        display = 'inline'
    language = str(body.get('language') or '').strip()
    use_files = str(body.get('files', 'false')).lower() in ('1', 'true', 'yes')
    left_path = str(body.get('left_path') or '').strip()
    right_path = str(body.get('right_path') or '').strip()
    try:
        timeout = max(5, min(int(body.get('timeout', 30)), 120))
    except (ValueError, TypeError):
        timeout = 30
    tmp = []
    try:
        if use_files:
            left_arg, right_arg = str(left), str(right)
            for p in (left_arg, right_arg):
                if not os.path.isfile(p):
                    return (jsonify({'error': f'File not found: {p}'}), 404)
        else:
            def _suffix(name):
                ext = os.path.splitext(name or '')[1]
                return ext if ext else '.txt'
            lf = tempfile.NamedTemporaryFile(mode='w', suffix=_suffix(left_path), delete=False, encoding='utf-8')
            lf.write(str(left))
            lf.close()
            tmp.append(lf.name)
            rf = tempfile.NamedTemporaryFile(mode='w', suffix=_suffix(right_path), delete=False, encoding='utf-8')
            rf.write(str(right))
            rf.close()
            tmp.append(rf.name)
            left_arg, right_arg = lf.name, rf.name
        cmd = [exe, '--display', display, '--exit-code']
        if display != 'json':
            cmd.extend(['--color', 'never'])
        if language:
            cmd.extend(['--language', language])
        cmd.extend([left_arg, right_arg])
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout)
        if r.returncode not in (0, 1):
            _log(f"[auto_difftastic_diff] rc={r.returncode}: {(r.stderr or '')[:300]}")
            return (jsonify({'error': (r.stderr or 'difftastic failed').strip()}), 500)
        if display == 'json':
            parsed = None
            if (r.stdout or '').strip():
                try:
                    parsed = json_lib.loads(r.stdout)
                except Exception:
                    parsed = None
            return jsonify({'ok': True, 'changed': r.returncode == 1, 'display': display,
                            'result': parsed, 'raw': r.stdout if parsed is None else None})
        return jsonify({'ok': True, 'changed': r.returncode == 1, 'display': display, 'diff': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'difftastic timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[auto_difftastic_diff] {e}')
        return (jsonify({'error': str(e)}), 500)
    finally:
        for p in tmp:
            try:
                os.unlink(p)
            except OSError:
                pass


def _h_difftastic_290():
    """List the languages supported by difftastic, along with their file extensions.

        Body (JSON):
            none - no body required.
        """
    exe = _find_tool('difftastic')
    if not exe:
        return (jsonify({'error': 'difftastic is not installed',
                         'hint': 'Install with: winget install Wilfred.difftastic'}), 503)
    try:
        r = subprocess.run([exe, '--list-languages'], capture_output=True, text=True,
                           errors='replace', timeout=30)
        lines = [ln for ln in (r.stdout or '').splitlines() if ln.strip()]
        return jsonify({'ok': r.returncode == 0, 'count': len(lines), 'languages': lines})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'difftastic --list-languages timed out'}), 504)
    except Exception as e:
        _log(f'[auto_difftastic_languages] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_uv_291():
    """Install Python packages with `uv pip install`.

        Body (JSON):
            packages (str|list, required): package spec(s) to install, e.g. 'requests'
                or ['requests', 'numpy>=1.24']. Comma/space separated when a string.
            requirements (str, optional): path to a requirements.txt file.
            python (str, optional): target interpreter/venv path (--python).
            extra_args (list, optional): extra uv flags, e.g. ['--upgrade'].
            timeout (int, optional): max seconds. Default 120, max 600.
        """
    body = _json_body() or {}
    packages = body.get('packages')
    requirements = str(body.get('requirements') or '').strip()
    if packages is None and not requirements:
        return (jsonify({'error': "Provide 'packages' (str or list) or 'requirements' (file path)"}), 400)
    exe = _find_tool('uv')
    if not exe:
        return (jsonify({'error': 'uv is not installed',
                         'hint': 'Install with: winget install astral-sh.uv'}), 503)
    if isinstance(packages, str):
        pkgs = [p for p in packages.replace(',', ' ').split() if p]
    elif isinstance(packages, list):
        pkgs = [str(p) for p in packages if str(p).strip()]
    else:
        pkgs = []
    if not pkgs and not requirements:
        return (jsonify({'error': "'packages' resolved to empty; provide at least one package or a requirements file"}), 400)
    if requirements and not os.path.isfile(requirements):
        return (jsonify({'error': f'requirements file not found: {requirements}'}), 404)
    try:
        timeout = max(10, min(int(body.get('timeout', 120)), 600))
    except (ValueError, TypeError):
        timeout = 120
    cmd = [exe, 'pip', 'install']
    python = str(body.get('python') or '').strip()
    if python:
        cmd.extend(['--python', python])
    for a in (body.get('extra_args') or []):
        cmd.append(str(a))
    if requirements:
        cmd.extend(['-r', requirements])
    cmd.extend(pkgs)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout)
        out = (r.stdout or '') + (('\n' + r.stderr) if r.stderr else '')
        if r.returncode != 0:
            _log(f"[auto_uv_pip_install] rc={r.returncode}: {out[:300]}")
            return (jsonify({'ok': False, 'rc': r.returncode, 'output': out.strip()}), 400)
        return jsonify({'ok': True, 'installed': pkgs if pkgs else ['(from requirements)'], 'output': out.strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'uv pip install timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[auto_uv_pip_install] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_uv_292():
    """Run a command or Python script with `uv run` (auto-manages env/deps).

        Body (JSON):
            args (str|list, required): command + arguments, e.g. 'python script.py'
                or ['ruff', 'check', '.'].
            cwd (str, optional): working directory.
            timeout (int, optional): max seconds. Default 120, max 600.
        """
    body = _json_body() or {}
    raw = body.get('args')
    if raw is None:
        return _missing_field(body, 'args')
    exe = _find_tool('uv')
    if not exe:
        return (jsonify({'error': 'uv is not installed',
                         'hint': 'Install with: winget install astral-sh.uv'}), 503)
    if isinstance(raw, str):
        parts = shlex.split(raw)
    elif isinstance(raw, list):
        parts = [str(p) for p in raw]
    else:
        return (jsonify({'error': "'args' must be a string or list"}), 400)
    if not parts:
        return (jsonify({'error': "'args' is empty"}), 400)
    try:
        timeout = max(10, min(int(body.get('timeout', 120)), 600))
    except (ValueError, TypeError):
        timeout = 120
    cwd = str(body.get('cwd') or '').strip() or None
    if cwd and not os.path.isdir(cwd):
        return (jsonify({'error': f'cwd not found: {cwd}'}), 404)
    try:
        r = subprocess.run([exe, 'run'] + parts, capture_output=True, text=True,
                           errors='replace', timeout=timeout, cwd=cwd)
        out = (r.stdout or '') + (('\n' + r.stderr) if r.stderr else '')
        return jsonify({'ok': r.returncode == 0, 'rc': r.returncode, 'output': out})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'uv run timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[auto_uv_run] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_pandoc_293():
    """Convert text or a file between any supported document formats.

        Body (JSON):
            from (str, required): source format, e.g. 'markdown', 'html', 'docx', 'rst'.
            to (str, required): target format, e.g. 'markdown', 'html', 'docx', 'plain', 'latex'.
            input (str, optional): inline content to convert. Provide this or 'path'.
            path (str, optional): path to an input file.
            output (str, optional): write result to this file path instead of returning inline.
            standalone (bool, optional): produce a full standalone document. Default True.
            extra_args (list, optional): additional pandoc flags.
            timeout (int, optional): max seconds. Default 60, max 300.
        """
    body = _json_body() or {}
    src_fmt = str(body.get('from') or '').strip()
    dst_fmt = str(body.get('to') or '').strip()
    if not src_fmt:
        return (jsonify({'error': "Missing required field: from (source format)"}), 400)
    if not dst_fmt:
        return (jsonify({'error': "Missing required field: to (target format)"}), 400)
    exe = _find_tool('pandoc')
    if not exe:
        return (jsonify({'error': 'pandoc is not installed',
                         'hint': 'Install with: winget install JohnMacFarlane.Pandoc'}), 503)
    raw_input = body.get('input')
    path = str(body.get('path') or '').strip()
    if raw_input is None and not path:
        return (jsonify({'error': "Provide 'input' (inline text) or 'path' (file)"}), 400)
    if path and not os.path.isfile(path):
        return (jsonify({'error': f'File not found: {path}'}), 404)
    try:
        timeout = max(10, min(int(body.get('timeout', 60)), 300))
    except (ValueError, TypeError):
        timeout = 60
    cmd = [exe, '-f', src_fmt, '-t', dst_fmt]
    if str(body.get('standalone', 'true')).lower() not in ('0', 'false', 'no'):
        cmd.append('--standalone')
    for a in (body.get('extra_args') or []):
        cmd.append(str(a))
    stdin_data = None
    if path:
        cmd.append(path)
    else:
        stdin_data = raw_input if isinstance(raw_input, str) else str(raw_input)
    output = str(body.get('output') or '').strip()
    if output:
        cmd.extend(['-o', output])
    try:
        r = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True,
                           errors='replace', timeout=timeout)
        if r.returncode != 0:
            _log(f"[auto_pandoc_convert] rc={r.returncode}: {(r.stderr or '')[:300]}")
            return (jsonify({'error': (r.stderr or 'pandoc failed').strip()}), 400)
        if output:
            size = os.path.getsize(output) if os.path.isfile(output) else None
            return jsonify({'ok': True, 'from': src_fmt, 'to': dst_fmt, 'output_path': output, 'bytes': size})
        return jsonify({'ok': True, 'from': src_fmt, 'to': dst_fmt, 'result': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'pandoc timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[auto_pandoc_convert] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_pandoc_294():
    """List the input/output formats pandoc supports (and highlight styles)."""
    exe = _find_tool('pandoc')
    if not exe:
        return (jsonify({'error': 'pandoc is not installed',
                         'hint': 'Install with: winget install JohnMacFarlane.Pandoc'}), 503)
    try:
        ri = subprocess.run([exe, '--list-input-formats'], capture_output=True, text=True,
                            errors='replace', timeout=30)
        ro = subprocess.run([exe, '--list-output-formats'], capture_output=True, text=True,
                            errors='replace', timeout=30)
        input_formats = [x for x in (ri.stdout or '').splitlines() if x.strip()]
        output_formats = [x for x in (ro.stdout or '').splitlines() if x.strip()]
        return jsonify({'ok': ri.returncode == 0 and ro.returncode == 0,
                        'input_formats': input_formats,
                        'output_formats': output_formats})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'pandoc format listing timed out'}), 504)
    except Exception as e:
        _log(f'[auto_pandoc_formats] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_rclone_295():
    """List configured rclone remotes (rclone listremotes --json)."""
    exe = _find_tool('rclone')
    if not exe:
        return (jsonify({'error': 'rclone is not installed', 'hint': 'Install with: winget install Rclone.Rclone'}), 503)
    try:
        r = subprocess.run([exe, 'listremotes', '--json'], capture_output=True, text=True, errors='replace', timeout=30)
        out = (r.stdout or '').strip()
        remotes = None
        if out:
            try:
                remotes = json_lib.loads(out)
            except Exception:
                remotes = [x.strip() for x in out.splitlines() if x.strip()]
        return jsonify({'ok': r.returncode == 0, 'remotes': remotes, 'raw': out})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'rclone listremotes timed out'}), 504)
    except Exception as e:
        _log(f'[auto_rclone_remotes] {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_rclone_296():
    """List files in a remote path as JSON (rclone lsjson <path>).

        Body (JSON):
            path (str, required): remote path, e.g. "gdrive:backups" or "s3:bucket/dir".
            max_depth (int, optional): recursion depth limit. Default: recurse.
            recursive (bool, optional): recurse into subdirectories. Default true.
    """
    body = _json_body()
    path = body.get('path')
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('rclone')
    if not exe:
        return (jsonify({'error': 'rclone is not installed', 'hint': 'Install with: winget install Rclone.Rclone'}), 503)
    args = ['lsjson', path]
    md = body.get('max_depth')
    if md is not None:
        args += ['--max-depth', str(md)]
    elif body.get('recursive', True) is False:
        args += ['--max-depth', '1']
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, errors='replace', timeout=120)
        if r.returncode != 0:
            _log(f'auto_rclone_list: rclone exited {r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'rclone lsjson failed'}), 500)
        entries = None
        out = (r.stdout or '').strip()
        if out:
            try:
                entries = json_lib.loads(out)
            except Exception:
                entries = out.splitlines()
        return jsonify({'path': path,
                        'count': len(entries) if isinstance(entries, list) else None,
                        'entries': entries})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'rclone lsjson timed out after 120s'}), 504)
    except Exception as e:
        _log(f'auto_rclone_list exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_rclone_297():
    """Total size + object count of a remote path (rclone size <path> --json)."""
    body = _json_body()
    path = body.get('path')
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('rclone')
    if not exe:
        return (jsonify({'error': 'rclone is not installed', 'hint': 'Install with: winget install Rclone.Rclone'}), 503)
    try:
        r = subprocess.run([exe, 'size', path, '--json'], capture_output=True, text=True, errors='replace', timeout=120)
        if r.returncode != 0:
            _log(f'auto_rclone_size: rclone exited {r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'rclone size failed'}), 500)
        out = (r.stdout or '').strip()
        size = None
        if out:
            try:
                size = json_lib.loads(out)
            except Exception:
                size = out
        return jsonify({'path': path, 'size': size})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'rclone size timed out after 120s'}), 504)
    except Exception as e:
        _log(f'auto_rclone_size exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_rclone_298():
    """Storage quota/usage for a remote (rclone about <remote>: --json)."""
    body = _json_body()
    remote = body.get('remote')
    if not remote:
        return _missing_field(body, 'remote')
    remote = remote if remote.endswith(':') else remote + ':'
    exe = _find_tool('rclone')
    if not exe:
        return (jsonify({'error': 'rclone is not installed', 'hint': 'Install with: winget install Rclone.Rclone'}), 503)
    try:
        r = subprocess.run([exe, 'about', remote, '--json'], capture_output=True, text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'auto_rclone_about: rclone exited {r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'rclone about failed'}), 500)
        out = (r.stdout or '').strip()
        usage = None
        if out:
            try:
                usage = json_lib.loads(out)
            except Exception:
                usage = out
        return jsonify({'remote': remote, 'usage': usage})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'rclone about timed out'}), 504)
    except Exception as e:
        _log(f'auto_rclone_about exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_rclone_299():
    """One-way sync source to destination (rclone sync <src> <dst> [--dry-run]).

        Body (JSON):
            source (str, required): source path.
            destination (str, required): destination path.
            dry_run (bool, optional): preview changes without applying. Default false.
            extra_args (list[str], optional): additional rclone flags.
    """
    body = _json_body()
    source = body.get('source') or body.get('src')
    destination = body.get('destination') or body.get('dst')
    if not source:
        return _missing_field(body, 'source')
    if not destination:
        return _missing_field(body, 'destination')
    exe = _find_tool('rclone')
    if not exe:
        return (jsonify({'error': 'rclone is not installed', 'hint': 'Install with: winget install Rclone.Rclone'}), 503)
    args = ['sync', source, destination]
    if body.get('dry_run'):
        args.append('--dry-run')
    for a in body.get('extra_args') or []:
        args.append(str(a))
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, errors='replace', timeout=1800)
        return jsonify({'ok': r.returncode == 0, 'source': source, 'destination': destination,
                        'dry_run': bool(body.get('dry_run')),
                        'output': (r.stdout or '').strip()[-4000:],
                        'error_output': (r.stderr or '').strip()[-2000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'rclone sync timed out after 1800s'}), 504)
    except Exception as e:
        _log(f'auto_rclone_sync exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_rclone_300():
    """Copy files from source to destination (rclone copy <src> <dst>).

        Body (JSON):
            source (str, required): source path.
            destination (str, required): destination path.
            extra_args (list[str], optional): additional rclone flags.
    """
    body = _json_body()
    source = body.get('source') or body.get('src')
    destination = body.get('destination') or body.get('dst')
    if not source:
        return _missing_field(body, 'source')
    if not destination:
        return _missing_field(body, 'destination')
    exe = _find_tool('rclone')
    if not exe:
        return (jsonify({'error': 'rclone is not installed', 'hint': 'Install with: winget install Rclone.Rclone'}), 503)
    args = ['copy', source, destination]
    for a in body.get('extra_args') or []:
        args.append(str(a))
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, errors='replace', timeout=1800)
        return jsonify({'ok': r.returncode == 0, 'source': source, 'destination': destination,
                        'output': (r.stdout or '').strip()[-4000:],
                        'error_output': (r.stderr or '').strip()[-2000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'rclone copy timed out after 1800s'}), 504)
    except Exception as e:
        _log(f'auto_rclone_copy exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_rclone_301():
    """Integrity-check two paths (rclone check <src> <dst>).

        Body (JSON):
            source (str, required): source path.
            destination (str, required): destination path.
            download (bool, optional): check by downloading and hashing. Default false.
            extra_args (list[str], optional): additional rclone flags.
    """
    body = _json_body()
    source = body.get('source') or body.get('src')
    destination = body.get('destination') or body.get('dst')
    if not source:
        return _missing_field(body, 'source')
    if not destination:
        return _missing_field(body, 'destination')
    exe = _find_tool('rclone')
    if not exe:
        return (jsonify({'error': 'rclone is not installed', 'hint': 'Install with: winget install Rclone.Rclone'}), 503)
    args = ['check', source, destination]
    if body.get('download'):
        args.append('--download')
    for a in body.get('extra_args') or []:
        args.append(str(a))
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, errors='replace', timeout=600)
        return jsonify({'ok': r.returncode == 0, 'source': source, 'destination': destination,
                        'output': (r.stdout or '').strip()[-4000:],
                        'error_output': (r.stderr or '').strip()[-2000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'rclone check timed out after 600s'}), 504)
    except Exception as e:
        _log(f'auto_rclone_check exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _restic__build_env(params):
    """Build subprocess env from repository/password params (values never logged)."""
    env = dict(os.environ)
    repo = params.get('repository') or params.get('repo')
    password = params.get('password')
    password_file = params.get('password_file')
    if repo:
        env['RESTIC_REPOSITORY'] = repo
    if password:
        env['RESTIC_PASSWORD'] = password
    elif password_file:
        env['RESTIC_PASSWORD_FILE'] = password_file
    return env


def _h_restic_302():
    """List snapshots in the repository (restic snapshots --json).

        Query params:
            repository (str, optional): repo location (else RESTIC_REPOSITORY env).
            password (str, optional): repo password (else RESTIC_PASSWORD env).
            password_file (str, optional): path to a password file.
    """
    exe = _find_tool('restic')
    if not exe:
        return (jsonify({'error': 'restic is not installed', 'hint': 'Install with: winget install restic.restic'}), 503)
    env = _restic__build_env(request.args.to_dict())
    try:
        r = subprocess.run([exe, 'snapshots', '--json'], capture_output=True, text=True, errors='replace', timeout=60, env=env)
        if r.returncode != 0:
            _log(f'auto_restic_snapshots: restic exited {r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'restic snapshots failed'}), 500)
        out = (r.stdout or '').strip()
        snapshots = None
        if out:
            try:
                snapshots = json_lib.loads(out)
            except Exception:
                snapshots = out.splitlines()
        return jsonify({'count': len(snapshots) if isinstance(snapshots, list) else 0, 'snapshots': snapshots})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'restic snapshots timed out'}), 504)
    except Exception as e:
        _log(f'auto_restic_snapshots exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_restic_303():
    """Back up one or more paths into the repository (restic backup --json).

        Body (JSON):
            path (str) or paths (list[str]) (required): what to back up.
            repository (str, optional): repo location.
            password (str, optional): repo password.
            password_file (str, optional): path to a password file.
            tags (list[str], optional): snapshot tags.
            exclude (list[str], optional): glob patterns to exclude.
    """
    body = _json_body()
    paths = body.get('paths') or ([body['path']] if body.get('path') else None)
    if not paths:
        return _missing_field(body, 'path')
    if isinstance(paths, str):
        paths = [paths]
    exe = _find_tool('restic')
    if not exe:
        return (jsonify({'error': 'restic is not installed', 'hint': 'Install with: winget install restic.restic'}), 503)
    env = _restic__build_env(body)
    args = ['backup', '--json'] + [str(p) for p in paths]
    for t in body.get('tags') or []:
        args += ['--tag', str(t)]
    for e in body.get('exclude') or []:
        args += ['--exclude', str(e)]
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, errors='replace', timeout=1800, env=env)
        return jsonify({'ok': r.returncode == 0, 'paths': paths,
                        'output': (r.stdout or '').strip()[-8000:],
                        'error_output': (r.stderr or '').strip()[-2000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'restic backup timed out after 1800s'}), 504)
    except Exception as e:
        _log(f'auto_restic_backup exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_restic_304():
    """Restore a snapshot to a target directory (restic restore <id> --target <dir>).

        Body (JSON):
            snapshot (str, required): snapshot ID or "latest".
            target (str, required): directory to restore into.
            repository (str, optional): repo location.
            password (str, optional): repo password.
            password_file (str, optional): path to a password file.
            include (list[str], optional): paths to restore (default: all).
    """
    body = _json_body()
    snapshot = body.get('snapshot')
    target = body.get('target')
    if not snapshot:
        return _missing_field(body, 'snapshot')
    if not target:
        return _missing_field(body, 'target')
    exe = _find_tool('restic')
    if not exe:
        return (jsonify({'error': 'restic is not installed', 'hint': 'Install with: winget install restic.restic'}), 503)
    env = _restic__build_env(body)
    args = ['restore', str(snapshot), '--target', str(target)]
    for i in body.get('include') or []:
        args += ['--include', str(i)]
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, errors='replace', timeout=1800, env=env)
        return jsonify({'ok': r.returncode == 0, 'snapshot': snapshot, 'target': target,
                        'output': (r.stdout or '').strip()[-8000:],
                        'error_output': (r.stderr or '').strip()[-2000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'restic restore timed out after 1800s'}), 504)
    except Exception as e:
        _log(f'auto_restic_restore exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_restic_305():
    """Repository statistics (restic stats --json).

        Query params: repository, password, password_file (optional).
    """
    exe = _find_tool('restic')
    if not exe:
        return (jsonify({'error': 'restic is not installed', 'hint': 'Install with: winget install restic.restic'}), 503)
    env = _restic__build_env(request.args.to_dict())
    try:
        r = subprocess.run([exe, 'stats', '--json'], capture_output=True, text=True, errors='replace', timeout=120, env=env)
        if r.returncode != 0:
            _log(f'auto_restic_stats: restic exited {r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'restic stats failed'}), 500)
        out = (r.stdout or '').strip()
        stats = None
        if out:
            try:
                stats = json_lib.loads(out)
            except Exception:
                stats = out
        return jsonify({'stats': stats})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'restic stats timed out'}), 504)
    except Exception as e:
        _log(f'auto_restic_stats exception: {e}')
        return (jsonify({'error': str(e)}), 500)


def _h_restic_306():
    """Initialize a new repository (restic init).

        Body (JSON):
            repository (str, required): repo location to initialize.
            password (str, required): new repository password.
    """
    body = _json_body()
    repository = body.get('repository')
    password = body.get('password')
    if not repository:
        return _missing_field(body, 'repository')
    if not password:
        return _missing_field(body, 'password')
    exe = _find_tool('restic')
    if not exe:
        return (jsonify({'error': 'restic is not installed', 'hint': 'Install with: winget install restic.restic'}), 503)
    env = _restic__build_env(body)
    try:
        r = subprocess.run([exe, 'init'], capture_output=True, text=True, errors='replace', timeout=60, env=env)
        return jsonify({'ok': r.returncode == 0,
                        'output': (r.stdout or '').strip(),
                        'error_output': (r.stderr or '').strip()[-2000:]})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'restic init timed out'}), 504)
    except Exception as e:
        _log(f'auto_restic_init exception: {e}')
        return (jsonify({'error': str(e)}), 500)


# ---- miller (mlr) action handlers ----

_MILLER_FORMATS = ('csv', 'tsv', 'json', 'dkvp', 'pprint', 'nidx', 'xtab', 'markdown')


def _miller__resolve_input(body):
    """Return (data_str_or_None, path_or_None, error_response_or_None)."""
    data = body.get('data')
    path = str(body.get('path') or '').strip()
    if data is None and not path:
        return None, None, _missing_field(body, 'data')
    if path and not os.path.isfile(path):
        return None, None, (jsonify({'error': f'File not found: {path}'}), 404)
    return data, path, None


def _miller__build_cmd(exe, in_fmt, out_fmt, verb_args, path):
    if in_fmt not in _MILLER_FORMATS or out_fmt not in _MILLER_FORMATS:
        return None, (jsonify({'error': f'Invalid format. Allowed: {", ".join(_MILLER_FORMATS)}'}), 400)
    cmd = [exe, f'--i{in_fmt}', f'--o{out_fmt}'] + verb_args
    if path:
        cmd.append(path)
    return cmd, None


def _h_miller_307():
    """Convert tabular data between formats (CSV/TSV/JSON/DKVP/...).

        Body (JSON):
            data (str, optional): inline input text (CSV/TSV/JSON/...).
            path (str, optional): path to an input file instead of `data`.
            input_format (str, optional): csv|tsv|json|dkvp|pprint|nidx|xtab|markdown. Default csv.
            output_format (str, optional): same set. Default json.
    """
    body = _json_body()
    data, path, err = _miller__resolve_input(body)
    if err:
        return err
    exe = _find_tool('miller')
    if not exe:
        return (jsonify({'error': 'miller is not installed', 'hint': 'winget install Miller.Miller'}), 503)
    in_fmt = str(body.get('input_format') or 'csv').strip().lower()
    out_fmt = str(body.get('output_format') or 'json').strip().lower()
    cmd, err = _miller__build_cmd(exe, in_fmt, out_fmt, [], path)
    if err:
        return err
    try:
        r = subprocess.run(cmd, input=None if path else str(data), capture_output=True,
                           text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'[miller convert] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'miller convert failed'}), 500)
        return jsonify({'ok': True, 'output_format': out_fmt, 'output': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'miller convert timed out'}), 504)
    except Exception as e:
        _log(f'[miller convert] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_miller_308():
    """Compute summary statistics for a named column.

        Body (JSON):
            field (str, required): column name to summarize.
            data (str, optional): inline input text.
            path (str, optional): input file path.
            input_format (str, optional): default csv.
            aggregators (str, optional): comma list e.g. count,mean,min,max,sum.
                Default count,mean,min,max,sum.
    """
    body = _json_body()
    field = str(body.get('field') or '').strip()
    if not field:
        return _missing_field(body, 'field')
    data, path, err = _miller__resolve_input(body)
    if err:
        return err
    exe = _find_tool('miller')
    if not exe:
        return (jsonify({'error': 'miller is not installed', 'hint': 'winget install Miller.Miller'}), 503)
    in_fmt = str(body.get('input_format') or 'csv').strip().lower()
    agg = str(body.get('aggregators') or 'count,mean,min,max,sum').strip()
    cmd, err = _miller__build_cmd(exe, in_fmt, 'json', ['stats1', '-a', agg, '-f', field], path)
    if err:
        return err
    try:
        r = subprocess.run(cmd, input=None if path else str(data), capture_output=True,
                           text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'[miller stats] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'miller stats failed'}), 500)
        return jsonify({'ok': True, 'field': field, 'aggregators': agg, 'output': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'miller stats timed out'}), 504)
    except Exception as e:
        _log(f'[miller stats] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_miller_309():
    """Run an arbitrary Miller verb chain against inline data or a file.

        Body (JSON):
            verbs (str, required): Miller verb chain, e.g. "cut -f a,b then sort -f a".
            data (str, optional): inline input text.
            path (str, optional): input file path.
            input_format (str, optional): default csv.
            output_format (str, optional): default json.
    """
    body = _json_body()
    verbs = str(body.get('verbs') or '').strip()
    if not verbs:
        return _missing_field(body, 'verbs')
    data, path, err = _miller__resolve_input(body)
    if err:
        return err
    exe = _find_tool('miller')
    if not exe:
        return (jsonify({'error': 'miller is not installed', 'hint': 'winget install Miller.Miller'}), 503)
    in_fmt = str(body.get('input_format') or 'csv').strip().lower()
    out_fmt = str(body.get('output_format') or 'json').strip().lower()
    try:
        verb_args = shlex.split(verbs)
    except ValueError as e:
        return (jsonify({'error': f'Invalid verbs string: {e}'}), 400)
    if not verb_args:
        return (jsonify({'error': 'verbs string parsed to nothing'}), 400)
    cmd, err = _miller__build_cmd(exe, in_fmt, out_fmt, verb_args, path)
    if err:
        return err
    try:
        r = subprocess.run(cmd, input=None if path else str(data), capture_output=True,
                           text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'[miller process] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'miller process failed'}), 500)
        return jsonify({'ok': True, 'output': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'miller process timed out'}), 504)
    except Exception as e:
        _log(f'[miller process] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


# ---- tokei action handlers ----

def _h_tokei_310():
    """Count lines of code in a path, grouped by language.

        Body (JSON):
            path (str, required): file or directory to analyze.
            exclude (str, optional): glob pattern to ignore.
            sort (str, optional): files|lines|blanks|code|comments.
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    if not os.path.exists(path):
        return (jsonify({'error': f'Path not found: {path}'}), 404)
    exe = _find_tool('tokei')
    if not exe:
        return (jsonify({'error': 'tokei is not installed', 'hint': 'winget install XAMPPRocky.tokei'}), 503)
    cmd = [exe, path, '--output', 'json']
    exclude = str(body.get('exclude') or '').strip()
    if exclude:
        cmd += ['--exclude', exclude]
    sort = str(body.get('sort') or '').strip().lower()
    if sort in ('files', 'lines', 'blanks', 'code', 'comments'):
        cmd += ['--sort', sort]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=120)
        if r.returncode != 0:
            _log(f'[tokei count] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'tokei count failed'}), 500)
        try:
            stats = json_lib.loads(r.stdout)
        except Exception:
            stats = r.stdout
        return jsonify({'ok': True, 'path': path, 'stats': stats})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'tokei count timed out'}), 504)
    except Exception as e:
        _log(f'[tokei count] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_tokei_311():
    """List the programming languages tokei recognizes."""
    exe = _find_tool('tokei')
    if not exe:
        return (jsonify({'error': 'tokei is not installed', 'hint': 'winget install XAMPPRocky.tokei'}), 503)
    try:
        r = subprocess.run([exe, '--languages'], capture_output=True, text=True, errors='replace', timeout=30)
        if r.returncode != 0:
            _log(f'[tokei languages] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'tokei languages failed'}), 500)
        langs = [ln.strip() for ln in (r.stdout or '').splitlines() if ln.strip()]
        return jsonify({'ok': True, 'count': len(langs), 'languages': langs})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'tokei languages timed out'}), 504)
    except Exception as e:
        _log(f'[tokei languages] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_tokei_312():
    """Per-file code statistics for a directory.

        Body (JSON):
            path (str, required): directory to analyze.
            exclude (str, optional): glob pattern to ignore.
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    if not os.path.isdir(path):
        return (jsonify({'error': f'Not a directory: {path}'}), 404)
    exe = _find_tool('tokei')
    if not exe:
        return (jsonify({'error': 'tokei is not installed', 'hint': 'winget install XAMPPRocky.tokei'}), 503)
    cmd = [exe, path, '--files', '--output', 'json']
    exclude = str(body.get('exclude') or '').strip()
    if exclude:
        cmd += ['--exclude', exclude]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=120)
        if r.returncode != 0:
            _log(f'[tokei files] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'tokei files failed'}), 500)
        try:
            stats = json_lib.loads(r.stdout)
        except Exception:
            stats = r.stdout
        return jsonify({'ok': True, 'path': path, 'stats': stats})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'tokei files timed out'}), 504)
    except Exception as e:
        _log(f'[tokei files] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_jc_313():
    """Convert raw command output (or a full command) to JSON/YAML via jc.

        Body (JSON):
            data (str, optional): raw text output to parse (sent to stdin).
            command (str, optional): full command to run via jc magic syntax
                (e.g. "ipconfig"). One of `data` or `command` is required.
            parser (str, optional): jc parser name (e.g. ipconfig, netstat,
                systeminfo, ls, df). If omitted, jc auto-detects when possible.
            pretty (bool, optional): pretty-print output. Default true.
            yaml (bool, optional): emit YAML instead of JSON. Default false.
    """
    body = _json_body()
    data = body.get('data')
    command = str(body.get('command') or '').strip()
    if data is None and not command:
        return _missing_field(body, 'data')
    parser = str(body.get('parser') or '').strip()
    pretty = bool(body.get('pretty', True))
    yaml = bool(body.get('yaml', False))
    exe = _find_tool('jc')
    if not exe:
        return (jsonify({'error': 'jc is not installed', 'hint': 'pip install jc  OR  winget install KellyBrazil.jc'}), 503)
    cmd = [exe]
    if pretty:
        cmd.append('-p')
    if yaml:
        cmd.append('-y')
    if parser:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", parser):
            return (jsonify({"error": f"invalid jc parser: {parser}"}), 400)
        cmd.append(parser)
    if command:
        cmd += shlex.split(command)
    try:
        r = subprocess.run(cmd, input=None if command else str(data),
                           capture_output=True, text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'[jc parse] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'jc parse failed'}), 500)
        out = r.stdout
        if not yaml:
            try:
                out = json_lib.loads(out)
            except Exception:
                pass
        return jsonify({'ok': True, 'parser': parser or 'auto', 'output': out})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'jc parse timed out'}), 504)
    except Exception as e:
        _log(f'[jc parse] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_jc_314():
    """List all jc parsers available on this system."""
    exe = _find_tool('jc')
    if not exe:
        return (jsonify({'error': 'jc is not installed', 'hint': 'pip install jc  OR  winget install KellyBrazil.jc'}), 503)
    try:
        r = subprocess.run([exe, '--about'], capture_output=True, text=True, errors='replace', timeout=30)
        if r.returncode != 0:
            _log(f'[jc parsers] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'jc --about failed'}), 500)
        return jsonify({'ok': True, 'about': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'jc parsers timed out'}), 504)
    except Exception as e:
        _log(f'[jc parsers] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_ruff_315():
    """Lint a file or directory with ruff.

        Body (JSON):
            path (str, required): file or directory to lint.
            fix (bool, optional): auto-fix violations. Default false.
            select (str, optional): comma-separated rule codes to limit to.
            output_format (str, optional): json|text|github|gitlab|grouped. Default json.
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('ruff')
    if not exe:
        return (jsonify({'error': 'ruff is not installed', 'hint': 'pip install ruff  OR  winget install astral-sh.ruff'}), 503)
    fmt = str(body.get('output_format') or 'json').strip().lower()
    cmd = [exe, 'check', path, '--output-format', fmt]
    if body.get('fix'):
        cmd.append('--fix')
    sel = str(body.get('select') or '').strip()
    if sel:
        cmd += ['--select', sel]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=120)
        # ruff returns rc=1 when violations are found; that's a valid result, not an error
        if r.returncode not in (0, 1):
            _log(f'[ruff check] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'ruff check failed'}), 500)
        out = r.stdout
        if fmt == 'json':
            try:
                out = json_lib.loads(out)
            except Exception:
                pass
        return jsonify({'ok': True, 'path': path, 'violations': out,
                        'count': len(out) if isinstance(out, list) else None})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'ruff check timed out'}), 504)
    except Exception as e:
        _log(f'[ruff check] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_ruff_316():
    """Format a file or directory with ruff.

        Body (JSON):
            path (str, required): file or directory to format.
            check (bool, optional): don't write; just report what would change. Default false.
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('ruff')
    if not exe:
        return (jsonify({'error': 'ruff is not installed', 'hint': 'pip install ruff  OR  winget install astral-sh.ruff'}), 503)
    cmd = [exe, 'format', path]
    if body.get('check'):
        cmd.append('--check')
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=120)
        if r.returncode not in (0, 1):
            _log(f'[ruff format] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'ruff format failed'}), 500)
        return jsonify({'ok': True, 'path': path, 'check': bool(body.get('check')),
                        'would_reformat': r.returncode == 1, 'output': (r.stdout or r.stderr).strip()})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'ruff format timed out'}), 504)
    except Exception as e:
        _log(f'[ruff format] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_ruff_317():
    """Explain a lint rule by its code (e.g. E501, F401, B008).

        Query params:
            code (str, required): rule code to explain.
    """
    code = str(request.args.get('code') or '').strip()
    if not code:
        code = str(_json_body().get('code') or '').strip()
    if not code:
        return _missing_field({'code': ''}, 'code')
    if not re.fullmatch(r"[A-Z]+\d+", code):
        return (jsonify({"error": f"invalid ruff rule code: {code}"}), 400)
    exe = _find_tool('ruff')
    if not exe:
        return (jsonify({'error': 'ruff is not installed', 'hint': 'pip install ruff  OR  winget install astral-sh.ruff'}), 503)
    try:
        r = subprocess.run([exe, 'rule', code], capture_output=True, text=True, errors='replace', timeout=30)
        if r.returncode != 0:
            _log(f'[ruff rule] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'ruff rule failed'}), 500)
        return jsonify({'ok': True, 'code': code, 'explanation': r.stdout})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'ruff rule timed out'}), 504)
    except Exception as e:
        _log(f'[ruff rule] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_mise_318():
    """List tools and versions managed by mise.

        Query params:
            json (bool, optional): machine-readable output. Default true.
    """
    exe = _find_tool('mise')
    if not exe:
        return (jsonify({'error': 'mise is not installed', 'hint': 'scoop install mise  OR  winget install jdx.mise'}), 503)
    as_json = str(request.args.get('json', 'true')).lower() != 'false'
    cmd = [exe, 'ls', '--json'] if as_json else [exe, 'ls']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=30)
        if r.returncode != 0:
            _log(f'[mise list] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'mise ls failed'}), 500)
        out = r.stdout
        if as_json:
            try:
                out = json_lib.loads(out)
            except Exception:
                pass
        return jsonify({'ok': True, 'tools': out})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'mise ls timed out'}), 504)
    except Exception as e:
        _log(f'[mise list] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_mise_319():
    """Show the active tool versions for the current directory scope."""
    exe = _find_tool('mise')
    if not exe:
        return (jsonify({'error': 'mise is not installed', 'hint': 'scoop install mise  OR  winget install jdx.mise'}), 503)
    cwd = str(request.args.get('cwd') or '').strip() or None
    try:
        r = subprocess.run([exe, 'current', '--json'], capture_output=True, text=True, errors='replace', timeout=30, cwd=cwd)
        if r.returncode != 0:
            r2 = subprocess.run([exe, 'current'], capture_output=True, text=True, errors='replace', timeout=30, cwd=cwd)
            if r2.returncode != 0:
                _log(f'[mise current] rc={r2.returncode}: {r2.stderr[:300]}')
                return (jsonify({'error': r2.stderr.strip() or 'mise current failed'}), 500)
            return jsonify({'ok': True, 'current': r2.stdout})
        out = r.stdout
        try:
            out = json_lib.loads(out)
        except Exception:
            pass
        return jsonify({'ok': True, 'current': out})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'mise current timed out'}), 504)
    except Exception as e:
        _log(f'[mise current] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_mise_320():
    """List tasks defined in the current mise config (mise.toml / .mise.toml).

        Query params:
            cwd (str, optional): directory containing the config.
    """
    exe = _find_tool('mise')
    if not exe:
        return (jsonify({'error': 'mise is not installed', 'hint': 'scoop install mise  OR  winget install jdx.mise'}), 503)
    cwd = str(request.args.get('cwd') or '').strip() or None
    try:
        r = subprocess.run([exe, 'tasks', 'ls', '--json'], capture_output=True, text=True, errors='replace', timeout=30, cwd=cwd)
        if r.returncode != 0:
            r2 = subprocess.run([exe, 'tasks', 'ls'], capture_output=True, text=True, errors='replace', timeout=30, cwd=cwd)
            if r2.returncode != 0:
                _log(f'[mise tasks] rc={r2.returncode}: {r2.stderr[:300]}')
                return (jsonify({'error': r2.stderr.strip() or 'mise tasks ls failed'}), 500)
            return jsonify({'ok': True, 'tasks': r2.stdout})
        out = r.stdout
        try:
            out = json_lib.loads(out)
        except Exception:
            pass
        return jsonify({'ok': True, 'tasks': out})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'mise tasks timed out'}), 504)
    except Exception as e:
        _log(f'[mise tasks] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_mise_321():
    """Run a command under a specific tool version via mise exec.

        Body (JSON):
            command (str, required): tool@version plus the command to run, e.g.
                "node@20 -- node -v" or "python@3.11 -- python script.py".
            cwd (str, optional): working directory.
    """
    body = _json_body()
    command = str(body.get('command') or '').strip()
    if not command:
        return _missing_field(body, 'command')
    exe = _find_tool('mise')
    if not exe:
        return (jsonify({'error': 'mise is not installed', 'hint': 'scoop install mise  OR  winget install jdx.mise'}), 503)
    cwd = str(body.get('cwd') or '').strip() or None
    try:
        cmd = [exe, 'exec'] + shlex.split(command)
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=300, cwd=cwd)
        return jsonify({'ok': r.returncode == 0, 'returncode': r.returncode,
                        'stdout': r.stdout, 'stderr': r.stderr})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'mise exec timed out'}), 504)
    except Exception as e:
        _log(f'[mise exec] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_mise_322():
    """Run a named task defined in the current mise config.

        Body (JSON):
            task (str, required): task name to run.
            cwd (str, optional): directory containing the config.
    """
    body = _json_body()
    task = str(body.get('task') or '').strip()
    if not task:
        return _missing_field(body, 'task')
    exe = _find_tool('mise')
    if not exe:
        return (jsonify({'error': 'mise is not installed', 'hint': 'scoop install mise  OR  winget install jdx.mise'}), 503)
    cwd = str(body.get('cwd') or '').strip() or None
    try:
        r = subprocess.run([exe, 'run', task], capture_output=True, text=True, errors='replace', timeout=600, cwd=cwd)
        return jsonify({'ok': r.returncode == 0, 'returncode': r.returncode,
                        'stdout': r.stdout, 'stderr': r.stderr})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'mise run timed out'}), 504)
    except Exception as e:
        _log(f'[mise run] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_shellcheck_323():
    """Lint a shell script (provided as text) with ShellCheck.

        Body (JSON):
            script (str, required): shell script source to lint.
            shell (str, optional): shell dialect: sh|bash|dash|ksh. Default auto-detect.
            format (str, optional): json1|json|checkstyle|gcc|tty. Default json1.
            severity (str, optional): minimum severity: error|warning|info|style.
    """
    body = _json_body()
    script = body.get('script')
    if script is None:
        return _missing_field(body, 'script')
    exe = _find_tool('shellcheck')
    if not exe:
        return (jsonify({'error': 'shellcheck is not installed', 'hint': 'scoop install shellcheck  OR  winget install koalaman.shellcheck'}), 503)
    fmt = str(body.get('format') or 'json1').strip()
    shell = str(body.get('shell') or '').strip()
    severity = str(body.get('severity') or '').strip()
    cmd = [exe, '-f', fmt]
    if shell:
        cmd += ['-s', shell]
    if severity:
        cmd += ['-S', severity]
    cmd.append('-')
    try:
        r = subprocess.run(cmd, input=str(script), capture_output=True, text=True, errors='replace', timeout=60)
        # shellcheck returns rc=1 when issues are found; that is a valid result
        if r.returncode not in (0, 1):
            _log(f'[shellcheck check] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'shellcheck failed'}), 500)
        out = r.stdout
        if fmt in ('json', 'json1'):
            try:
                out = json_lib.loads(out)
            except Exception:
                pass
        count = len(out.get('comments', [])) if isinstance(out, dict) else (len(out) if isinstance(out, list) else None)
        return jsonify({'ok': True, 'format': fmt, 'issues': out, 'count': count})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'shellcheck timed out'}), 504)
    except Exception as e:
        _log(f'[shellcheck check] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_shellcheck_324():
    """Lint a shell script file by path.

        Body (JSON):
            path (str, required): path to the script to lint.
            format (str, optional): json1|json|checkstyle|gcc|tty. Default json1.
            shell (str, optional): shell dialect: sh|bash|dash|ksh.
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('shellcheck')
    if not exe:
        return (jsonify({'error': 'shellcheck is not installed', 'hint': 'scoop install shellcheck  OR  winget install koalaman.shellcheck'}), 503)
    if not os.path.isfile(path):
        return (jsonify({'error': f'file not found: {path}'}), 400)
    fmt = str(body.get('format') or 'json1').strip()
    shell = str(body.get('shell') or '').strip()
    cmd = [exe, '-f', fmt]
    if shell:
        cmd += ['-s', shell]
    cmd.append(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=60)
        if r.returncode not in (0, 1):
            _log(f'[shellcheck file] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'shellcheck failed'}), 500)
        out = r.stdout
        if fmt in ('json', 'json1'):
            try:
                out = json_lib.loads(out)
            except Exception:
                pass
        count = len(out.get('comments', [])) if isinstance(out, dict) else (len(out) if isinstance(out, list) else None)
        return jsonify({'ok': True, 'path': path, 'format': fmt, 'issues': out, 'count': count})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'shellcheck timed out'}), 504)
    except Exception as e:
        _log(f'[shellcheck file] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_dust_325():
    """Analyze disk usage of a path and return a JSON tree.

        Body (JSON):
            path (str, required): directory to analyze.
            depth (int, optional): max directory depth to recurse.
            min_size (str, optional): only include entries larger than this (e.g. '30MB').
            apparent (bool, optional): use apparent size (file length) instead of disk usage.
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('dust')
    if not exe:
        return (jsonify({'error': 'dust is not installed', 'hint': 'scoop install dust  OR  winget install bootandy.dust'}), 503)
    if not os.path.isdir(path):
        return (jsonify({'error': f'directory not found: {path}'}), 400)
    cmd = [exe, '-j', '-P']
    if body.get('apparent'):
        cmd.append('-s')
    depth = body.get('depth')
    if depth is not None:
        try:
            cmd += ['-d', str(int(depth))]
        except (TypeError, ValueError):
            pass
    min_size = str(body.get('min_size') or '').strip()
    if min_size:
        cmd += ['-z', min_size]
    cmd.append(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=120)
        if r.returncode != 0:
            _log(f'[dust usage] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'dust failed'}), 500)
        out = r.stdout.strip()
        try:
            data = json_lib.loads(out)
        except Exception:
            data = out
        return jsonify({'ok': True, 'path': path, 'tree': data})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'dust timed out'}), 504)
    except Exception as e:
        _log(f'[dust usage] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_dust_326():
    """Return the N largest files/directories under a path as JSON.

        Body (JSON):
            path (str, required): directory to scan.
            count (int, optional): number of largest entries to return (default 10).
            apparent (bool, optional): use apparent size instead of disk usage.
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('dust')
    if not exe:
        return (jsonify({'error': 'dust is not installed', 'hint': 'scoop install dust  OR  winget install bootandy.dust'}), 503)
    if not os.path.isdir(path):
        return (jsonify({'error': f'directory not found: {path}'}), 400)
    try:
        count = max(1, int(body.get('count') or 10))
    except (TypeError, ValueError):
        count = 10
    cmd = [exe, '-j', '-P', '-n', str(count)]
    if body.get('apparent'):
        cmd.append('-s')
    cmd.append(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=120)
        if r.returncode != 0:
            _log(f'[dust largest] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'dust failed'}), 500)
        out = r.stdout.strip()
        try:
            data = json_lib.loads(out)
        except Exception:
            data = out
        return jsonify({'ok': True, 'path': path, 'count': count, 'entries': data})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'dust timed out'}), 504)
    except Exception as e:
        _log(f'[dust largest] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_onefetch_327():
    """Return full Git repository metadata as JSON.

        Body (JSON):
            path (str, required): path to the repository (a directory containing .git).
            output (str, optional): json|yaml. Default json.
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('onefetch')
    if not exe:
        return (jsonify({'error': 'onefetch is not installed', 'hint': 'scoop install onefetch  OR  winget install o2sh.onefetch'}), 503)
    if not os.path.isdir(os.path.join(path, '.git')) and not os.path.isfile(os.path.join(path, '.git')):
        return (jsonify({'error': f'not a git repository: {path}'}), 400)
    fmt = str(body.get('output') or 'json').strip().lower()
    if fmt not in ('json', 'yaml'):
        fmt = 'json'
    try:
        r = subprocess.run([exe, '--output', fmt, path], capture_output=True, text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'[onefetch repo] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'onefetch failed'}), 500)
        out = r.stdout.strip()
        data = out
        if fmt == 'json':
            try:
                data = json_lib.loads(out)
            except Exception:
                pass
        return jsonify({'ok': True, 'path': path, 'output': fmt, 'repo': data})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'onefetch timed out'}), 504)
    except Exception as e:
        _log(f'[onefetch repo] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_onefetch_328():
    """Return the language breakdown of a Git repository.

        Body (JSON):
            path (str, required): path to the repository (a directory containing .git).
    """
    def _walk_langs(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, list) and 'lang' in k.lower():
                    if v and all(isinstance(x, dict) for x in v):
                        return v
                found = _walk_langs(v)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for x in node:
                found = _walk_langs(x)
                if found is not None:
                    return found
        return None

    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('onefetch')
    if not exe:
        return (jsonify({'error': 'onefetch is not installed', 'hint': 'scoop install onefetch  OR  winget install o2sh.onefetch'}), 503)
    if not os.path.isdir(os.path.join(path, '.git')) and not os.path.isfile(os.path.join(path, '.git')):
        return (jsonify({'error': f'not a git repository: {path}'}), 400)
    try:
        r = subprocess.run([exe, '--output', 'json', path], capture_output=True, text=True, errors='replace', timeout=60)
        if r.returncode != 0:
            _log(f'[onefetch languages] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'onefetch failed'}), 500)
        out = r.stdout.strip()
        try:
            data = json_lib.loads(out)
        except Exception:
            data = out
        langs = _walk_langs(data)
        return jsonify({'ok': True, 'path': path, 'languages': langs if langs is not None else data})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'onefetch timed out'}), 504)
    except Exception as e:
        _log(f'[onefetch languages] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _strip_ansi(text):
    """Remove ANSI escape sequences from terminal output."""
    return re.sub(r'\x1b\[[0-9;?]*[ -/]*[@-~]', '', text or '')


def _h_nushell_329():
    """Run a Nushell script string via `nu -c`.

        Body (JSON):
            code (str, required): the Nushell script/expression to evaluate.
            timeout (int, optional): seconds (default 30, max 120).
    """
    body = _json_body()
    code = str(body.get('code') or '').strip()
    if not code:
        return _missing_field(body, 'code')
    exe = _find_tool('nushell')
    if not exe:
        return (jsonify({'error': 'nushell is not installed', 'hint': 'winget install nushell.nushell  OR  scoop install nu'}), 503)
    timeout = int(body.get('timeout') or 30)
    timeout = max(1, min(timeout, 120))
    try:
        r = subprocess.run([exe, '-c', code], capture_output=True, text=True, errors='replace', timeout=timeout)
        return jsonify({
            'ok': r.returncode == 0,
            'code': code,
            'exit_code': r.returncode,
            'stdout': r.stdout,
            'stderr': r.stderr,
        })
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'nushell timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[nushell eval] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_nushell_330():
    """Run a .nu script file.

        Body (JSON):
            path (str, required): path to a .nu script.
            timeout (int, optional): seconds (default 30, max 120).
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    exe = _find_tool('nushell')
    if not exe:
        return (jsonify({'error': 'nushell is not installed', 'hint': 'winget install nushell.nushell  OR  scoop install nu'}), 503)
    if not os.path.isfile(path):
        return (jsonify({'error': f'script not found: {path}'}), 404)
    timeout = int(body.get('timeout') or 30)
    timeout = max(1, min(timeout, 120))
    try:
        r = subprocess.run([exe, path], capture_output=True, text=True, errors='replace', timeout=timeout)
        return jsonify({
            'ok': r.returncode == 0,
            'path': path,
            'exit_code': r.returncode,
            'stdout': r.stdout,
            'stderr': r.stderr,
        })
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'nushell timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[nushell script] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _h_nushell_331():
    """Run a Nushell expression and return the result as JSON.

        Appends `| to json` automatically unless the code already produces
        JSON, so the result is machine-readable.

        Body (JSON):
            code (str, required): the Nushell expression to evaluate.
            timeout (int, optional): seconds (default 30, max 120).
    """
    body = _json_body()
    code = str(body.get('code') or '').strip()
    if not code:
        return _missing_field(body, 'code')
    exe = _find_tool('nushell')
    if not exe:
        return (jsonify({'error': 'nushell is not installed', 'hint': 'winget install nushell.nushell  OR  scoop install nu'}), 503)
    timeout = int(body.get('timeout') or 30)
    timeout = max(1, min(timeout, 120))
    if 'to json' not in code and 'to nuon' not in code and 'to jsonl' not in code:
        code = f'{code} | to json'
    try:
        r = subprocess.run([exe, '-c', code], capture_output=True, text=True, errors='replace', timeout=timeout)
        if r.returncode != 0:
            _log(f'[nushell query] rc={r.returncode}: {r.stderr[:300]}')
            return (jsonify({'error': r.stderr.strip() or 'nushell failed'}), 500)
        out = r.stdout.strip()
        try:
            data = json_lib.loads(out)
        except Exception:
            data = out
        return jsonify({'ok': True, 'code': code, 'result': data})
    except subprocess.TimeoutExpired:
        return (jsonify({'error': f'nushell timed out after {timeout}s'}), 504)
    except Exception as e:
        _log(f'[nushell query] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def _glow_render_file(path, width, style):
    """Render a Markdown file with glow; returns (styled_text, plain_text)."""
    exe = _find_tool('glow')
    if not exe:
        return None, None
    args = [exe]
    if width:
        args += ['-w', str(int(width))]
    if style:
        args += ['-s', str(style)]
    args.append(path)
    r = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or 'glow failed')
    return r.stdout, _strip_ansi(r.stdout)


def _h_glow_332():
    """Render Markdown (string or file) to styled terminal text.

        Body (JSON):
            text (str, optional): raw Markdown string to render.
            path (str, optional): path to a Markdown file.
            width (int, optional): word-wrap width (default 80).
            style (str, optional): dark|light|auto (default auto).
            strip_ansi (bool, optional): strip ANSI color codes (default false).

        One of `text` or `path` is required.
    """
    body = _json_body()
    text = str(body.get('text') or '').strip()
    path = str(body.get('path') or '').strip()
    if not text and not path:
        return (jsonify({'error': 'provide either `text` or `path`'}), 400)
    width = int(body.get('width') or 80)
    style = str(body.get('style') or 'auto').strip().lower()
    if style not in ('dark', 'light', 'auto'):
        style = 'auto'
    strip_ansi = bool(body.get('strip_ansi', False))
    tmp = None
    try:
        if text:
            fd, tmp = tempfile.mkstemp(suffix='.md')
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(text)
            path = tmp
        styled, plain = _glow_render_file(path, width, style)
        if styled is None:
            return (jsonify({'error': 'glow is not installed', 'hint': 'winget install charmbracelet.glow  OR  scoop install glow'}), 503)
        return jsonify({
            'ok': True,
            'markdown_len': len(text),
            'width': width,
            'style': style,
            'output': plain if strip_ansi else styled,
        })
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'glow timed out'}), 504)
    except Exception as e:
        _log(f'[glow render] {str(e)}')
        return (jsonify({'error': str(e)}), 500)
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _h_glow_333():
    """Render a Markdown file by path to styled terminal text.

        Body (JSON):
            path (str, required): path to a Markdown file.
            width (int, optional): word-wrap width (default 80).
            style (str, optional): dark|light|auto (default auto).
            strip_ansi (bool, optional): strip ANSI color codes (default false).
    """
    body = _json_body()
    path = str(body.get('path') or '').strip()
    if not path:
        return _missing_field(body, 'path')
    if not os.path.isfile(path):
        return (jsonify({'error': f'file not found: {path}'}), 404)
    width = int(body.get('width') or 80)
    style = str(body.get('style') or 'auto').strip().lower()
    if style not in ('dark', 'light', 'auto'):
        style = 'auto'
    strip_ansi = bool(body.get('strip_ansi', False))
    try:
        styled, plain = _glow_render_file(path, width, style)
        if styled is None:
            return (jsonify({'error': 'glow is not installed', 'hint': 'winget install charmbracelet.glow  OR  scoop install glow'}), 503)
        return jsonify({
            'ok': True,
            'path': path,
            'width': width,
            'style': style,
            'output': plain if strip_ansi else styled,
        })
    except subprocess.TimeoutExpired:
        return (jsonify({'error': 'glow timed out'}), 504)
    except Exception as e:
        _log(f'[glow render_file] {str(e)}')
        return (jsonify({'error': str(e)}), 500)


def register_routes(app, state, require_auth):
    global _STATE
    _STATE = state
    for _tool in TOOLS:
        _register_generic(app, require_auth, _tool)
    _ACTIONS = [
        ('/auto/aider/run', ['POST'], _h_aider_0),
        ('/auto/autohotkey/run', ['POST'], _h_autohotkey_1),
        ('/auto/autohotkey/compile', ['POST'], _h_autohotkey_2),
        ('/auto/bat/cat', ['POST'], _h_bat_3),
        ('/auto/bat/languages', ['GET'], _h_bat_4),
        ('/auto/bat/themes', ['GET'], _h_bat_5),
        ('/auto/bitsadmin/jobs', ['GET'], _h_bitsadmin_6),
        ('/auto/bitsadmin/job/info', ['POST'], _h_bitsadmin_7),
        ('/auto/bitsadmin/job/create', ['POST'], _h_bitsadmin_8),
        ('/auto/bitsadmin/job/add_file', ['POST'], _h_bitsadmin_9),
        ('/auto/bitsadmin/job/resume', ['POST'], _h_bitsadmin_10),
        ('/auto/bitsadmin/job/suspend', ['POST'], _h_bitsadmin_11),
        ('/auto/bitsadmin/job/cancel', ['POST'], _h_bitsadmin_12),
        ('/auto/bitsadmin/job/complete', ['POST'], _h_bitsadmin_13),
        ('/auto/bitsadmin/job/files', ['POST'], _h_bitsadmin_14),
        ('/auto/bitsadmin/monitor', ['GET'], _h_bitsadmin_15),
        ('/auto/bitsadmin/reset', ['POST'], _h_bitsadmin_16),
        ('/auto/bitsadmin/cache/info', ['GET'], _h_bitsadmin_17),
        ('/auto/bitsadmin/cache/delete', ['POST'], _h_bitsadmin_18),
        ('/auto/bitsadmin/peers/list', ['GET'], _h_bitsadmin_19),
        ('/auto/certutil/hash', ['POST'], _h_certutil_20),
        ('/auto/certutil/encode', ['POST'], _h_certutil_21),
        ('/auto/certutil/decode', ['POST'], _h_certutil_22),
        ('/auto/certutil/store', ['GET'], _h_certutil_23),
        ('/auto/certutil/csr', ['POST'], _h_certutil_24),
        ('/auto/chkdsk/scan', ['POST'], _h_chkdsk_25),
        ('/auto/chkdsk/repair', ['POST'], _h_chkdsk_26),
        ('/auto/chkdsk/thorough', ['POST'], _h_chkdsk_27),
        ('/auto/chkdsk/force-dismount', ['POST'], _h_chkdsk_28),
        ('/auto/chkdsk/schedule', ['POST'], _h_chkdsk_29),
        ('/auto/chkdsk/volumes', ['GET'], _h_chkdsk_30),
        ('/auto/choco/search', ['POST'], _h_choco_31),
        ('/auto/choco/list', ['GET'], _h_choco_32),
        ('/auto/choco/install', ['POST'], _h_choco_33),
        ('/auto/choco/upgrade', ['POST'], _h_choco_34),
        ('/auto/choco/uninstall', ['POST'], _h_choco_35),
        ('/auto/choco/outdated', ['GET'], _h_choco_36),
        ('/auto/choco/info_pkg', ['POST'], _h_choco_37),
        ('/auto/cognee/recall', ['POST'], _h_cognee_38),
        ('/auto/copyq/clipboard', ['GET'], _h_copyq_39),
        ('/auto/copyq/clipboard', ['POST'], _h_copyq_40),
        ('/auto/copyq/history', ['GET'], _h_copyq_41),
        ('/auto/copyq/eval', ['POST'], _h_copyq_42),
        ('/auto/defrag/analyze', ['POST'], _h_defrag_43),
        ('/auto/defrag/optimize', ['POST'], _h_defrag_44),
        ('/auto/defrag/progress', ['POST'], _h_defrag_45),
        ('/auto/delta/format', ['POST'], _h_delta_46),
        ('/auto/delta/themes', ['GET'], _h_delta_47),
        ('/auto/delta/languages', ['GET'], _h_delta_48),
        ('/auto/detect_it_easy/detect', ['POST'], _h_detect_it_easy_49),
        ('/auto/devtoys/encode/base64', ['POST'], _h_devtoys_50),
        ('/auto/devtoys/decode/base64', ['POST'], _h_devtoys_51),
        ('/auto/devtoys/hash', ['POST'], _h_devtoys_52),
        ('/auto/devtoys/json/format', ['POST'], _h_devtoys_53),
        ('/auto/devtoys/uuid', ['GET'], _h_devtoys_54),
        ('/auto/diskpart/list-disks', ['GET'], _h_diskpart_55),
        ('/auto/diskpart/list-volumes', ['GET'], _h_diskpart_56),
        ('/auto/diskpart/list-partitions', ['POST'], _h_diskpart_57),
        ('/auto/diskpart/disk-detail', ['POST'], _h_diskpart_58),
        ('/auto/diskpart/clean-disk', ['POST'], _h_diskpart_59),
        ('/auto/diskpart/convert-gpt', ['POST'], _h_diskpart_60),
        ('/auto/diskpart/create-partition', ['POST'], _h_diskpart_61),
        ('/auto/diskpart/format-volume', ['POST'], _h_diskpart_62),
        ('/auto/diskpart/assign-letter', ['POST'], _h_diskpart_63),
        ('/auto/diskpart/remove-letter', ['POST'], _h_diskpart_64),
        ('/auto/dism/health/scan', ['POST'], _h_dism_65),
        ('/auto/dism/health/check', ['POST'], _h_dism_66),
        ('/auto/dism/health/restore', ['POST'], _h_dism_67),
        ('/auto/dism/features', ['GET'], _h_dism_68),
        ('/auto/dism/feature/enable', ['POST'], _h_dism_69),
        ('/auto/dism/feature/disable', ['POST'], _h_dism_70),
        ('/auto/dism/feature/state', ['POST'], _h_dism_71),
        ('/auto/dism/packages', ['GET'], _h_dism_72),
        ('/auto/dism/info/online', ['GET'], _h_dism_73),
        ('/auto/driverquery/list', ['GET'], _h_driverquery_74),
        ('/auto/driverquery/raw', ['GET'], _h_driverquery_75),
        ('/auto/excel_mcp_server/execute', ['POST'], _h_excel_mcp_server_76),
        ('/auto/eza/list', ['GET', 'POST'], _h_eza_77),
        ('/auto/fd/search', ['GET', 'POST'], _h_fd_78),
        ('/auto/fsutil/fsinfo', ['POST'], _h_fsutil_79),
        ('/auto/fsutil/diskfree', ['GET'], _h_fsutil_80),
        ('/auto/fsutil/file', ['POST'], _h_fsutil_81),
        ('/auto/fsutil/volume', ['GET'], _h_fsutil_82),
        ('/auto/fsutil/hardlink', ['POST'], _h_fsutil_83),
        ('/auto/fsutil/quota', ['POST'], _h_fsutil_84),
        ('/auto/fzf/filter', ['POST'], _h_fzf_85),
        ('/auto/fzf/search', ['POST'], _h_fzf_86),
        ('/auto/gsudo/run', ['POST'], _h_gsudo_87),
        ('/auto/gsudo/status', ['GET'], _h_gsudo_88),
        ('/auto/icacls/display', ['GET'], _h_icacls_89),
        ('/auto/icacls/grant', ['POST'], _h_icacls_90),
        ('/auto/icacls/deny', ['POST'], _h_icacls_91),
        ('/auto/icacls/remove', ['POST'], _h_icacls_92),
        ('/auto/icacls/setowner', ['POST'], _h_icacls_93),
        ('/auto/icacls/inheritance', ['POST'], _h_icacls_94),
        ('/auto/icacls/save', ['POST'], _h_icacls_95),
        ('/auto/icacls/restore', ['POST'], _h_icacls_96),
        ('/auto/imagemagick/identify', ['POST'], _h_imagemagick_97),
        ('/auto/imagemagick/convert', ['POST'], _h_imagemagick_98),
        ('/auto/imagemagick/compare', ['POST'], _h_imagemagick_99),
        ('/auto/imagemagick/resize', ['POST'], _h_imagemagick_100),
        ('/auto/ipconfig/all', ['GET'], _h_ipconfig_101),
        ('/auto/ipconfig/renew', ['POST'], _h_ipconfig_102),
        ('/auto/ipconfig/release', ['POST'], _h_ipconfig_103),
        ('/auto/ipconfig/flushdns', ['POST'], _h_ipconfig_104),
        ('/auto/ipconfig/displaydns', ['GET'], _h_ipconfig_105),
        ('/auto/ipconfig/registerdns', ['POST'], _h_ipconfig_106),
        ('/auto/ipconfig/showclassid', ['GET'], _h_ipconfig_107),
        ('/auto/ipconfig/setclassid', ['POST'], _h_ipconfig_108),
        ('/auto/just/list', ['GET'], _h_just_109),
        ('/auto/just/run', ['POST'], _h_just_110),
        ('/auto/just/dump', ['GET'], _h_just_111),
        ('/auto/komorebi/state', ['GET'], _h_komorebi_112),
        ('/auto/komorebi/command', ['POST'], _h_komorebi_113),
        ('/auto/komorebi/workspace', ['POST'], _h_komorebi_114),
        ('/auto/kopia/version', ['GET'], _h_kopia_115),
        ('/auto/kopia/status', ['GET'], _h_kopia_116),
        ('/auto/kopia/snapshots', ['GET'], _h_kopia_117),
        ('/auto/kopia/policy/list', ['GET'], _h_kopia_118),
        ('/auto/kopia/repository/connect', ['POST'], _h_kopia_119),
        ('/auto/kopia/repository/create', ['POST'], _h_kopia_120),
        ('/auto/kopia/maintenance/run', ['POST'], _h_kopia_121),
        ('/auto/kopia/repository/disconnect', ['POST'], _h_kopia_122),
        ('/auto/llama_cpp/health', ['GET'], _h_llama_cpp_123),
        ('/auto/llama_cpp/models', ['GET'], _h_llama_cpp_124),
        ('/auto/llama_cpp/generate', ['POST'], _h_llama_cpp_125),
        ('/auto/llama_cpp/chat', ['POST'], _h_llama_cpp_126),
        ('/auto/llama_cpp/embeddings', ['POST'], _h_llama_cpp_127),
        ('/auto/mkcert/version', ['GET'], _h_mkcert_128),
        ('/auto/mkcert/install-ca', ['POST'], _h_mkcert_129),
        ('/auto/mkcert/generate', ['POST'], _h_mkcert_130),
        ('/auto/mkcert/caroot', ['GET'], _h_mkcert_131),
        ('/auto/mkcert/uninstall-ca', ['POST'], _h_mkcert_132),
        ('/auto/netsh/interface/show', ['GET'], _h_netsh_133),
        ('/auto/netsh/wifi', ['GET'], _h_netsh_134),
        ('/auto/netsh/wifi/profile', ['GET'], _h_netsh_135),
        ('/auto/netsh/firewall', ['GET'], _h_netsh_136),
        ('/auto/netsh/dns', ['GET'], _h_netsh_137),
        ('/auto/netsh/proxy', ['GET'], _h_netsh_138),
        ('/auto/netsh/command', ['POST'], _h_netsh_139),
        ('/auto/nmap/scan', ['POST'], _h_nmap_140),
        ('/auto/nmap/quick-scan', ['POST'], _h_nmap_141),
        ('/auto/nmap/version-scan', ['POST'], _h_nmap_142),
        ('/auto/ollama/list', ['GET'], _h_ollama_143),
        ('/auto/ollama/ps', ['GET'], _h_ollama_144),
        ('/auto/ollama/show', ['GET'], _h_ollama_145),
        ('/auto/ollama/pull', ['POST'], _h_ollama_146),
        ('/auto/ollama/generate', ['POST'], _h_ollama_147),
        ('/auto/ollama/chat', ['POST'], _h_ollama_148),
        ('/auto/ollama/embeddings', ['POST'], _h_ollama_149),
        ('/auto/pe_sieve/scan', ['POST'], _h_pe_sieve_150),
        ('/auto/photoshop_mcp/execute', ['POST'], _h_photoshop_mcp_151),
        ('/auto/photoshop_mcp/run_script', ['POST'], _h_photoshop_mcp_152),
        ('/auto/powercfg/list', ['GET'], _h_powercfg_153),
        ('/auto/powercfg/query', ['GET'], _h_powercfg_154),
        ('/auto/powercfg/set_active', ['POST'], _h_powercfg_155),
        ('/auto/powercfg/energy', ['GET'], _h_powercfg_156),
        ('/auto/powercfg/battery_report', ['GET'], _h_powercfg_157),
        ('/auto/powercfg/hibernate', ['POST'], _h_powercfg_158),
        ('/auto/procs/list', ['GET'], _h_procs_159),
        ('/auto/procs/tree', ['GET'], _h_procs_160),
        ('/auto/procs/find', ['GET'], _h_procs_161),
        ('/auto/procs/kill', ['POST'], _h_procs_162),
        ('/auto/rapidocr/ocr', ['POST'], _h_rapidocr_163),
        ('/auto/reg/query', ['POST'], _h_reg_164),
        ('/auto/reg/add', ['POST'], _h_reg_165),
        ('/auto/reg/delete', ['POST'], _h_reg_166),
        ('/auto/reg/export', ['POST'], _h_reg_167),
        ('/auto/reg/compare', ['POST'], _h_reg_168),
        ('/auto/ripgrep/search', ['POST'], _h_ripgrep_169),
        ('/auto/ripgrep/count', ['POST'], _h_ripgrep_170),
        ('/auto/ripgrep/files', ['POST'], _h_ripgrep_171),
        ('/auto/rufus/drives', ['GET'], _h_rufus_172),
        ('/auto/rufus/isos', ['GET'], _h_rufus_173),
        ('/auto/rufus/create', ['POST'], _h_rufus_174),
        ('/auto/sc/query', ['GET'], _h_sc_175),
        ('/auto/sc/query_service', ['GET'], _h_sc_176),
        ('/auto/sc/control', ['POST'], _h_sc_177),
        ('/auto/sc/config', ['POST'], _h_sc_178),
        ('/auto/sc/dependencies', ['GET'], _h_sc_179),
        ('/auto/schtasks/query', ['GET'], _h_schtasks_180),
        ('/auto/schtasks/query/detail', ['GET'], _h_schtasks_181),
        ('/auto/schtasks/folders', ['GET'], _h_schtasks_182),
        ('/auto/schtasks/run', ['POST'], _h_schtasks_183),
        ('/auto/schtasks/end', ['POST'], _h_schtasks_184),
        ('/auto/schtasks/delete', ['POST'], _h_schtasks_185),
        ('/auto/schtasks/create/hourly', ['POST'], _h_schtasks_186),
        ('/auto/schtasks/create/daily', ['POST'], _h_schtasks_187),
        ('/auto/schtasks/create/onstart', ['POST'], _h_schtasks_188),
        ('/auto/scrcpy/devices', ['GET'], _h_scrcpy_189),
        ('/auto/scrcpy/displays', ['GET'], _h_scrcpy_190),
        ('/auto/scrcpy/record', ['POST'], _h_scrcpy_191),
        ('/auto/sd/replace', ['POST'], _h_sd_192),
        ('/auto/sfc/scannow', ['POST'], _h_sfc_193),
        ('/auto/sfc/verify', ['GET'], _h_sfc_194),
        ('/auto/sfc/verifyfile', ['POST'], _h_sfc_195),
        ('/auto/sfc/status', ['GET'], _h_sfc_196),
        ('/auto/sharex/capture/screen', ['POST'], _h_sharex_197),
        ('/auto/sharex/capture/upload', ['POST'], _h_sharex_198),
        ('/auto/sharex/tools/hash', ['POST'], _h_sharex_199),
        ('/auto/sharex/tools/colorpicker', ['GET'], _h_sharex_200),
        ('/auto/sharex/tools/image-editor', ['POST'], _h_sharex_201),
        ('/auto/sharex/tools/ocr', ['POST'], _h_sharex_202),
        ('/auto/sharex/tools/metadata', ['POST'], _h_sharex_203),
        ('/auto/sharpdxscreencapture/capture', ['POST'], _h_sharpdxscreencapture_204),
        ('/auto/shutdown/shutdown', ['POST'], _h_shutdown_205),
        ('/auto/shutdown/restart', ['POST'], _h_shutdown_206),
        ('/auto/shutdown/logoff', ['POST'], _h_shutdown_207),
        ('/auto/shutdown/hibernate', ['POST'], _h_shutdown_208),
        ('/auto/shutdown/abort', ['POST'], _h_shutdown_209),
        ('/auto/shutdown/poweroff', ['POST'], _h_shutdown_210),
        ('/auto/shutdown/hybrid_shutdown', ['POST'], _h_shutdown_211),
        ('/auto/shutdown/status', ['GET'], _h_shutdown_212),
        ('/auto/systeminfo/report', ['GET'], _h_systeminfo_213),
        ('/auto/systeminfo/os', ['GET'], _h_systeminfo_214),
        ('/auto/systeminfo/hardware', ['GET'], _h_systeminfo_215),
        ('/auto/systeminfo/hotfixes', ['GET'], _h_systeminfo_216),
        ('/auto/takeown/status', ['GET'], _h_takeown_217),
        ('/auto/takeown/take', ['POST'], _h_takeown_218),
        ('/auto/taskkill/pid', ['POST'], _h_taskkill_219),
        ('/auto/taskkill/name', ['POST'], _h_taskkill_220),
        ('/auto/taskkill/filter', ['POST'], _h_taskkill_221),
        ('/auto/taskkill/all', ['DELETE'], _h_taskkill_222),
        ('/auto/tasklist/list', ['GET'], _h_tasklist_223),
        ('/auto/tasklist/filter', ['POST'], _h_tasklist_224),
        ('/auto/tasklist/kill', ['POST'], _h_tasklist_225),
        ('/auto/tasklist/kill_by_name', ['POST'], _h_tasklist_226),
        ('/auto/topgrade/dry-run', ['GET'], _h_topgrade_227),
        ('/auto/topgrade/run', ['POST'], _h_topgrade_228),
        ('/auto/topgrade/config', ['GET'], _h_topgrade_229),
        ('/auto/trippy/trace', ['POST'], _h_trippy_230),
        ('/auto/trippy/targets', ['GET'], _h_trippy_231),
        ('/auto/ventoy/volumes', ['GET'], _h_ventoy_232),
        ('/auto/ventoy/status', ['GET'], _h_ventoy_233),
        ('/auto/ventoy/install', ['POST'], _h_ventoy_234),
        ('/auto/vssadmin/shadows', ['GET'], _h_vssadmin_235),
        ('/auto/vssadmin/delete_shadows', ['POST'], _h_vssadmin_236),
        ('/auto/vssadmin/providers', ['GET'], _h_vssadmin_237),
        ('/auto/vssadmin/storage', ['GET'], _h_vssadmin_238),
        ('/auto/vssadmin/volumes', ['GET'], _h_vssadmin_239),
        ('/auto/vssadmin/writers', ['GET'], _h_vssadmin_240),
        ('/auto/vssadmin/resize_storage', ['POST'], _h_vssadmin_241),
        ('/auto/wevtutil/logs', ['GET'], _h_wevtutil_242),
        ('/auto/wevtutil/log/info', ['POST'], _h_wevtutil_243),
        ('/auto/wevtutil/query', ['POST'], _h_wevtutil_244),
        ('/auto/wevtutil/export', ['POST'], _h_wevtutil_245),
        ('/auto/wevtutil/clear', ['POST'], _h_wevtutil_246),
        ('/auto/wevtutil/publishers', ['GET'], _h_wevtutil_247),
        ('/auto/wevtutil/subscriptions', ['GET'], _h_wevtutil_248),
        ('/auto/wevtutil/archive', ['POST'], _h_wevtutil_249),
        ('/auto/win11debloat/run-defaults', ['POST'], _h_win11debloat_250),
        ('/auto/win11debloat/custom', ['POST'], _h_win11debloat_251),
        ('/auto/win11debloat/check', ['GET'], _h_win11debloat_252),
        ('/auto/windows_mcp/server/start', ['POST'], _h_windows_mcp_253),
        ('/auto/windows_mcp/server/stop', ['POST'], _h_windows_mcp_254),
        ('/auto/windows_mcp/tool', ['POST'], _h_windows_mcp_255),
        ('/auto/windows_mcp/tools', ['GET'], _h_windows_mcp_256),
        ('/auto/windows_mcp/screenshot', ['GET'], _h_windows_mcp_257),
        ('/auto/winget_cli/search', ['POST'], _h_winget_cli_258),
        ('/auto/winget_cli/list', ['GET'], _h_winget_cli_259),
        ('/auto/winget_cli/install', ['POST'], _h_winget_cli_260),
        ('/auto/winget_cli/upgrade', ['POST'], _h_winget_cli_261),
        ('/auto/winget_cli/show', ['POST'], _h_winget_cli_262),
        ('/auto/winget_cli/uninstall', ['POST'], _h_winget_cli_263),
        ('/auto/xh/request', ['POST'], _h_xh_264),
        ('/auto/xh/headers', ['GET'], _h_xh_265),
        ('/auto/yq/query', ['POST'], _h_yq_266),
        ('/auto/yq/convert', ['POST'], _h_yq_267),
        ('/auto/yt_dlp/info_video', ['POST'], _h_yt_dlp_268),
        ('/auto/yt_dlp/list_formats', ['POST'], _h_yt_dlp_269),
        ('/auto/yt_dlp/download', ['POST'], _h_yt_dlp_270),
        ('/auto/yt_dlp/update', ['POST'], _h_yt_dlp_271),
        ('/auto/zoxide/query', ['POST'], _h_zoxide_272),
        ('/auto/zoxide/list', ['GET'], _h_zoxide_273),
        ('/auto/zoxide/add', ['POST'], _h_zoxide_274),
        ('/auto/ffmpeg/probe', ['POST'], _h_ffmpeg_275),
        ('/auto/ffmpeg/transcode', ['POST'], _h_ffmpeg_276),
        ('/auto/ffmpeg/extract_audio', ['POST'], _h_ffmpeg_277),
        ('/auto/ffmpeg/frames', ['POST'], _h_ffmpeg_278),
        ('/auto/ffmpeg/gif', ['POST'], _h_ffmpeg_279),
        ('/auto/hexyl/view', ['POST'], _h_hexyl_280),
        ('/auto/hexyl/decode', ['POST'], _h_hexyl_281),
        ('/auto/doggo/query', ['POST'], _h_doggo_282),
        ('/auto/volatility3/plugins', ['GET'], _h_volatility3_283),
        ('/auto/volatility3/analyze', ['POST'], _h_volatility3_284),
        ('/auto/hyperfine/bench', ['POST'], _h_hyperfine_285),
        ('/auto/duf/usage', ['GET', 'POST'], _h_duf_286),
        ('/auto/jq/query', ['POST'], _h_jq_287),
        ('/auto/jq/validate', ['POST'], _h_jq_288),
        ('/auto/difftastic/diff', ['POST'], _h_difftastic_289),
        ('/auto/difftastic/languages', ['GET'], _h_difftastic_290),
        ('/auto/uv/pip_install', ['POST'], _h_uv_291),
        ('/auto/uv/run', ['POST'], _h_uv_292),
        ('/auto/pandoc/convert', ['POST'], _h_pandoc_293),
        ('/auto/pandoc/formats', ['GET'], _h_pandoc_294),
        ('/auto/rclone/remotes', ['GET'], _h_rclone_295),
        ('/auto/rclone/list', ['POST'], _h_rclone_296),
        ('/auto/rclone/size', ['POST'], _h_rclone_297),
        ('/auto/rclone/about', ['POST'], _h_rclone_298),
        ('/auto/rclone/sync', ['POST'], _h_rclone_299),
        ('/auto/rclone/copy', ['POST'], _h_rclone_300),
        ('/auto/rclone/check', ['POST'], _h_rclone_301),
        ('/auto/restic/snapshots', ['GET'], _h_restic_302),
        ('/auto/restic/backup', ['POST'], _h_restic_303),
        ('/auto/restic/restore', ['POST'], _h_restic_304),
        ('/auto/restic/stats', ['GET'], _h_restic_305),
        ('/auto/restic/init', ['POST'], _h_restic_306),
        ('/auto/miller/convert', ['POST'], _h_miller_307),
        ('/auto/miller/stats', ['POST'], _h_miller_308),
        ('/auto/miller/process', ['POST'], _h_miller_309),
        ('/auto/tokei/count', ['POST'], _h_tokei_310),
        ('/auto/tokei/languages', ['GET'], _h_tokei_311),
        ('/auto/tokei/files', ['POST'], _h_tokei_312),
        ('/auto/jc/parse', ['POST'], _h_jc_313),
        ('/auto/jc/parsers', ['GET'], _h_jc_314),
        ('/auto/ruff/check', ['POST'], _h_ruff_315),
        ('/auto/ruff/format', ['POST'], _h_ruff_316),
        ('/auto/ruff/rule', ['GET'], _h_ruff_317),
        ('/auto/mise/list', ['GET'], _h_mise_318),
        ('/auto/mise/current', ['GET'], _h_mise_319),
        ('/auto/mise/tasks', ['GET'], _h_mise_320),
        ('/auto/mise/exec', ['POST'], _h_mise_321),
        ('/auto/mise/run', ['POST'], _h_mise_322),
        ('/auto/shellcheck/check', ['POST'], _h_shellcheck_323),
        ('/auto/shellcheck/file', ['POST'], _h_shellcheck_324),
        ('/auto/dust/usage', ['POST'], _h_dust_325),
        ('/auto/dust/largest', ['POST'], _h_dust_326),
        ('/auto/onefetch/repo', ['POST'], _h_onefetch_327),
        ('/auto/onefetch/languages', ['POST'], _h_onefetch_328),
        ('/auto/nushell/eval', ['POST'], _h_nushell_329),
        ('/auto/nushell/script', ['POST'], _h_nushell_330),
        ('/auto/nushell/query', ['POST'], _h_nushell_331),
        ('/auto/glow/render', ['POST'], _h_glow_332),
        ('/auto/glow/render_file', ['POST'], _h_glow_333),
    ]
    for _path, _methods, _fn in _ACTIONS:
        app.add_url_rule(_path, endpoint=_fn.__name__, view_func=require_auth(_fn), methods=_methods)
