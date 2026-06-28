"""Portable MySQL and MinIO backup, verification, and restore operations."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from minio import Minio

from novel_harness.config import Settings

logger = logging.getLogger("novel_harness.ops")


class OpsService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_backup(self, destination: Path) -> dict[str, Any]:
        destination = destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._require_command("mysqldump")
        with tempfile.TemporaryDirectory(prefix="novel-backup-") as temporary:
            root = Path(temporary)
            dump_path = root / "database.sql"
            self._dump_database(dump_path)
            object_entries = self._download_objects(root / "objects")
            files = [
                {"path": "database.sql", "sha256": self._sha256(dump_path)},
                *object_entries,
            ]
            manifest = {
                "format_version": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "database": self.settings.database_name,
                "bucket": self.settings.minio_bucket,
                "files": files,
                "milvus": "rebuild from relational metadata and object-store content",
            }
            (root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with tarfile.open(destination, "w:gz") as archive:
                archive.add(root / "manifest.json", arcname="manifest.json")
                archive.add(dump_path, arcname="database.sql")
                if (root / "objects").exists():
                    archive.add(root / "objects", arcname="objects")
        result = {
            "archive": str(destination),
            "objects": len(object_entries),
            "sha256": self._sha256(destination),
        }
        self._log("backup_created", **result)
        return result

    def verify_backup(self, archive_path: Path) -> dict[str, Any]:
        with self._extract_verified(archive_path) as extracted:
            manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
            for item in manifest.get("files", []):
                path = extracted / str(item["path"])
                if not path.is_file() or self._sha256(path) != item["sha256"]:
                    raise ValueError(f"backup checksum failed for {item['path']!r}")
            result = {
                "archive": str(archive_path.expanduser().resolve()),
                "valid": True,
                "files": len(manifest.get("files", [])),
                "created_at": manifest.get("created_at"),
            }
        self._log("backup_verified", **result)
        return result

    def restore_backup(
        self,
        archive_path: Path,
        *,
        target_database: str | None = None,
        target_bucket: str | None = None,
    ) -> dict[str, Any]:
        database = target_database or self.settings.database_name
        bucket = target_bucket or self.settings.minio_bucket
        self._validate_name(database, "database")
        self._validate_name(bucket, "bucket")
        self._require_command("mysql")
        with self._extract_verified(archive_path) as extracted:
            self.verify_backup(archive_path)
            self._ensure_database(database)
            self._restore_database(extracted / "database.sql", database)
            count = self._upload_objects(extracted, bucket)
        result = {
            "archive": str(archive_path.expanduser().resolve()),
            "database": database,
            "bucket": bucket,
            "objects": count,
            "vector_rebuild_required": True,
        }
        self._log("backup_restored", **result)
        return result

    def drill(
        self,
        archive_path: Path,
        *,
        target_database: str,
        target_bucket: str,
    ) -> dict[str, Any]:
        if target_database == self.settings.database_name:
            raise ValueError("drill database must differ from the production database")
        if target_bucket == self.settings.minio_bucket:
            raise ValueError("drill bucket must differ from the production bucket")
        result = self.restore_backup(
            archive_path,
            target_database=target_database,
            target_bucket=target_bucket,
        )
        result["drill"] = True
        self._log("restore_drill_completed", **result)
        return result

    def _dump_database(self, destination: Path) -> None:
        with destination.open("wb") as output:
            self._run(
                [
                    "mysqldump",
                    "--host",
                    self.settings.database_host,
                    "--port",
                    str(self.settings.database_port),
                    "--user",
                    self.settings.database_root_user,
                    "--single-transaction",
                    "--routines",
                    "--triggers",
                    "--set-gtid-purged=OFF",
                    self.settings.database_name,
                ],
                stdout=output,
            )

    def _ensure_database(self, database: str) -> None:
        self._run(
            [
                "mysql",
                "--host",
                self.settings.database_host,
                "--port",
                str(self.settings.database_port),
                "--user",
                self.settings.database_root_user,
                "--execute",
                (
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                ),
            ]
        )

    def _restore_database(self, dump: Path, database: str) -> None:
        with dump.open("rb") as source:
            self._run(
                [
                    "mysql",
                    "--host",
                    self.settings.database_host,
                    "--port",
                    str(self.settings.database_port),
                    "--user",
                    self.settings.database_root_user,
                    database,
                ],
                stdin=source,
            )

    def _download_objects(self, destination: Path) -> list[dict[str, str]]:
        client = self._minio()
        if not client.bucket_exists(self.settings.minio_bucket):
            return []
        entries: list[dict[str, str]] = []
        for item in client.list_objects(self.settings.minio_bucket, recursive=True):
            key = item.object_name
            if not key:
                continue
            relative = f"objects/{quote(key, safe='')}"
            path = destination / quote(key, safe="")
            path.parent.mkdir(parents=True, exist_ok=True)
            client.fget_object(self.settings.minio_bucket, key, str(path))
            entries.append({"path": relative, "sha256": self._sha256(path)})
        return entries

    def _upload_objects(self, extracted: Path, bucket: str) -> int:
        client = self._minio()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        count = 0
        objects = extracted / "objects"
        if not objects.exists():
            return count
        for path in objects.iterdir():
            if not path.is_file():
                continue
            client.fput_object(bucket, unquote(path.name), str(path))
            count += 1
        return count

    def _minio(self) -> Minio:
        return Minio(
            self.settings.minio_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_secure,
        )

    def _run(
        self,
        command: list[str],
        *,
        stdin: Any | None = None,
        stdout: Any | None = None,
    ) -> None:
        environment = dict(os.environ)
        environment["MYSQL_PWD"] = self.settings.database_root_password
        subprocess.run(
            command,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=True,
            env=environment,
        )

    @contextmanager
    def _extract_verified(self, archive_path: Path) -> Iterator[Path]:
        archive_path = archive_path.expanduser().resolve()
        with tempfile.TemporaryDirectory(prefix="novel-restore-") as temporary:
            root = Path(temporary)
            with tarfile.open(archive_path, "r:gz") as archive:
                for member in archive.getmembers():
                    target = (root / member.name).resolve()
                    if root not in target.parents and target != root:
                        raise ValueError("backup contains an unsafe path")
                    if member.issym() or member.islnk():
                        raise ValueError("backup must not contain links")
                archive.extractall(root, filter="data")
            if not (root / "manifest.json").is_file() or not (root / "database.sql").is_file():
                raise ValueError("backup is missing manifest.json or database.sql")
            yield root

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _require_command(command: str) -> None:
        if shutil.which(command) is None:
            raise RuntimeError(f"required command {command!r} was not found")

    @staticmethod
    def _validate_name(value: str, label: str) -> None:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        if not value or any(character not in allowed for character in value):
            raise ValueError(f"{label} contains unsupported characters")

    @staticmethod
    def _log(event: str, **data: Any) -> None:
        logger.info(
            json.dumps(
                {"event": event, **data},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
