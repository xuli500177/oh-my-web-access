#!/usr/bin/env python3
"""
Exa MCP Search — free web search via Exa's public MCP endpoint.

No API key needed. 1000 requests/month free tier.
High-quality results especially for English/technical/academic content.

Usage:
  exa-search.py "search query"                    # Basic search
  exa-search.py "query" -n 5                      # Number of results (default 3)
  exa-search.py "query" --content                 # Include full page content
  exa-search.py "query" --recency week            # Time filter: day/week/month/year
  exa-search.py "query" --domains github.com      # Limit to specific domains
  exa-search.py "query" --exclude pinterest.com   # Exclude domains
  exa-search.py "query" --max-chars 5000          # Max content characters
"""

import argparse, json, sys, urllib.request

EXA_MCP_URL = "https://mcp.exa.ai/mcp"
DEFAULT_RESULTS = 3
MAX_RESULTS = 20
DEFAULT_MAX_CHARS = 3000


def search_exa(query: str, num_results: int = DEFAULT_RESULTS,
               include_content: bool = False,
               recency: str = None,
               domains: list[str] = None,
               exclude_domains: list[str] = None,
               max_chars: int = DEFAULT_MAX_CHARS) -> list[dict]:
    """
    Search via Exa MCP endpoint. Returns list of results.
    Each result: {title, url, content, published_date}
    """
    # Build enriched query with filters
    parts = [query]
    if domains:
        for d in domains:
            parts.append(f"site:{d}")
    if exclude_domains:
        for d in exclude_domains:
            parts.append(f"-site:{d}")
    if recency:
        from datetime import datetime
        now = datetime.now()
        recency_hints = {
            "day": "past 24 hours",
            "week": "past week",
            "month": f"{now.strftime('%B')} {now.year}",
            "year": str(now.year),
        }
        hint = recency_hints.get(recency)
        if hint:
            parts.append(hint)

    enriched_query = " ".join(parts)

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "web_search_exa",
            "arguments": {
                "query": enriched_query,
                "numResults": min(num_results, MAX_RESULTS),
                "livecrawl": "fallback",
                "type": "auto",
                "contextMaxCharacters": max_chars if include_content else 1000,
            },
        },
    }

    req = urllib.request.Request(
        EXA_MCP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", errors="replace")

    # Parse SSE or direct JSON response
    parsed = _parse_response(body)
    if not parsed:
        return []

    text = ""
    if parsed.get("result", {}).get("content"):
        for item in parsed["result"]["content"]:
            if item.get("type") == "text" and item.get("text", "").strip():
                text = item["text"]
                break

    if parsed.get("error"):
        raise RuntimeError(
            f"Exa error: {parsed['error'].get('message', 'unknown')}")

    if not text:
        return []

    return _parse_results(text)


def _parse_response(body: str) -> dict | None:
    """Parse SSE stream or direct JSON."""
    # Try SSE data lines first
    for line in body.split("\n"):
        if line.startswith("data: "):
            payload = line[6:].strip()
            if not payload:
                continue
            try:
                candidate = json.loads(payload)
                if candidate.get("result") or candidate.get("error"):
                    return candidate
            except json.JSONDecodeError:
                continue

    # Try direct JSON
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _parse_results(text: str) -> list[dict]:
    """Parse Exa's formatted text output into structured results."""
    results = []
    blocks = text.split("\n---\n")

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        result = {}

        title_m = block.split("\n")[0] if block else ""
        if title_m.startswith("Title: "):
            result["title"] = title_m[7:].strip()
        else:
            result["title"] = title_m.strip()

        for line in block.split("\n"):
            if line.startswith("URL: "):
                result["url"] = line[5:].strip()
            elif line.startswith("Published: "):
                result["published_date"] = line[11:].strip()
            elif line.startswith("Author: "):
                result["author"] = line[8:].strip()

        # Extract content after "Text:" or "Highlights:"
        content = ""
        text_idx = block.find("\nText: ")
        if text_idx >= 0:
            content = block[text_idx + 7:].strip()
        else:
            hl_idx = block.find("\nHighlights:\n")
            if hl_idx >= 0:
                content = block[hl_idx + 12:].strip()

        result["content"] = content.rstrip("-").strip()
        if result.get("url"):
            results.append(result)

    return results


def main():
    p = argparse.ArgumentParser(description="Exa MCP Web Search (free)")
    p.add_argument("query", help="Search query")
    p.add_argument("-n", "--num", type=int, default=DEFAULT_RESULTS,
                   help=f"Number of results (default {DEFAULT_RESULTS}, max {MAX_RESULTS})")
    p.add_argument("--content", action="store_true",
                   help="Include full page content")
    p.add_argument("--recency", choices=["day", "week", "month", "year"],
                   help="Time filter")
    p.add_argument("--domains", nargs="+", help="Limit to these domains")
    p.add_argument("--exclude", nargs="+", help="Exclude these domains")
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                   help=f"Max content characters (default {DEFAULT_MAX_CHARS})")

    args = p.parse_args()

    try:
        results = search_exa(
            query=args.query,
            num_results=args.num,
            include_content=args.content,
            recency=args.recency,
            domains=args.domains,
            exclude_domains=args.exclude,
            max_chars=args.max_chars,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No results found.", file=sys.stderr)
        sys.exit(1)

    # Output formatted results
    for i, r in enumerate(results, 1):
        print(f"{'─' * 60}")
        print(f"[{i}] {r.get('title', 'No title')}")
        print(f"    {r.get('url', '')}")
        if r.get("published_date"):
            print(f"    Published: {r['published_date']}")
        if r.get("author"):
            print(f"    Author: {r['author']}")
        if r.get("content") and args.content:
            content = r["content"]
            if len(content) > args.max_chars:
                content = content[:args.max_chars] + "..."
            print(f"\n    {content}\n")
    print(f"{'─' * 60}")
    print(f"Total: {len(results)} results")


if __name__ == "__main__":
    main()
