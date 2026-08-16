"""Physical five-view and exact 3x3 storyboard image operations."""

from __future__ import annotations

import base64
import io
import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps


Image.MAX_IMAGE_PIXELS = 60_000_000
MAX_REMOTE_IMAGE_BYTES = 30 * 1024 * 1024


def _validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("image URL must use HTTP(S)")
    if parsed.scheme == "http" and os.getenv("ALLOW_INSECURE_MEDIA_HTTP", "0") != "1":
        raise ValueError("remote image URL must use HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("credentials in media URLs are not allowed")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("private or local media hosts are not allowed")


def _download_image(url: str) -> bytes:
    current = url
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for _ in range(4):
            _validate_remote_url(current)
            with client.stream("GET", current, headers={"Accept": "image/*"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("image redirect has no location")
                    current = str(response.url.join(location))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if content_type and not content_type.startswith("image/"):
                    raise ValueError("remote resource is not an image")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_REMOTE_IMAGE_BYTES:
                        raise ValueError("remote image exceeds 30 MB")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ValueError("too many image redirects")


def _open_image(source: str | Path) -> Image.Image:
    value = str(source)
    if value.startswith("data:image/"):
        try:
            payload = value.split(",", 1)[1]
            data = base64.b64decode(payload, validate=True)
        except (IndexError, ValueError) as exc:
            raise ValueError("invalid image data URI") from exc
        if len(data) > MAX_REMOTE_IMAGE_BYTES:
            raise ValueError("image data URI exceeds 30 MB")
        image = Image.open(io.BytesIO(data))
    elif value.startswith(("https://", "http://")):
        image = Image.open(io.BytesIO(_download_image(value)))
    else:
        image = Image.open(Path(value).expanduser().resolve())
    image.load()
    return image.convert("RGB")


def compose_nine_grid(
    sources: list[str | Path],
    output: str | Path,
    *,
    cell_size: tuple[int, int] = (356, 636),
    gutter: int = 6,
) -> Path:
    """Create one 3x3 board; unused cells stay blank instead of duplicating beats."""
    if not 1 <= len(sources) <= 9:
        raise ValueError("a nine-grid page requires between one and nine real images")
    cell_width, cell_height = cell_size
    if cell_width <= 0 or cell_height <= 0 or not 0 <= gutter <= 32:
        raise ValueError("invalid grid geometry")
    canvas = Image.new(
        "RGB",
        (cell_width * 3 + gutter * 2, cell_height * 3 + gutter * 2),
        "white",
    )
    for index, source in enumerate(sources):
        image = _open_image(source)
        fitted = ImageOps.fit(image, cell_size, method=Image.Resampling.LANCZOS)
        row, column = divmod(index, 3)
        canvas.paste(
            fitted,
            (column * (cell_width + gutter), row * (cell_height + gutter)),
        )
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="PNG", optimize=True)
    return target


def split_five_view_sheet(source: str | Path, output_directory: str | Path) -> list[Path]:
    """Materialize five stable view assets from an ordered horizontal sheet."""
    image = _open_image(source)
    if image.width < 5 or image.height < 1:
        raise ValueError("five-view sheet is too small")
    target_dir = Path(output_directory).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    names = ["front", "front_three_quarter", "profile", "rear_three_quarter", "back"]
    boundaries = [round(image.width * index / 5) for index in range(6)]
    paths: list[Path] = []
    for index, name in enumerate(names):
        crop = image.crop((boundaries[index], 0, boundaries[index + 1], image.height))
        path = target_dir / f"{index + 1}_{name}.png"
        crop.save(path, format="PNG", optimize=True)
        paths.append(path)
    return paths
