#!/usr/bin/env python3
"""
Bible Verse Lookup — MCP Server (KJV + Valera Purificada 1602)

Transports:
  stdio  — local use with Claude Desktop / Claude Code (TRANSPORT=stdio)
  http   — remote use via proxy to internal MCP server (default)

Environment variables:
  TRANSPORT     stdio | http  (default: http)
  PORT          public port   (default: 8000)
  API_KEY       bearer token  (optional but recommended)
"""

import os
import re
import sys
import json
import time
import threading
import urllib.request
import urllib.parse
from pathlib import Path

from mcp.server.fastmcp import FastMCP
import bible_data

# ---------------------------------------------------------------------------
# Auto-download KJV data
# ---------------------------------------------------------------------------
if not Path(bible_data.DATA_FILE).exists():
    print("KJV data not found — downloading now...", flush=True)
    try:
        import download_kjv
        download_kjv.download()
    except SystemExit:
        print("ERROR: Could not download KJV data.", file=sys.stderr)
        sys.exit(1)

bible_data._load()
print(f"KJV data loaded ({len(bible_data._cache[str(bible_data.DATA_FILE)]):,} verses)", flush=True)

# ---------------------------------------------------------------------------
# Auto-download RVP data
# ---------------------------------------------------------------------------
if not Path(bible_data.VP_FILE).exists():
    print("RVP data not found — downloading now...", flush=True)
    try:
        import download_vp
        download_vp.download()
    except SystemExit:
        print("WARNING: Could not download RVP data — Spanish tool unavailable.", flush=True)

_vp_available = Path(bible_data.VP_FILE).exists()
if _vp_available:
    bible_data._load(bible_data.VP_FILE)
    print(f"RVP data loaded ({len(bible_data._cache[str(bible_data.VP_FILE)]):,} verses)", flush=True)

# ---------------------------------------------------------------------------
# MCP server definition
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Bible Verse Lookup",
    instructions=(
        "Use kjv_lookup to find any KJV Bible verse by a partial text snippet "
        "and retrieve it with surrounding context. Use vp_lookup for the same "
        "in Spanish (Valera Purificada 1602). Always pass the returned "
        "passage back to the user verbatim — it already includes the reference."
    ),
)


# ---------------------------------------------------------------------------
# Web-search fallback — infer a Bible reference from search results
# ---------------------------------------------------------------------------

# Matches references like "John 3:16", "1 Cor 13:4", "Salmos 23:1"
_REF_PAT = re.compile(
    r'\b(\d\s+)?'                        # optional leading number (1, 2, 3)
    r'([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+'         # book name (may include accented chars)
    r'(?:\s+(?:of\s+)?[A-Za-z]+)?)'      # optional "of Solomon" etc.
    r'\s+(\d{1,3}):(\d{1,3})\b',
    re.IGNORECASE,
)


def _web_search_reference(snippet: str, lang: str = "en"):
    """
    Query DuckDuckGo Instant Answer API for snippet + 'Bible verse'.
    Returns (book_str, chapter, verse) if a reference is found, else None.
    """
    if lang == "es":
        q = f'Biblia versículo "{snippet}"'
    else:
        q = f'KJV Bible verse "{snippet}"'

    url = (
        "https://api.duckduckgo.com/?format=json&no_redirect=1&skip_disambig=1&q="
        + urllib.parse.quote(q)
    )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "BibleLookupBot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        # Gather all text fields from the DDG response
        parts = [
            data.get("Answer", ""),
            data.get("AbstractText", ""),
            data.get("AbstractSource", ""),
        ]
        for topic in data.get("RelatedTopics", []):
            if isinstance(topic, dict):
                parts.append(topic.get("Text", ""))

        combined = " ".join(parts)
        m = _REF_PAT.search(combined)
        if m:
            num = (m.group(1) or "").strip()
            book = ((num + " " + m.group(2)).strip() if num else m.group(2)).strip()
            return (book, int(m.group(3)), int(m.group(4)))
    except Exception:
        pass
    return None


def _lookup(snippet: str, data_file=None, lang: str = "en") -> int:
    """
    Three-stage verse lookup:
      1. All-words exact match in local data (highest precision).
      2. Web search → parse reference → local reference lookup.
      3. Fuzzy match fallback (original behaviour).
    Returns the verse index to pass to get_passage().
    """
    # Stage 1
    idx = bible_data.find_verse_by_all_words(snippet, data_file)
    if idx != -1:
        return idx

    # Stage 2
    ref = _web_search_reference(snippet, lang)
    if ref:
        book, ch, v = ref
        idx = bible_data.find_verse_by_reference(book, ch, v, data_file)
        if idx != -1:
            return idx

    # Stage 3
    return bible_data.find_verse_index(snippet, data_file)


@mcp.tool()
def kjv_lookup(snippet: str, context_verses: int = 3) -> str:
    """Find the closest matching KJV verse and return it with context.

    Args:
        snippet: Any partial or complete KJV verse text to search for.
        context_verses: How many verses to include before and after the match
                        (default 3; set to 0 for the single verse only).

    Returns:
        The passage as plain text — one verse per paragraph, with the full
        passage reference (e.g. "John 3:14-18") on the last line.
    """
    try:
        idx = _lookup(snippet, lang="en")
        passage = bible_data.get_passage(idx, context_verses)
        return bible_data.format_passage(passage)
    except Exception as exc:
        return f"Error during verse lookup: {exc}"


@mcp.tool()
def vp_lookup(snippet: str, context_verses: int = 3) -> str:
    """Find the closest matching verse in the Valera Purificada 1602 (Spanish) and return it with context.

    Args:
        snippet: Any partial or complete Spanish verse text to search for.
        context_verses: How many verses to include before and after the match
                        (default 3; set to 0 for the single verse only).

    Returns:
        The passage as plain text — one verse per paragraph, with the full
        passage reference on the last line.
    """
    if not _vp_available:
        return "Error: VP 1602 Spanish Bible data is not available on this server."
    try:
        idx = _lookup(snippet, bible_data.VP_FILE, lang="es")
        passage = bible_data.get_passage(idx, context_verses, bible_data.VP_FILE)
        return bible_data.format_passage(passage)
    except Exception as exc:
        return f"Error during verse lookup: {exc}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    transport = os.environ.get("TRANSPORT", "http").lower()

    if transport == "stdio":
        mcp.run(transport="stdio")

    else:
        import uvicorn
        import httpx

        PUBLIC_PORT = int(os.environ.get("PORT", 8000))
        INTERNAL_PORT = PUBLIC_PORT + 1  # e.g. 8001
        API_KEY = os.environ.get("API_KEY", "").strip()
        BEARER = f"Bearer {API_KEY}" if API_KEY else None

        # ── Start internal MCP server on localhost ──────────────────────────
        # Running on 127.0.0.1 means the MCP SDK's host security check sees
        # "localhost" as the Host header and accepts it.
        def _run_mcp():
            import asyncio
            import uvicorn as _uvi
            print(f"Internal MCP starting on port {INTERNAL_PORT}", flush=True)
            try:
                _app = mcp.streamable_http_app(stateless_http=True)
            except TypeError:
                _app = mcp.streamable_http_app()
            config = _uvi.Config(
                _app,
                host="127.0.0.1",
                port=INTERNAL_PORT,
                log_level="warning",
            )
            asyncio.run(_uvi.Server(config).serve())

        mcp_thread = threading.Thread(target=_run_mcp, daemon=True)
        mcp_thread.start()

        time.sleep(2)  # Give internal MCP server time to start
        print("Internal MCP server ready", flush=True)

        BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

        # ── Public-facing ASGI proxy ────────────────────────────────────────
        async def _send_json(send, body: dict, status: int = 200):
            raw = json.dumps(body).encode()
            await send({"type": "http.response.start", "status": status,
                        "headers": [[b"content-type", b"application/json"],
                                    [b"content-length", str(len(raw)).encode()]]})
            await send({"type": "http.response.body", "body": raw})

        async def _send_redirect(send, location: str):
            loc = location.encode()
            await send({"type": "http.response.start", "status": 302,
                        "headers": [[b"location", loc],
                                    [b"content-length", b"0"]]})
            await send({"type": "http.response.body", "body": b""})

        def _lookup_page(q: str, n: int, v: str, result: str, action: str = "/lookup") -> str:
            q_esc = q.replace('"', "&quot;")
            lang = "es" if v == "vp" else "en"
            title = "Búsqueda de Versículos (VP 1602)" if v == "vp" else "KJV Bible Verse Lookup"
            placeholder = "Escriba un fragmento de versículo…" if v == "vp" else "Enter a verse snippet…"
            btn = "Buscar" if v == "vp" else "Look up"
            if result:
                lines = result.split("\n\n")
                reference = lines[-1] if lines else ""
                vlines = lines[:-1]
                body = "".join(f"<p>{vl}</p>" for vl in vlines if vl.strip())
                body += f'<p class="ref">{reference}</p>'
            else:
                body = ""
            ver_opts = (
                f'<option value="kjv"{"selected" if v=="kjv" else ""}>English — KJV</option>'
                f'<option value="vp"{"selected" if v=="vp" else ""}>Español — VP 1602</option>'
            )
            ctx_opts = "".join(
                f'<option value="{i}"{"selected" if i==n else ""}>{i}</option>'
                for i in range(0, 26)
            )
            return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem; background: #fdf6e3; color: #333; }}
  h1 {{ font-size: 1.4rem; color: #5a3e1b; }}
  form {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1.5rem; }}
  input[name=q] {{ flex: 1; min-width: 200px; padding: .4rem .6rem; font-size: 1rem; border: 1px solid #ccc; border-radius: 4px; }}
  select {{ padding: .4rem; border: 1px solid #ccc; border-radius: 4px; }}
  button {{ padding: .4rem 1rem; background: #5a3e1b; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; }}
  p {{ line-height: 1.7; margin: .6rem 0; }}
  p.ref {{ font-style: italic; color: #5a3e1b; margin-top: 1rem; font-size: .95rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<form method="get" action="{action}">
  <input name="q" type="text" placeholder="{placeholder}" value="{q_esc}" required>
  <select name="v">{ver_opts}</select>
  <select name="n">{ctx_opts}</select>
  <button type="submit">{btn}</button>
</form>
{body}
</body>
</html>"""

        class ProxyApp:
            """Auth + health wrapper that proxies to the internal MCP server."""

            async def __call__(self, scope, receive, send):
                if scope["type"] == "lifespan":
                    await receive()
                    await send({"type": "lifespan.startup.complete"})
                    await receive()
                    await send({"type": "lifespan.shutdown.complete"})
                    return

                if scope["type"] != "http":
                    return

                path = scope.get("path", "")
                method = scope.get("method", "GET")
                qs_raw = scope.get("query_string", b"").decode()

                # CORS preflight
                if method == "OPTIONS":
                    await send({"type": "http.response.start", "status": 204,
                                "headers": [[b"access-control-allow-origin", b"*"],
                                            [b"access-control-allow-methods", b"GET, POST, OPTIONS"],
                                            [b"access-control-allow-headers", b"*"]]})
                    await send({"type": "http.response.body", "body": b""})
                    return

                # Health probe — no auth
                if path == "/health":
                    await _send_json(send, {"status": "ok"})
                    return

                # ── Browser-friendly verse lookup ───────────────────────────
                if path in ("/lookup", "/busca"):
                    import urllib.parse as _up
                    params = dict(_up.parse_qsl(qs_raw))
                    q = params.get("q", "").strip()
                    # /busca defaults to VP; /lookup defaults to KJV
                    default_v = "vp" if path == "/busca" else "kjv"
                    v = params.get("v", default_v).lower()
                    try:
                        n = max(0, min(int(params.get("n", "3")), 25))
                    except ValueError:
                        n = 3

                    data_file = bible_data.VP_FILE if v == "vp" else bible_data.DATA_FILE
                    result = ""
                    if q:
                        try:
                            lang = "es" if v == "vp" else "en"
                            idx = _lookup(q, data_file, lang)
                            passage = bible_data.get_passage(idx, n, data_file)
                            result = bible_data.format_passage(passage)
                        except Exception as exc:
                            result = f"Error: {exc}"
                    html = _lookup_page(q, n, v, result, path)

                    raw = html.encode()
                    await send({"type": "http.response.start", "status": 200,
                                "headers": [[b"content-type", b"text/html; charset=utf-8"],
                                            [b"content-length", str(len(raw)).encode()]]})
                    await send({"type": "http.response.body", "body": raw})
                    return

                # ── Minimal OAuth 2.0 server (for Claude.ai connector) ──────
                if path == "/.well-known/oauth-authorization-server":
                    issuer = BASE_URL or f"http://localhost:{PUBLIC_PORT}"
                    await _send_json(send, {
                        "issuer": issuer,
                        "authorization_endpoint": f"{issuer}/authorize",
                        "token_endpoint": f"{issuer}/token",
                        "response_types_supported": ["code"],
                        "grant_types_supported": ["authorization_code"],
                        "code_challenge_methods_supported": ["S256", "plain"],
                    })
                    return

                if path == "/authorize":
                    import urllib.parse as _up
                    params = dict(_up.parse_qsl(qs_raw))
                    redirect_uri = params.get("redirect_uri", "")
                    state = params.get("state", "")
                    # Use the API_KEY itself as the authorization code
                    code = API_KEY if API_KEY else "open"
                    sep = "&" if "?" in redirect_uri else "?"
                    location = f"{redirect_uri}{sep}code={_up.quote(code, safe='')}"
                    if state:
                        location += f"&state={_up.quote(state, safe='')}"
                    await _send_redirect(send, location)
                    return

                if path == "/token" and method == "POST":
                    # Exchange any code for our static bearer token
                    await _send_json(send, {
                        "access_token": API_KEY if API_KEY else "open",
                        "token_type": "bearer",
                        "expires_in": 315360000,  # ~10 years
                    })
                    return

                # Bearer auth
                if BEARER:
                    hdrs = {k.lower(): v for k, v in scope.get("headers", [])}
                    auth = hdrs.get(b"authorization", b"").decode(errors="replace")
                    if auth != BEARER:
                        print(f"Auth failed: {repr(auth)}", flush=True)
                        await _send_json(send, {"error": "Unauthorized"}, 401)
                        return

                # Read request body
                body = b""
                while True:
                    msg = await receive()
                    body += msg.get("body", b"")
                    if not msg.get("more_body", False):
                        break

                # Forward headers, override Host so MCP security passes
                fwd_headers = {
                    k.decode(errors="replace"): v.decode(errors="replace")
                    for k, v in scope.get("headers", [])
                    if k.lower() not in (b"host", b"authorization")
                }
                fwd_headers["host"] = f"localhost:{INTERNAL_PORT}"  # must match MCP server's bound port
                fwd_headers.setdefault("accept", "application/json, text/event-stream")

                url = f"http://127.0.0.1:{INTERNAL_PORT}{path}"
                if qs_raw:
                    url += f"?{qs_raw}"

                # Stream the response back
                async with httpx.AsyncClient(timeout=60.0) as client:
                    try:
                        async with client.stream(
                            method, url,
                            content=body,
                            headers=fwd_headers,
                        ) as resp:
                            await send({
                                "type": "http.response.start",
                                "status": resp.status_code,
                                "headers": [
                                    [k.lower().encode(), v.encode()]
                                    for k, v in resp.headers.items()
                                ],
                            })
                            async for chunk in resp.aiter_bytes():
                                await send({
                                    "type": "http.response.body",
                                    "body": chunk,
                                    "more_body": True,
                                })
                            await send({
                                "type": "http.response.body",
                                "body": b"",
                                "more_body": False,
                            })
                    except Exception as exc:
                        print(f"Proxy error: {exc}", flush=True)
                        await _send_json(send, {"error": "proxy error"}, 502)

        print(f"Starting public proxy on 0.0.0.0:{PUBLIC_PORT} "
              f"({'auth enabled' if BEARER else 'open'})", flush=True)

        uvicorn.run(ProxyApp(), host="0.0.0.0", port=PUBLIC_PORT,
                    proxy_headers=True, forwarded_allow_ips="*")
