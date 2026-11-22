#!/usr/bin/env python3
"""
tools/context7_docs.py
Context7 documentation & snippet lookup tool.

Allows automated querying of framework/library documentation (aiogram, aiohttp, etc.)
from workspace scripts, bot services, or directly via CLI.

Usage (CLI):
    python tools/context7_docs.py <library> <query>
    python tools/context7_docs.py aiogram "TelegramConflictError"
    python tools/context7_docs.py aiohttp "ClientSession timeout" --language Python
    python tools/context7_docs.py aiogram --resolve-only

Usage (Python module):
    from tools.context7_docs import query_library_docs, resolve_library_id

    # Sync
    docs = query_library_docs("aiogram", "TelegramConflictError")

    # Async
    from tools.context7_docs import async_query_library_docs
    docs = await async_query_library_docs("aiogram", "TelegramConflictError")
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Context7 Configuration
DEFAULT_SERVER_URL = "https://mcp.context7.com/mcp"
CONTEXT7_SERVER_URL = os.getenv("CONTEXT7_SERVER_URL", DEFAULT_SERVER_URL)
CONTEXT7_API_KEY = os.getenv("CONTEXT7_API_KEY", "")


# -----------------------------------------------------------------------------
# Custom Exceptions
# -----------------------------------------------------------------------------

class Context7Error(Exception):
    """Base exception for Context7 documentation lookup errors."""
    pass


class Context7ConnectionError(Context7Error):
    """Raised when communication with the Context7 endpoint fails."""
    pass


class Context7APIError(Context7Error):
    """Raised when Context7 returns an API error or invalid response."""
    pass


class Context7NotFoundError(Context7Error):
    """Raised when no matching library or documentation snippet is found."""
    pass


# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------

@dataclass
class LibraryCandidate:
    """Represents a candidate library resolved by Context7."""
    id: str
    title: str = ""
    description: str = ""
    snippets: int = 0
    reputation: str = ""
    benchmark_score: float = 0.0
    versions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -----------------------------------------------------------------------------
# Parsing Helpers
# -----------------------------------------------------------------------------

def _build_headers() -> dict[str, str]:
    """Construct standard HTTP headers for Context7 JSON-RPC over HTTP/SSE."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "CryptoRadarPro-Context7Docs/1.0",
    }
    if CONTEXT7_API_KEY:
        headers["X-Context7-API-Key"] = CONTEXT7_API_KEY
    return headers


def _parse_sse_response(raw_text: str) -> dict[str, Any]:
    """
    Parse JSON-RPC response from text/event-stream or standard JSON.
    Context7 sends 'event: message\ndata: { ... }'.
    """
    for line in raw_text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("data:"):
            payload = trimmed[5:].strip()
            if payload:
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as err:
        raise Context7APIError(f"Failed to parse Context7 response: {raw_text[:300]}") from err


def _extract_text_content(response_dict: dict[str, Any]) -> str:
    """Extract combined text content from a JSON-RPC tool result."""
    if "error" in response_dict and response_dict["error"]:
        err = response_dict["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise Context7APIError(f"Context7 tool error: {msg}")

    result = response_dict.get("result", {})
    if not isinstance(result, dict):
        return str(result)

    content_list = result.get("content", [])
    texts: list[str] = []
    for item in content_list:
        if isinstance(item, dict) and item.get("type") == "text":
            texts.append(item.get("text", ""))
        elif isinstance(item, str):
            texts.append(item)

    if not texts and "text" in result:
        texts.append(str(result["text"]))

    return "\n".join(texts)


def _parse_libraries_output(raw_text: str) -> list[LibraryCandidate]:
    """Parse output of resolve-library-id into structured LibraryCandidate objects."""
    candidates: list[LibraryCandidate] = []
    # Results are usually separated by dashed lines (e.g. ----------)
    sections = re.split(r"\n-{3,}\n", raw_text)

    for sec in sections:
        sec_clean = sec.strip()
        if not sec_clean:
            continue

        lib_id_match = re.search(r"Context7-compatible library ID:\s*(\S+)", sec_clean)
        if not lib_id_match:
            continue

        candidate_id = lib_id_match.group(1).strip()
        title_match = re.search(r"Title:\s*(.+)", sec_clean)
        desc_match = re.search(r"Description:\s*(.+)", sec_clean)
        snippets_match = re.search(r"Code Snippets:\s*(\d+)", sec_clean)
        rep_match = re.search(r"Source Reputation:\s*(\w+)", sec_clean)
        score_match = re.search(r"Benchmark Score:\s*([\d\.]+)", sec_clean)
        versions_match = re.search(r"Versions:\s*(.+)", sec_clean)

        versions: list[str] = []
        if versions_match:
            versions = [v.strip() for v in versions_match.group(1).split(",") if v.strip()]

        candidates.append(
            LibraryCandidate(
                id=candidate_id,
                title=title_match.group(1).strip() if title_match else "",
                description=desc_match.group(1).strip() if desc_match else "",
                snippets=int(snippets_match.group(1)) if snippets_match else 0,
                reputation=rep_match.group(1).strip() if rep_match else "",
                benchmark_score=float(score_match.group(1)) if score_match else 0.0,
                versions=versions,
            )
        )

    return candidates


def _pick_best_candidate(candidates: list[LibraryCandidate], library_name: str) -> LibraryCandidate | None:
    """
    Select the most suitable library candidate from resolution results.
    Prioritizes:
      1. Exact or canonical name matches in ID or Title
      2. Highest benchmark score & snippet coverage
    """
    if not candidates:
        return None

    clean_name = library_name.strip().lower().replace("-", "").replace("_", "")

    # Look for matching candidates
    matching: list[LibraryCandidate] = []
    for cand in candidates:
        cand_id_clean = cand.id.lower().replace("-", "").replace("_", "")
        cand_title_clean = cand.title.lower().replace("-", "").replace("_", "")
        if clean_name in cand_id_clean or clean_name in cand_title_clean:
            matching.append(cand)

    pool = matching if matching else candidates

    # Rank by benchmark score descending, then code snippets descending
    sorted_candidates = sorted(
        pool,
        key=lambda c: (c.benchmark_score, c.snippets),
        reverse=True,
    )
    return sorted_candidates[0]


# -----------------------------------------------------------------------------
# Synchronous Core Functions
# -----------------------------------------------------------------------------

def call_context7_tool(
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float = 15.0,
    server_url: str = CONTEXT7_SERVER_URL,
) -> str:
    """
    Synchronously call a Context7 tool via HTTP JSON-RPC endpoint.

    Args:
        tool_name: Name of Context7 tool (e.g. 'resolve-library-id' or 'query-docs')
        arguments: Parameters payload matching tool schema
        timeout: Request timeout in seconds
        server_url: Target Context7 MCP endpoint

    Returns:
        Raw text extracted from tool execution response.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    data_bytes = json.dumps(payload).encode("utf-8")
    headers = _build_headers()
    req = urllib.request.Request(server_url, data=data_bytes, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as http_err:
        err_body = http_err.read().decode("utf-8", errors="replace")
        raise Context7APIError(
            f"HTTP {http_err.code} from Context7 server: {err_body[:300]}"
        ) from http_err
    except (urllib.error.URLError, TimeoutError, OSError) as conn_err:
        raise Context7ConnectionError(
            f"Failed to connect to Context7 at {server_url}: {conn_err}"
        ) from conn_err

    resp_json = _parse_sse_response(raw_text)
    return _extract_text_content(resp_json)


def resolve_library_id(
    library_name: str,
    query: str = "",
    timeout: float = 15.0,
) -> list[LibraryCandidate]:
    """
    Resolve a library/package name to Context7-compatible candidates.

    Args:
        library_name: Name of library (e.g. 'aiogram', 'aiohttp', 'fastapi')
        query: Concept/query to improve relevance ranking
        timeout: Request timeout in seconds

    Returns:
        List of LibraryCandidate objects.
    """
    if not library_name or not library_name.strip():
        raise ValueError("library_name cannot be empty")

    # If library is already formatted as Context7 ID (/org/repo), return it directly
    if library_name.strip().startswith("/"):
        return [LibraryCandidate(id=library_name.strip(), title=library_name.strip())]

    raw_text = call_context7_tool(
        tool_name="resolve-library-id",
        arguments={
            "libraryName": library_name.strip(),
            "query": query.strip() or f"Overview and API documentation for {library_name}",
        },
        timeout=timeout,
    )

    candidates = _parse_libraries_output(raw_text)
    if not candidates:
        # Fallback to direct heuristic ID if resolution returned no candidates
        heuristic_id = f"/{library_name.strip()}/{library_name.strip()}"
        return [LibraryCandidate(id=heuristic_id, title=library_name.strip())]

    return candidates


def query_docs(
    library_id: str,
    query: str,
    language: str = "Python",
    timeout: float = 15.0,
) -> str:
    """
    Retrieve documentation and code snippets for a specific Context7 library ID.

    Args:
        library_id: Context7 library ID (format: /org/repo)
        query: Concept or symbol to query
        language: Programming language for snippets (default: 'Python')
        timeout: Request timeout in seconds

    Returns:
        Markdown string containing documentation and code snippets.
    """
    if not library_id or not library_id.strip():
        raise ValueError("library_id cannot be empty")
    if not query or not query.strip():
        raise ValueError("query cannot be empty")

    clean_id = library_id.strip()
    if not clean_id.startswith("/"):
        clean_id = f"/{clean_id}"

    args: dict[str, Any] = {
        "libraryId": clean_id,
        "query": query.strip(),
    }
    if language:
        args["language"] = language.strip()

    return call_context7_tool(
        tool_name="query-docs",
        arguments=args,
        timeout=timeout,
    )


def query_library_docs(
    library: str,
    query: str,
    language: str = "Python",
    library_id: str | None = None,
    timeout: float = 15.0,
) -> str:
    """
    High-level entry point to search and fetch documentation snippets in one call.

    Resolves the library ID if not explicitly provided, selects the best candidate,
    and returns up-to-date documentation and code examples.

    Args:
        library: Library name (e.g. 'aiogram') or direct ID ('/aiogram/aiogram')
        query: Concept or error to look up (e.g. 'TelegramConflictError')
        language: Programming language filter (default: 'Python')
        library_id: Optional explicit Context7 library ID override
        timeout: Request timeout in seconds

    Returns:
        Markdown documentation and code snippets.
    """
    target_id = library_id

    # If library is already an ID (starts with /), use it directly
    if not target_id and library.strip().startswith("/"):
        target_id = library.strip()

    # Otherwise resolve candidates
    if not target_id:
        candidates = resolve_library_id(library, query=query, timeout=timeout)
        best = _pick_best_candidate(candidates, library)
        if best:
            target_id = best.id
        else:
            target_id = f"/{library.strip()}/{library.strip()}"

    return query_docs(
        library_id=target_id,
        query=query,
        language=language,
        timeout=timeout,
    )


# -----------------------------------------------------------------------------
# Asynchronous Core Functions
# -----------------------------------------------------------------------------

async def async_call_context7_tool(
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float = 15.0,
    server_url: str = CONTEXT7_SERVER_URL,
) -> str:
    """
    Asynchronously call a Context7 tool using aiohttp if available,
    falling back to thread executor if aiohttp is unavailable.
    """
    try:
        import aiohttp
    except ImportError:
        # Fallback to sync in thread pool
        return await asyncio.to_thread(
            call_context7_tool, tool_name, arguments, timeout, server_url
        )

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    headers = _build_headers()

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(server_url, json=payload, headers=headers) as resp:
                raw_text = await resp.text()
                if resp.status >= 400:
                    raise Context7APIError(
                        f"HTTP {resp.status} from Context7 server: {raw_text[:300]}"
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as conn_err:
        raise Context7ConnectionError(
            f"Failed async communication with Context7 at {server_url}: {conn_err}"
        ) from conn_err

    resp_json = _parse_sse_response(raw_text)
    return _extract_text_content(resp_json)


async def async_resolve_library_id(
    library_name: str,
    query: str = "",
    timeout: float = 15.0,
) -> list[LibraryCandidate]:
    """Asynchronous version of resolve_library_id."""
    if not library_name or not library_name.strip():
        raise ValueError("library_name cannot be empty")

    if library_name.strip().startswith("/"):
        return [LibraryCandidate(id=library_name.strip(), title=library_name.strip())]

    raw_text = await async_call_context7_tool(
        tool_name="resolve-library-id",
        arguments={
            "libraryName": library_name.strip(),
            "query": query.strip() or f"Overview and API documentation for {library_name}",
        },
        timeout=timeout,
    )

    candidates = _parse_libraries_output(raw_text)
    if not candidates:
        heuristic_id = f"/{library_name.strip()}/{library_name.strip()}"
        return [LibraryCandidate(id=heuristic_id, title=library_name.strip())]

    return candidates


async def async_query_docs(
    library_id: str,
    query: str,
    language: str = "Python",
    timeout: float = 15.0,
) -> str:
    """Asynchronous version of query_docs."""
    if not library_id or not library_id.strip():
        raise ValueError("library_id cannot be empty")
    if not query or not query.strip():
        raise ValueError("query cannot be empty")

    clean_id = library_id.strip()
    if not clean_id.startswith("/"):
        clean_id = f"/{clean_id}"

    args: dict[str, Any] = {
        "libraryId": clean_id,
        "query": query.strip(),
    }
    if language:
        args["language"] = language.strip()

    return await async_call_context7_tool(
        tool_name="query-docs",
        arguments=args,
        timeout=timeout,
    )


async def async_query_library_docs(
    library: str,
    query: str,
    language: str = "Python",
    library_id: str | None = None,
    timeout: float = 15.0,
) -> str:
    """Asynchronous version of query_library_docs."""
    target_id = library_id

    if not target_id and library.strip().startswith("/"):
        target_id = library.strip()

    if not target_id:
        candidates = await async_resolve_library_id(library, query=query, timeout=timeout)
        best = _pick_best_candidate(candidates, library)
        if best:
            target_id = best.id
        else:
            target_id = f"/{library.strip()}/{library.strip()}"

    return await async_query_docs(
        library_id=target_id,
        query=query,
        language=language,
        timeout=timeout,
    )


# -----------------------------------------------------------------------------
# CLI Interface
# -----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Query live framework documentation & snippets via Context7.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python tools/context7_docs.py aiogram "TelegramConflictError"
  python tools/context7_docs.py aiohttp "ClientSession timeout" --language Python
  python tools/context7_docs.py aiogram --resolve-only
  python tools/context7_docs.py /websites/aiogram_dev_en "TelegramConflictError"
""",
    )

    parser.add_argument(
        "library",
        help="Library name (e.g. 'aiogram', 'aiohttp') or exact Context7 ID (e.g. '/aiogram/aiogram')",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="general overview",
        help="Concept, class, function, or error to search for in documentation",
    )
    parser.add_argument(
        "-l",
        "--language",
        default="Python",
        help="Programming language to prioritize for code examples (default: Python)",
    )
    parser.add_argument(
        "-r",
        "--resolve-only",
        action="store_true",
        help="Only resolve and display candidate library IDs without querying documentation",
    )
    parser.add_argument(
        "--id",
        dest="library_id",
        default=None,
        help="Explicit Context7-compatible library ID to query (bypasses resolve step)",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=15.0,
        help="Network timeout in seconds (default: 15.0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON results",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print verbose diagnostics to stderr",
    )

    return parser


def main() -> int:
    """CLI execution entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.resolve_only:
            if args.verbose:
                sys.stderr.write(f"[INFO] Resolving candidates for '{args.library}'...\n")
            candidates = resolve_library_id(args.library, query=args.query, timeout=args.timeout)

            if args.json:
                print(json.dumps([c.to_dict() for c in candidates], indent=2, ensure_ascii=False))
            else:
                print(f"\nResolved Context7 candidates for '{args.library}':\n" + "=" * 60)
                for i, cand in enumerate(candidates, 1):
                    print(f"[{i}] {cand.title or cand.id}")
                    print(f"    ID:          {cand.id}")
                    if cand.description:
                        print(f"    Description: {cand.description}")
                    print(f"    Score:       {cand.benchmark_score:.2f} | Snippets: {cand.snippets} | Reputation: {cand.reputation or 'N/A'}")
                    if cand.versions:
                        print(f"    Versions:    {', '.join(cand.versions[:5])}")
                    print("-" * 60)
            return 0

        # Documentation lookup mode
        target_id = args.library_id
        if not target_id and args.library.startswith("/"):
            target_id = args.library

        if not target_id:
            if args.verbose:
                sys.stderr.write(f"[INFO] Resolving library ID for '{args.library}'...\n")
            candidates = resolve_library_id(args.library, query=args.query, timeout=args.timeout)
            best = _pick_best_candidate(candidates, args.library)
            if best:
                target_id = best.id
                if args.verbose:
                    sys.stderr.write(f"[INFO] Selected library ID: {target_id} (Score: {best.benchmark_score:.2f})\n")
            else:
                target_id = f"/{args.library.strip()}/{args.library.strip()}"

        if args.verbose:
            sys.stderr.write(f"[INFO] Querying docs from '{target_id}' for '{args.query}'...\n")

        docs = query_docs(
            library_id=target_id,
            query=args.query,
            language=args.language,
            timeout=args.timeout,
        )

        if args.json:
            out_obj = {
                "library": args.library,
                "library_id": target_id,
                "query": args.query,
                "language": args.language,
                "content": docs,
            }
            print(json.dumps(out_obj, indent=2, ensure_ascii=False))
        else:
            print(f"\n# Context7 Documentation: {target_id}")
            print(f"# Query: {args.query}\n")
            print(docs)

        return 0

    except Context7Error as c7_err:
        sys.stderr.write(f"\n[ERROR] Context7 operation failed: {c7_err}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n[ABORTED] Operation canceled by user.\n")
        return 130
    except Exception as exc:
        sys.stderr.write(f"\n[UNEXPECTED ERROR] {exc}\n")
        return 1


__all__ = [
    "LibraryCandidate",
    "Context7Error",
    "Context7ConnectionError",
    "Context7APIError",
    "Context7NotFoundError",
    "call_context7_tool",
    "resolve_library_id",
    "query_docs",
    "query_library_docs",
    "async_call_context7_tool",
    "async_resolve_library_id",
    "async_query_docs",
    "async_query_library_docs",
]

if __name__ == "__main__":
    sys.exit(main())
