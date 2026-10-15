from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import quote, urljoin, urlparse

from fastapi import Request

PLAYLIST_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
)

URI_ATTR_RE = re.compile(r'(URI=)(["\'])([^"\']+)\2', re.IGNORECASE)


def is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def looks_like_playlist(url: str, content_type: str, body_prefix: bytes) -> bool:
    path = urlparse(url).path.lower()
    if path.endswith((".m3u8", ".m3u")):
        return True
    ctype = content_type.split(";", 1)[0].strip().lower()
    if ctype in PLAYLIST_CONTENT_TYPES:
        return True
    stripped = body_prefix.lstrip()
    return stripped.startswith(b"#EXTM3U")


def proxy_url(request: Request, tvg_id: str, target: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/proxy/{tvg_id}?u={quote(target, safe='')}"


def rewrite_playlist(body: str, playlist_url: str, request: Request, tvg_id: str) -> str:
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if stripped.startswith("#"):
            if "URI=" in stripped.upper():
                lines.append(
                    URI_ATTR_RE.sub(
                        lambda match: _rewrite_uri_attr(match, playlist_url, request, tvg_id),
                        line,
                    )
                )
            else:
                lines.append(line)
            continue
        absolute = urljoin(playlist_url, stripped)
        lines.append(proxy_url(request, tvg_id, absolute))
    return "\n".join(lines) + "\n"


def _rewrite_uri_attr(
    match: re.Match[str],
    playlist_url: str,
    request: Request,
    tvg_id: str,
) -> str:
    absolute = urljoin(playlist_url, match.group(3))
    return f"{match.group(1)}{match.group(2)}{proxy_url(request, tvg_id, absolute)}{match.group(2)}"


def origin_headers(channel_headers: Mapping[str, str], incoming: Mapping[str, str]) -> dict[str, str]:
    headers = dict(channel_headers)
    if range_header := incoming.get("range"):
        headers["Range"] = range_header
    if if_range := incoming.get("if-range"):
        headers["If-Range"] = if_range
    return headers
