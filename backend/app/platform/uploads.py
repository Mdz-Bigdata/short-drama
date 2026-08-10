from __future__ import annotations

from pathlib import Path


class UploadValidationError(ValueError):
    pass


_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}


def validate_image_upload(
    filename: str,
    content_type: str,
    content: bytes,
    *,
    max_bytes: int = 10 * 1024 * 1024,
) -> str:
    if not content or len(content) > max_bytes:
        raise UploadValidationError("图片为空或超过大小限制")
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared not in _SIGNATURES:
        raise UploadValidationError("仅支持 PNG、JPEG、WebP 图片")
    suffix = Path(filename or "").suffix.lower()
    allowed_suffixes = {
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/webp": {".webp"},
    }
    if suffix not in allowed_suffixes[declared]:
        raise UploadValidationError("文件扩展名与媒体类型不一致")
    if not any(content.startswith(prefix) for prefix in _SIGNATURES[declared]):
        raise UploadValidationError("图片内容与声明类型不一致")
    if declared == "image/webp" and (len(content) < 12 or content[8:12] != b"WEBP"):
        raise UploadValidationError("WebP 文件头无效")
    return declared
