from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import UploadFile
from app.core import prompt_data


_WORDING_FILE = "project_skill_import"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/project_skill_import.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


MAX_MARKDOWN_BYTES = 128 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 32
MAX_ARCHIVE_EXPANDED_BYTES = 512 * 1024


@dataclass(frozen=True)
class ImportedSkillMarkdown:
    name: str
    slug: str
    description: str
    markdown_content: str


async def read_upload_limited(file: UploadFile, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(min(64 * 1024, maximum + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise ValueError(_text_of("read_upload_limited.text"))
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_markdown(content: bytes) -> str:
    if not content or len(content) > MAX_MARKDOWN_BYTES:
        raise ValueError(_text_of("_decode_markdown.text"))
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(_text_of("_decode_markdown.text.2")) from exc
    if "\x00" in text:
        raise ValueError(_text_of("_decode_markdown.text.3"))
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", ""
    end = text.find("\n---", 4, 8192)
    if end < 0:
        return "", ""
    block = text[4:end]
    name = re.search(r"(?mi)^name:\s*['\"]?([^'\"\n]{1,160})", block)
    description = re.search(r"(?mi)^description:\s*['\"]?([^'\"\n]{1,4000})", block)
    return (
        name.group(1).strip() if name else "",
        description.group(1).strip() if description else "",
    )


def _slug(value: str, content: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if len(normalized) < 3:
        normalized = f"skill-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:12]}"
    return normalized[:80].rstrip("-")


def parse_markdown_upload(filename: str, content: bytes) -> ImportedSkillMarkdown:
    safe_name = Path(filename or "").name
    if not safe_name.lower().endswith(".md"):
        raise ValueError(_text_of("parse_markdown_upload.text"))
    text = _decode_markdown(content)
    front_name, description = _front_matter(text)
    stem = Path(safe_name).stem
    name = front_name or stem.replace("-", " ").replace("_", " ").strip() or "Custom Skill"
    return ImportedSkillMarkdown(
        name=name[:160],
        slug=_slug(stem, text),
        description=description,
        markdown_content=text,
    )


def parse_skill_archive(filename: str, content: bytes) -> ImportedSkillMarkdown:
    if not Path(filename or "").name.lower().endswith(".zip"):
        raise ValueError(_text_of("parse_skill_archive.text"))
    if not content.startswith(b"PK") or len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError(_text_of("parse_skill_archive.text.2"))
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError(_text_of("parse_skill_archive.text.3")) from exc
    with archive:
        members = archive.infolist()
        if not members or len(members) > MAX_ARCHIVE_ENTRIES:
            raise ValueError(_text_of("parse_skill_archive.text.4"))
        total = 0
        skill_files: list[zipfile.ZipInfo] = []
        for member in members:
            name = member.filename
            if "\\" in name:
                raise ValueError(_text_of("parse_skill_archive.text.5"))
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(_text_of("parse_skill_archive.text.6"))
            file_type = (member.external_attr >> 16) & 0o170000
            if file_type == 0o120000:
                raise ValueError(_text_of("parse_skill_archive.text.7"))
            if member.flag_bits & 0x1:
                raise ValueError(_text_of("parse_skill_archive.text.8"))
            if member.is_dir():
                continue
            if path.suffix.lower() != ".md":
                raise ValueError(_text_of("parse_skill_archive.text.9"))
            total += member.file_size
            if total > MAX_ARCHIVE_EXPANDED_BYTES:
                raise ValueError(_text_of("parse_skill_archive.text.10"))
            if path.name.lower() == "skill.md":
                skill_files.append(member)
        if len(skill_files) != 1:
            raise ValueError(_text_of("parse_skill_archive.text.11"))
        target = skill_files[0]
        text = _decode_markdown(archive.read(target))
    front_name, description = _front_matter(text)
    package_stem = Path(filename).stem
    name = front_name or target.filename.split("/")[-2] if "/" in target.filename else front_name
    name = name or package_stem.replace("-", " ").replace("_", " ").strip() or "Imported Skill"
    return ImportedSkillMarkdown(
        name=name[:160],
        slug=_slug(package_stem, text),
        description=description,
        markdown_content=text,
    )
