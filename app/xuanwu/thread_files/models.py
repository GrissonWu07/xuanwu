# -*- coding: utf-8 -*-
"""Metadata models for thread attachments and artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import uuid


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass
class ThreadUploadRecord:
    """Metadata for a saved upload."""

    upload_id: str
    batch_id: str
    filename: str
    relative_path: str
    size_bytes: int
    content_type: Optional[str] = None
    sha256: Optional[str] = None
    injection_mode: str = "reference"
    content: str = ""
    summary: str = ""
    created_at: str = field(default_factory=_utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        filename: str,
        relative_path: str,
        size_bytes: int,
        content_type: Optional[str] = None,
        sha256: Optional[str] = None,
        injection_mode: str = "reference",
        content: str = "",
        summary: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ThreadUploadRecord":
        return cls(
            upload_id=_new_id("upload"),
            batch_id=batch_id,
            filename=filename,
            relative_path=relative_path,
            size_bytes=size_bytes,
            content_type=content_type,
            sha256=sha256,
            injection_mode=injection_mode,
            content=content,
            summary=summary,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "upload_id": self.upload_id,
            "batch_id": self.batch_id,
            "filename": self.filename,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "sha256": self.sha256,
            "injection_mode": self.injection_mode,
            "content": self.content,
            "summary": self.summary,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThreadUploadRecord":
        return cls(
            upload_id=str(data.get("upload_id") or _new_id("upload")),
            batch_id=str(data.get("batch_id") or ""),
            filename=str(data.get("filename") or ""),
            relative_path=str(data.get("relative_path") or ""),
            size_bytes=int(data.get("size_bytes") or 0),
            content_type=data.get("content_type"),
            sha256=data.get("sha256"),
            injection_mode=str(data.get("injection_mode") or "reference"),
            content=str(data.get("content") or ""),
            summary=str(data.get("summary") or ""),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class ThreadArtifactRecord:
    """Metadata for a generated artifact."""

    artifact_id: str
    batch_id: str
    name: str
    relative_path: str
    status: str = "ready"
    size_bytes: int = 0
    created_at: str = field(default_factory=_utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        name: str,
        relative_path: str,
        status: str = "ready",
        size_bytes: int = 0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ThreadArtifactRecord":
        return cls(
            artifact_id=_new_id("artifact"),
            batch_id=batch_id,
            name=name,
            relative_path=relative_path,
            status=status,
            size_bytes=size_bytes,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "batch_id": self.batch_id,
            "name": self.name,
            "relative_path": self.relative_path,
            "status": self.status,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThreadArtifactRecord":
        return cls(
            artifact_id=str(data.get("artifact_id") or _new_id("artifact")),
            batch_id=str(data.get("batch_id") or ""),
            name=str(data.get("name") or ""),
            relative_path=str(data.get("relative_path") or ""),
            status=str(data.get("status") or "ready"),
            size_bytes=int(data.get("size_bytes") or 0),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class ThreadFileIndex:
    """Batch-local attachment index persisted to index.json."""

    uploads: list[ThreadUploadRecord] = field(default_factory=list)
    artifacts: list[ThreadArtifactRecord] = field(default_factory=list)
    schema_version: int = 1
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "uploads": [item.to_dict() for item in self.uploads],
            "artifacts": [item.to_dict() for item in self.artifacts],
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "ThreadFileIndex":
        payload = dict(data or {})
        return cls(
            uploads=[
                ThreadUploadRecord.from_dict(item)
                for item in payload.get("uploads", [])
                if isinstance(item, dict)
            ],
            artifacts=[
                ThreadArtifactRecord.from_dict(item)
                for item in payload.get("artifacts", [])
                if isinstance(item, dict)
            ],
            schema_version=int(payload.get("schema_version") or 1),
            updated_at=str(payload.get("updated_at") or _utc_now_iso()),
        )

    def upsert_upload(self, record: ThreadUploadRecord) -> None:
        self.uploads = [item for item in self.uploads if item.upload_id != record.upload_id]
        self.uploads.append(record)
        self.updated_at = _utc_now_iso()

    def upsert_artifact(self, record: ThreadArtifactRecord) -> None:
        self.artifacts = [item for item in self.artifacts if item.relative_path != record.relative_path]
        self.artifacts.append(record)
        self.updated_at = _utc_now_iso()


@dataclass(frozen=True)
class ThreadRuntimeBatch:
    """Resolved paths for the active runtime batch."""

    batch_id: str
    root: Any
    uploads_dir: Any
    workspace_dir: Any
    outputs_dir: Any
    index_path: Any
