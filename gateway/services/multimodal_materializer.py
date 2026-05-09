from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from config import VISION_YTDLP_COOKIES_FROM_BROWSER

OCTET_STREAM = "application/octet-stream"
VIDEO_URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
logger = logging.getLogger(__name__)
_HTTP_FETCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=20.0, pool=10.0)
_HTTP_FETCH_CLIENT = httpx.AsyncClient(timeout=_HTTP_FETCH_TIMEOUT, follow_redirects=True)


def _is_data_url(raw_url: str, *, prefix: str) -> bool:
    return raw_url.strip().lower().startswith(prefix)


def _decode_data_url(raw_url: str) -> tuple[bytes, str]:
    header, payload = raw_url.split(",", 1)
    mime = OCTET_STREAM
    if ";" in header:
        mime = header[5 : header.index(";")] or mime
    elif ":" in header:
        mime = header.split(":", 1)[1] or mime
    data = base64.b64decode(payload, validate=False)
    return data, mime.lower()


async def _fetch_bytes_from_url(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme == "file":
        file_path = Path(unquote(parsed.path or "")).expanduser()
        if not file_path.exists() or not file_path.is_file():
            raise RuntimeError(f"file_not_found:{file_path}")
        data = await asyncio.to_thread(file_path.read_bytes)
        mime = mimetypes.guess_type(str(file_path))[0] or OCTET_STREAM
        return data, mime
    if scheme in {"http", "https"}:
        res = await _HTTP_FETCH_CLIENT.get(url)
        if res.status_code != 200:
            raise RuntimeError(f"http_fetch_failed:{res.status_code}")
        content_type = str(res.headers.get("content-type") or "").split(";")[0].strip().lower()
        mime = content_type or OCTET_STREAM
        return bytes(res.content), mime
    raise RuntimeError(f"unsupported_url_scheme:{scheme or 'none'}")


async def close_multimodal_http_client() -> None:
    try:
        await _HTTP_FETCH_CLIENT.aclose()
    except Exception:
        return


def _to_data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return "youtube.com" in host or "youtu.be" in host


async def _resolve_youtube_stream_url(youtube_url: str) -> str:
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-g",
        "-f",
        "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
    ]
    if VISION_YTDLP_COOKIES_FROM_BROWSER:
        cmd.extend(["--cookies-from-browser", VISION_YTDLP_COOKIES_FROM_BROWSER])
    cmd.append(youtube_url)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = (stderr or b"").decode("utf-8", errors="replace").strip() or "youtube_resolve_failed"
        raise RuntimeError(msg)
    candidates = [line.strip() for line in (stdout or b"").decode("utf-8", errors="replace").splitlines() if line.strip()]
    if not candidates:
        raise RuntimeError("youtube_stream_url_not_found")
    return candidates[0]


async def _download_youtube_video_bytes(youtube_url: str) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory(prefix="vision_yt_") as temp_dir:
        temp_path = Path(temp_dir)
        output_template = str(temp_path / "video.%(ext)s")
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f",
            "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
            "-o",
            output_template,
        ]
        if VISION_YTDLP_COOKIES_FROM_BROWSER:
            cmd.extend(["--cookies-from-browser", VISION_YTDLP_COOKIES_FROM_BROWSER])
        cmd.append(youtube_url)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = (stderr or b"").decode("utf-8", errors="replace").strip() or "youtube_download_failed"
            raise RuntimeError(msg)
        candidates = sorted(temp_path.glob("video.*"))
        if not candidates:
            raise RuntimeError("youtube_video_file_missing")
        video_path = candidates[0]
        data = await asyncio.to_thread(video_path.read_bytes)
        mime = mimetypes.guess_type(str(video_path))[0] or "video/mp4"
        return data, mime


async def _fetch_youtube_metadata_summary(youtube_url: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "--skip-download",
        "--no-playlist",
        "--dump-json",
        youtube_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    try:
        obj = json.loads((stdout or b"{}").decode("utf-8", errors="replace"))
    except Exception:
        return None
    title = str(obj.get("title") or "").strip()
    uploader = str(obj.get("uploader") or "").strip()
    duration = obj.get("duration")
    duration_text = f"{int(duration)}s" if isinstance(duration, (int, float)) else ""
    description = str(obj.get("description") or "").strip()
    if len(description) > 1200:
        description = description[:1200] + "..."
    lines = [line for line in [f"title: {title}" if title else "", f"uploader: {uploader}" if uploader else "", f"duration: {duration_text}" if duration_text else "", f"description: {description}" if description else ""] if line]
    if not lines:
        return None
    return "[youtube metadata fallback]\n" + "\n".join(lines)


async def _extract_video_frame_data_urls_from_input(
    *,
    input_source: str,
    max_frames: int,
    frame_interval_seconds: float,
    max_image_bytes: int,
) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="vision_video_") as temp_dir:
        temp_path = Path(temp_dir)
        output_pattern = str(temp_path / "frame_%03d.jpg")
        fps = max(0.1, 1.0 / max(0.25, frame_interval_seconds))
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            input_source,
            "-vf",
            f"fps={fps}",
            "-frames:v",
            str(max(1, max_frames)),
            output_pattern,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = (stderr or b"").decode("utf-8", errors="replace").strip() or "ffmpeg_failed"
            raise RuntimeError(msg)
        frame_urls: list[str] = []
        for frame_path in sorted(temp_path.glob("frame_*.jpg")):
            frame_bytes = await asyncio.to_thread(frame_path.read_bytes)
            if len(frame_bytes) > max_image_bytes:
                continue
            frame_urls.append(_to_data_url(frame_bytes, "image/jpeg"))
        return frame_urls


async def _extract_video_frame_data_urls(
    *,
    video_bytes: bytes,
    video_mime: str,
    max_frames: int,
    frame_interval_seconds: float,
    max_image_bytes: int,
) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="vision_video_") as temp_dir:
        temp_path = Path(temp_dir)
        ext = mimetypes.guess_extension(video_mime) or ".mp4"
        input_path = temp_path / f"input{ext}"
        await asyncio.to_thread(input_path.write_bytes, video_bytes)
        return await _extract_video_frame_data_urls_from_input(
            input_source=str(input_path),
            max_frames=max_frames,
            frame_interval_seconds=frame_interval_seconds,
            max_image_bytes=max_image_bytes,
        )


def promote_text_video_links(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    promoted: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            promoted.append(msg)
            continue
        content = msg.get("content")
        if isinstance(content, str):
            urls = [u.rstrip(").,!?;:\"'") for u in VIDEO_URL_RE.findall(content)]
            video_urls = [u for u in urls if _is_youtube_url(u) or u.lower().endswith((".mp4", ".mov", ".m4v", ".webm"))]
            if video_urls:
                parts: list[dict[str, Any]] = [{"type": "text", "text": content}]
                for url in video_urls:
                    parts.append({"type": "video_url", "video_url": {"url": url}})
                promoted.append({**msg, "content": parts})
                continue
        promoted.append(msg)
    return promoted


def contains_video_url_part(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and str(part.get("type") or "").strip().lower() == "video_url":
                return True
    return False


def contains_image_url_part(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and str(part.get("type") or "").strip().lower() == "image_url":
                return True
    return False


async def materialize_multimodal_parts(
    messages: list[dict[str, Any]],
    *,
    max_image_bytes: int,
    max_video_bytes: int,
    max_video_frames: int,
    video_frame_interval_seconds: float,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            normalized.append(msg)
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            normalized.append(msg)
            continue
        next_parts: list[Any] = []
        for part in content:
            if not isinstance(part, dict):
                next_parts.append(part)
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type == "image_url":
                image_obj = part.get("image_url") or {}
                if not isinstance(image_obj, dict):
                    next_parts.append(part)
                    continue
                raw_url = str(image_obj.get("url") or "").strip()
                if not raw_url or _is_data_url(raw_url, prefix="data:image/"):
                    next_parts.append(part)
                    continue
                try:
                    data, mime = await _fetch_bytes_from_url(raw_url)
                    if len(data) > max_image_bytes:
                        raise RuntimeError(f"image_too_large:{len(data)}")
                    next_parts.append({**part, "image_url": {**image_obj, "url": _to_data_url(data, mime)}})
                except Exception as exc:
                    logger.warning("image_materialization_failed url=%s reason=%s", raw_url, str(exc))
                    next_parts.append(part)
                continue
            if part_type == "video_url":
                video_obj = part.get("video_url") or {}
                if not isinstance(video_obj, dict):
                    next_parts.append(part)
                    continue
                raw_url = str(video_obj.get("url") or "").strip()
                if not raw_url:
                    next_parts.append(part)
                    continue
                try:
                    if _is_youtube_url(raw_url):
                        metadata_summary = await _fetch_youtube_metadata_summary(raw_url)
                        try:
                            stream_url = await _resolve_youtube_stream_url(raw_url)
                            frame_urls = await _extract_video_frame_data_urls_from_input(
                                input_source=stream_url,
                                max_frames=max_video_frames,
                                frame_interval_seconds=video_frame_interval_seconds,
                                max_image_bytes=max_image_bytes,
                            )
                        except Exception:
                            video_data, video_mime = await _download_youtube_video_bytes(raw_url)
                            if len(video_data) > max_video_bytes:
                                raise RuntimeError(f"video_too_large:{len(video_data)}")
                            frame_urls = await _extract_video_frame_data_urls(
                                video_bytes=video_data,
                                video_mime=video_mime,
                                max_frames=max_video_frames,
                                frame_interval_seconds=video_frame_interval_seconds,
                                max_image_bytes=max_image_bytes,
                            )
                        if not frame_urls and metadata_summary:
                            next_parts.append({"type": "text", "text": metadata_summary})
                            continue
                    elif _is_data_url(raw_url, prefix="data:video/"):
                        video_data, video_mime = _decode_data_url(raw_url)
                        if len(video_data) > max_video_bytes:
                            raise RuntimeError(f"video_too_large:{len(video_data)}")
                        frame_urls = await _extract_video_frame_data_urls(
                            video_bytes=video_data,
                            video_mime=video_mime,
                            max_frames=max_video_frames,
                            frame_interval_seconds=video_frame_interval_seconds,
                            max_image_bytes=max_image_bytes,
                        )
                    else:
                        video_data, video_mime = await _fetch_bytes_from_url(raw_url)
                        if len(video_data) > max_video_bytes:
                            raise RuntimeError(f"video_too_large:{len(video_data)}")
                        frame_urls = await _extract_video_frame_data_urls(
                            video_bytes=video_data,
                            video_mime=video_mime,
                            max_frames=max_video_frames,
                            frame_interval_seconds=video_frame_interval_seconds,
                            max_image_bytes=max_image_bytes,
                        )
                    if frame_urls:
                        next_parts.append({"type": "text", "text": f"[video decoded into {len(frame_urls)} frame(s)]"})
                        for frame_url in frame_urls:
                            next_parts.append({"type": "image_url", "image_url": {"url": frame_url}})
                    else:
                        next_parts.append(part)
                except Exception as exc:
                    logger.warning("video_materialization_failed url=%s reason=%s", raw_url, str(exc))
                    if _is_youtube_url(raw_url):
                        metadata_summary = await _fetch_youtube_metadata_summary(raw_url)
                        if metadata_summary:
                            next_parts.append({"type": "text", "text": metadata_summary})
                            continue
                    next_parts.append(part)
                continue
            next_parts.append(part)
        normalized.append({**msg, "content": next_parts})
    return normalized
