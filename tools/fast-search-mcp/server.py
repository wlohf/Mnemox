#!/usr/bin/env python3
"""Fast Search MCP: local, read-only, path-restricted search tools for coding agents."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "fast-search"
SERVER_VERSION = "0.1.0"
DEFAULT_ROOTS = ["/home/cloudcli/projects", "/home/cloudcli"]
ALLOWED_ROOTS = [Path(p).resolve() for p in os.environ.get("FAST_SEARCH_ROOTS", ":".join(DEFAULT_ROOTS)).split(":") if p]
MAX_RESULTS = int(os.environ.get("FAST_SEARCH_MAX_RESULTS", "200"))
MAX_OUTPUT_BYTES = int(os.environ.get("FAST_SEARCH_MAX_OUTPUT_BYTES", "262144"))
TIMEOUT = float(os.environ.get("FAST_SEARCH_TIMEOUT", "8"))

def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}

def _err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

def _text(data: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}]}

def _resolve(path: str | None, default: str = "/home/cloudcli/projects") -> Path:
    p = Path(path or default).expanduser().resolve()
    if not any(p == root or root in p.parents for root in ALLOWED_ROOTS):
        raise ValueError(f"path is outside allowed roots: {p}")
    if not p.exists():
        raise ValueError(f"path does not exist: {p}")
    return p

def _limit(n: Any) -> int:
    try:
        return max(1, min(int(n or 50), MAX_RESULTS))
    except Exception:
        return 50

def _run(argv: list[str], cwd: Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout or TIMEOUT,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )

def _clip(text: str) -> str:
    raw = text.encode("utf-8", "replace")
    if len(raw) <= MAX_OUTPUT_BYTES:
        return text
    return raw[:MAX_OUTPUT_BYTES].decode("utf-8", "replace") + "\n...[truncated]"

def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    extra = ["/root/.pi/agent/bin/fd"]
    for p in extra:
        if Path(p).is_file() and os.access(p, os.X_OK):
            return p
    return None

def find_file(args: dict[str, Any]) -> Any:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    root = _resolve(args.get("root"))
    limit = _limit(args.get("limit"))
    mode = str(args.get("mode", "contains"))

    locate = _which("plocate", "locate")
    if locate:
        cp = _run([locate, "--", query])
        items = []
        for line in cp.stdout.splitlines():
            try:
                p = Path(line).resolve()
            except Exception:
                continue
            if any(p == r or r in p.parents for r in ALLOWED_ROOTS) and (p == root or root in p.parents):
                items.append(str(p))
                if len(items) >= limit:
                    break
        if items:
            return {"engine": Path(locate).name, "results": items, "count": len(items)}

    fd = _which("fd", "fdfind")
    if fd:
        pattern = query if mode == "regex" else re.escape(query)
        cp = _run([fd, "--hidden", "--follow", "--exclude", ".git", "--max-results", str(limit), pattern, str(root)])
        items = cp.stdout.splitlines()[:limit]
        return {"engine": Path(fd).name, "results": items, "count": len(items)}

    cp = _run(["find", str(root), "-path", "*/.git", "-prune", "-o", "-iname", f"*{query}*", "-print"])
    items = cp.stdout.splitlines()[:limit]
    return {"engine": "find", "results": items, "count": len(items)}

def list_files(args: dict[str, Any]) -> Any:
    root = _resolve(args.get("root"))
    limit = _limit(args.get("limit"))
    git = _which("git")
    if git and (root / ".git").exists():
        cp = _run([git, "ls-files", "-co", "--exclude-standard"], cwd=root)
        items = cp.stdout.splitlines()[:limit]
        return {"engine": "git ls-files", "root": str(root), "results": items, "count": len(items)}
    fd = _which("fd", "fdfind")
    if fd:
        cp = _run([fd, "--type", "f", "--hidden", "--exclude", ".git", ".", str(root)])
        items = cp.stdout.splitlines()[:limit]
        return {"engine": Path(fd).name, "root": str(root), "results": items, "count": len(items)}
    cp = _run(["find", str(root), "-type", "f", "-not", "-path", "*/.git/*"])
    items = cp.stdout.splitlines()[:limit]
    return {"engine": "find", "root": str(root), "results": items, "count": len(items)}

def search_code(args: dict[str, Any]) -> Any:
    query = str(args.get("query", ""))
    if not query:
        raise ValueError("query is required")
    root = _resolve(args.get("root"))
    limit = _limit(args.get("limit"))
    regex = bool(args.get("regex", False))
    glob = args.get("glob")

    rg = _which("rg")
    if rg:
        argv = [rg, "--line-number", "--column", "--no-heading", "--color", "never", "--hidden", "--glob", "!.git/*", "--max-count", str(limit)]
        if not regex:
            argv.append("--fixed-strings")
        if glob:
            argv += ["--glob", str(glob)]
        argv += ["--", query, str(root)]
        cp = _run(argv)
        lines = cp.stdout.splitlines()[:limit]
        return {"engine": "rg", "results": lines, "count": len(lines)}

    git = _which("git")
    if git and (root / ".git").exists():
        argv = [git, "grep", "-n", "-I"]
        if not regex:
            argv.append("-F")
        argv += ["--", query]
        cp = _run(argv, cwd=root)
        lines = cp.stdout.splitlines()[:limit]
        return {"engine": "git grep", "results": lines, "count": len(lines)}

    grep = _which("grep")
    argv = [grep or "grep", "-R", "-n", "-I", "--exclude-dir=.git"]
    if not regex:
        argv.append("-F")
    argv += ["--", query, str(root)]
    cp = _run(argv)
    lines = cp.stdout.splitlines()[:limit]
    return {"engine": "grep", "results": lines, "count": len(lines)}

def search_structure(args: dict[str, Any]) -> Any:
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern is required")
    root = _resolve(args.get("root"))
    limit = _limit(args.get("limit"))
    language = args.get("language")
    sg = _which("ast-grep", "sg")
    if not sg:
        return {"available": False, "message": "ast-grep is not installed; install @ast-grep/cli or distro package."}
    argv = [sg, "run", "--pattern", pattern, "--json=stream"]
    if language:
        argv += ["--lang", str(language)]
    argv += [str(root)]
    cp = _run(argv, timeout=max(TIMEOUT, 15))
    lines = cp.stdout.splitlines()[:limit]
    return {"available": True, "engine": Path(sg).name, "results": [json.loads(x) if x.startswith("{") else x for x in lines], "count": len(lines), "stderr": _clip(cp.stderr)}

def find_definition(args: dict[str, Any]) -> Any:
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        raise ValueError("symbol is required")
    root = _resolve(args.get("root"))
    lang = str(args.get("language", "auto")).lower()
    escaped = re.escape(symbol)
    patterns = []
    if lang in ("auto", "python", "py"):
        patterns += [rf"^(class|def|async\s+def)\s+{escaped}\b"]
    if lang in ("auto", "typescript", "javascript", "ts", "js"):
        patterns += [rf"^(export\s+)?(default\s+)?(class|function|const|let|var|interface|type|enum)\s+{escaped}\b"]
    if lang in ("auto", "go"):
        patterns += [rf"^(type|func)\s+(\([^)]*\)\s+)?{escaped}\b"]
    query = "|".join(f"(?:{p})" for p in patterns) or escaped
    result = search_code({"query": query, "root": str(root), "regex": True, "limit": args.get("limit", 50)})
    result["semantic"] = False
    result["note"] = "Fast textual definition heuristic. Use a language LSP for fully semantic resolution."
    return result

def find_references(args: dict[str, Any]) -> Any:
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        raise ValueError("symbol is required")
    root = _resolve(args.get("root"))
    result = search_code({"query": symbol, "root": str(root), "regex": False, "limit": args.get("limit", 100)})
    result["semantic"] = False
    result["note"] = "Fast textual references. A future LSP adapter can provide semantic references."
    return result

def read_range(args: dict[str, Any]) -> Any:
    p = _resolve(args.get("path"), default="/home/cloudcli/projects")
    if not p.is_file():
        raise ValueError("path must be a file")
    start = max(1, int(args.get("start_line", 1)))
    end = max(start, int(args.get("end_line", start + 199)))
    end = min(end, start + 999)
    out = []
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if i < start:
                continue
            if i > end:
                break
            out.append(f"{i}: {line.rstrip()}")
    return {"path": str(p), "start_line": start, "end_line": end, "text": _clip("\n".join(out))}

TOOLS = [
    {"name": "find_file", "description": "Find a file or directory by name/path very quickly inside approved local roots. Uses plocate/locate, then fd, then find.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "root": {"type": "string"}, "limit": {"type": "integer", "default": 50}, "mode": {"type": "string", "enum": ["contains", "regex"], "default": "contains"}}, "required": ["query"]}},
    {"name": "list_files", "description": "List project files while respecting gitignore when possible.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "limit": {"type": "integer", "default": 100}}}},
    {"name": "search_code", "description": "Fast text/code search within a project. Prefers ripgrep and respects .gitignore; falls back to git grep/grep.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "root": {"type": "string"}, "regex": {"type": "boolean", "default": False}, "glob": {"type": "string"}, "limit": {"type": "integer", "default": 50}}, "required": ["query"]}},
    {"name": "search_structure", "description": "AST-aware structural code search using ast-grep when installed.", "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string"}, "root": {"type": "string"}, "language": {"type": "string"}, "limit": {"type": "integer", "default": 50}}, "required": ["pattern"]}},
    {"name": "find_definition", "description": "Locate likely code definitions for a symbol with fast language-aware textual heuristics.", "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}, "root": {"type": "string"}, "language": {"type": "string", "default": "auto"}, "limit": {"type": "integer", "default": 50}}, "required": ["symbol"]}},
    {"name": "find_references", "description": "Locate references/usages of a symbol quickly across a project.", "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}, "root": {"type": "string"}, "limit": {"type": "integer", "default": 100}}, "required": ["symbol"]}},
    {"name": "read_range", "description": "Read only a requested line range from an approved local file to reduce context/token use.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer", "default": 1}, "end_line": {"type": "integer", "default": 200}}, "required": ["path"]}},
]
HANDLERS = {
    "find_file": find_file,
    "list_files": list_files,
    "search_code": search_code,
    "search_text": search_code,
    "search_structure": search_structure,
    "find_definition": find_definition,
    "find_references": find_references,
    "read_range": read_range,
}

def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    req_id = msg.get("id")
    if method == "initialize":
        return _ok(req_id, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if not fn:
            return _ok(req_id, {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True})
        try:
            return _ok(req_id, _text(fn(args)))
        except subprocess.TimeoutExpired:
            return _ok(req_id, {"content": [{"type": "text", "text": f"search timed out after {TIMEOUT}s"}], "isError": True})
        except Exception as e:
            return _ok(req_id, {"content": [{"type": "text", "text": str(e)}], "isError": True})
    if req_id is not None:
        return _err(req_id, -32601, f"method not found: {method}")
    return None

def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            resp = handle(msg)
        except Exception as e:
            resp = _err(None, -32700, f"parse error: {e}")
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
