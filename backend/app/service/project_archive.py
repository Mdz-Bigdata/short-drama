"""Deterministic, checksum-verified studio project archives."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile

from app.repository.studio_repo import StudioRepository
from app.schema.studio import ProjectRecord


class ProjectArchiveError(ValueError):
    pass


class ProjectArchiveService:
    MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
    MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
    _FILES = {"manifest.json", "project.json"}

    def __init__(self, repository: StudioRepository):
        self.repository = repository

    @staticmethod
    def _canonical_json(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _zip_info(name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        info.create_system = 3
        return info

    def export_project(self, project_id: str, owner_id: str) -> bytes:
        payload = self._canonical_json(self.repository.project_snapshot(project_id, owner_id))
        if len(payload) > self.MAX_UNCOMPRESSED_BYTES:
            raise ProjectArchiveError("project payload exceeds the export size limit")
        manifest = self._canonical_json(
            {
                "format": "short-drama-project-archive",
                "version": 1,
                "files": [
                    {
                        "path": "project.json",
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "size": len(payload),
                    }
                ],
            }
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(self._zip_info("manifest.json"), manifest)
            archive.writestr(self._zip_info("project.json"), payload)
        result = output.getvalue()
        if len(result) > self.MAX_ARCHIVE_BYTES:
            raise ProjectArchiveError("project archive exceeds the export size limit")
        return result

    def import_project(
        self, archive_bytes: bytes, *, owner_id: str, project_name: str
    ) -> ProjectRecord:
        if not archive_bytes or len(archive_bytes) > self.MAX_ARCHIVE_BYTES:
            raise ProjectArchiveError("project archive is empty or too large")
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos]
                if len(names) != len(set(names)) or set(names) != self._FILES:
                    raise ProjectArchiveError("project archive contains missing or undeclared files")
                total = 0
                for info in infos:
                    if (
                        info.is_dir()
                        or info.filename.startswith(("/", "\\"))
                        or ".." in info.filename.replace("\\", "/").split("/")
                        or stat.S_ISLNK(info.external_attr >> 16)
                    ):
                        raise ProjectArchiveError("project archive contains an unsafe entry")
                    total += info.file_size
                    if info.compress_size and info.file_size / info.compress_size > 100:
                        raise ProjectArchiveError("project archive compression ratio is unsafe")
                if total > self.MAX_UNCOMPRESSED_BYTES:
                    raise ProjectArchiveError("project archive expands beyond the size limit")
                manifest_raw = archive.read("manifest.json")
                payload = archive.read("project.json")
        except (zipfile.BadZipFile, RuntimeError, KeyError, OSError) as exc:
            raise ProjectArchiveError("project archive is not a valid ZIP package") from exc
        try:
            manifest = json.loads(manifest_raw)
            snapshot = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectArchiveError("project archive JSON is invalid") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != "short-drama-project-archive"
            or manifest.get("version") != 1
            or not isinstance(manifest.get("files"), list)
            or len(manifest["files"]) != 1
        ):
            raise ProjectArchiveError("project archive manifest is unsupported")
        entry = manifest["files"][0]
        if (
            not isinstance(entry, dict)
            or entry.get("path") != "project.json"
            or entry.get("size") != len(payload)
            or entry.get("sha256") != hashlib.sha256(payload).hexdigest()
        ):
            raise ProjectArchiveError("project archive checksum validation failed")
        if not isinstance(snapshot, dict):
            raise ProjectArchiveError("project archive payload must be an object")
        return self.repository.import_project_snapshot(
            snapshot,
            owner_id=owner_id,
            project_name=project_name,
        )
