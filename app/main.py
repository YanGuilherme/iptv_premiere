from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import time
from urllib.parse import unquote, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from app.channels import CHANNELS, channel_to_dict, get_channel, to_m3u
from app.hls import is_http_url, looks_like_playlist, origin_headers, rewrite_playlist

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

SEGMENT_SUFFIXES = {
    ".aac",
    ".ac3",
    ".ec3",
    ".m4a",
    ".m4s",
    ".mp4",
    ".ts",
}

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = httpx.Timeout(60.0, connect=10.0)
    limits = httpx.Limits(keepalive_expiry=30.0)
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, limits=limits
    ) as client:
        app.state.http = client
        yield


app = FastAPI(
    title="IPTV",
    description="API IPTV que serve M3U e injeta headers HLS de forma recursiva.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Range", "Accept-Ranges"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "IPTV",
        "playlist": "/playlist.m3u",
        "channels": "/channels",
        "live": "/live/{tvg_id}",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/channels")
def channels() -> JSONResponse:
    return JSONResponse([channel_to_dict(channel) for channel in CHANNELS])


@app.get("/playlist.m3u", response_class=PlainTextResponse)
def playlist(request: Request) -> PlainTextResponse:
    return PlainTextResponse(
        content=to_m3u(base_url=str(request.base_url)),
        media_type="application/vnd.apple.mpegurl",
        headers={"Content-Disposition": 'inline; filename="playlist.m3u"'},
    )



@app.api_route("/live/{tvg_id}.m3u8", methods=["GET", "HEAD"])
async def live_m3u8(tvg_id: str, request: Request) -> Response:
    channel = get_channel(tvg_id)

    if channel is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    return await _proxy_resource(
        request,
        channel.tvg_id,
        channel.url,
        channel.headers,
        force_playlist=True,
    )


@app.api_route("/live/{tvg_id}", methods=["GET", "HEAD"])
async def live(tvg_id: str, request: Request) -> Response:
    channel = get_channel(tvg_id)

    if channel is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    return await _proxy_resource(
        request,
        channel.tvg_id,
        channel.url,
        channel.headers,
        force_playlist=True,
    )


@app.api_route("/proxy/{tvg_id}", methods=["GET", "HEAD"])
async def proxy(tvg_id: str, request: Request, u: str) -> Response:
    channel = get_channel(tvg_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")
    target = unquote(u)
    if not is_http_url(target):
        raise HTTPException(status_code=400, detail="URL de mídia inválida")
    return await _proxy_resource(request, channel.tvg_id, target, channel.headers)


async def _proxy_resource(
    request: Request,
    tvg_id: str,
    target: str,
    channel_headers: dict[str, str],
    force_playlist: bool = False,
) -> Response:
    client: httpx.AsyncClient = request.app.state.http
    started_at = time.perf_counter()
    headers = origin_headers(channel_headers, request.headers)
    resource_path = urlparse(target).path
    resource_name = resource_path.rsplit("/", 1)[-1] or resource_path or "/"
    is_segment = resource_path.lower().endswith(tuple(SEGMENT_SUFFIXES))

    upstream_request = client.build_request(request.method, target, headers=headers)

    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        logger.warning(
            "Origem indisponível canal=%s recurso=%s erro=%s",
            tvg_id,
            resource_name,
            type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail=f"Falha ao buscar origem: {exc}") from exc

    try:
        if upstream.status_code >= 400:
            logger.warning(
                "Origem recusou recurso canal=%s recurso=%s status=%d",
                tvg_id,
                resource_name,
                upstream.status_code,
            )
            raise HTTPException(status_code=upstream.status_code, detail="Origem recusou a mídia")

        content_type = upstream.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()
        if urlparse(target).path.lower().endswith(".ts"):
            content_type = "video/mp2t"

        if force_playlist or looks_like_playlist(target, content_type, b""):
            if request.method == "HEAD":
                logger.info(
                    "Playlist consultada canal=%s recurso=%s status=%d duracao_ms=%.1f",
                    tvg_id,
                    resource_name,
                    upstream.status_code,
                    (time.perf_counter() - started_at) * 1000,
                )
                return Response(
                    status_code=200,
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-store"},
                )
            body = await upstream.aread()
            rewritten = rewrite_playlist(
                body.decode("utf-8", errors="replace"), target, request, tvg_id
            )
            reference_count = sum(
                1 for line in rewritten.splitlines() if line.strip() and not line.lstrip().startswith("#")
            )
            logger.info(
                "Playlist entregue canal=%s recurso=%s status=200 referencias=%d bytes=%d duracao_ms=%.1f",
                tvg_id,
                resource_name,
                reference_count,
                len(rewritten.encode("utf-8")),
                (time.perf_counter() - started_at) * 1000,
            )
            return PlainTextResponse(
                content=rewritten,
                media_type="application/vnd.apple.mpegurl",
                status_code=200,
                headers={"Cache-Control": "no-store"},
            )

        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in HOP_BY_HOP
            and key.lower() != "content-type"
        }
        if request.method == "HEAD":
            logger.info(
                "%s consultado canal=%s recurso=%s status=%d duracao_ms=%.1f",
                "Segmento" if is_segment else "Mídia",
                tvg_id,
                resource_name,
                upstream.status_code,
                (time.perf_counter() - started_at) * 1000,
            )
            return Response(
                status_code=upstream.status_code,
                media_type=content_type,
                headers=response_headers,
            )

        stream_resp = upstream
        upstream = None

        async def stream():
            bytes_sent = 0
            try:
                async for chunk in stream_resp.aiter_bytes():
                    bytes_sent += len(chunk)
                    yield chunk
            except asyncio.CancelledError:
                logger.warning(
                    "%s interrompido canal=%s recurso=%s status=%d bytes=%d duracao_ms=%.1f",
                    "Segmento" if is_segment else "Mídia",
                    tvg_id,
                    resource_name,
                    stream_resp.status_code,
                    bytes_sent,
                    (time.perf_counter() - started_at) * 1000,
                )
                raise
            except Exception:
                logger.exception(
                    "Falha ao entregar %s canal=%s recurso=%s bytes=%d duracao_ms=%.1f",
                    "segmento" if is_segment else "mídia",
                    tvg_id,
                    resource_name,
                    bytes_sent,
                    (time.perf_counter() - started_at) * 1000,
                )
                raise
            else:
                logger.info(
                    "%s entregue canal=%s recurso=%s status=%d bytes=%d duracao_ms=%.1f",
                    "Segmento" if is_segment else "Mídia",
                    tvg_id,
                    resource_name,
                    stream_resp.status_code,
                    bytes_sent,
                    (time.perf_counter() - started_at) * 1000,
                )
            finally:
                await stream_resp.aclose()

        return StreamingResponse(
            stream(),
            status_code=stream_resp.status_code,
            media_type=content_type,
            headers=response_headers,
        )
    finally:
        if upstream is not None:
            await upstream.aclose()
