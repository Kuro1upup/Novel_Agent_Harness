"""Milvus vector-store provider using the modern ``MilvusClient`` API."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .base import (
    VectorMatch,
    VectorRecord,
    VectorStore,
    VectorStoreConfigurationError,
    VectorStoreTransportError,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:@/-]{1,512}$")


class MilvusVectorStore(VectorStore):
    """Cosine/HNSW Milvus collection with mandatory project isolation."""

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 19530,
        collection_name: str = "novel_harness_vectors_v1",
        dimension: int = 384,
        token: str | None = None,
        database: str = "default",
        client: Any | None = None,
    ) -> None:
        if not host.strip():
            raise VectorStoreConfigurationError("Milvus host must not be empty")
        if not 1 <= port <= 65535:
            raise VectorStoreConfigurationError("Milvus port is invalid")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,254}", collection_name):
            raise VectorStoreConfigurationError("Invalid Milvus collection name")
        if dimension < 8:
            raise VectorStoreConfigurationError("Milvus dimension must be at least 8")
        self.collection_name = collection_name
        self.dimension = dimension
        self._client = client or self._make_client(
            host=host, port=port, token=token, database=database
        )

    @staticmethod
    def _make_client(*, host: str, port: int, token: str | None, database: str) -> Any:
        try:
            from pymilvus import MilvusClient  # type: ignore[import-untyped]
        except ImportError as exc:
            raise VectorStoreConfigurationError(
                "PyMilvus is required for MilvusVectorStore; install 'pymilvus'"
            ) from exc
        kwargs: dict[str, Any] = {
            "uri": f"http://{host}:{port}",
            "db_name": database,
        }
        if token:
            kwargs["token"] = token
        try:
            return MilvusClient(**kwargs)
        except Exception as exc:
            raise VectorStoreTransportError(f"Could not connect to Milvus: {exc}") from exc

    def ensure_collection(self) -> None:
        try:
            if self._client.has_collection(collection_name=self.collection_name):
                return
            try:
                from pymilvus import DataType
            except ImportError as exc:
                raise VectorStoreConfigurationError(
                    "PyMilvus is required to define the Milvus collection schema"
                ) from exc
            schema = self._client.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            schema.add_field(
                field_name="id",
                datatype=DataType.VARCHAR,
                is_primary=True,
                max_length=512,
            )
            schema.add_field(
                field_name="project_id",
                datatype=DataType.VARCHAR,
                max_length=512,
            )
            schema.add_field(
                field_name="source_id",
                datatype=DataType.VARCHAR,
                max_length=512,
            )
            schema.add_field(
                field_name="source_type",
                datatype=DataType.VARCHAR,
                max_length=128,
            )
            schema.add_field(field_name="chunk_ordinal", datatype=DataType.INT64)
            schema.add_field(
                field_name="content_hash",
                datatype=DataType.VARCHAR,
                max_length=128,
            )
            schema.add_field(
                field_name="metadata_json",
                datatype=DataType.VARCHAR,
                max_length=65535,
            )
            schema.add_field(
                field_name="vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=self.dimension,
            )
            index_params = self._client.prepare_index_params()
            index_params.add_index(
                field_name="vector",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
            self._client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                consistency_level="Strong",
                index_params=index_params,
            )
        except Exception as exc:
            try:
                if self._client.has_collection(collection_name=self.collection_name):
                    return
            except Exception:
                pass
            raise VectorStoreTransportError(
                f"Could not create Milvus collection {self.collection_name}: {exc}"
            ) from exc

    def upsert(self, records: Sequence[VectorRecord]) -> int:
        if not records:
            return 0
        rows: list[dict[str, Any]] = []
        for record in records:
            self._validate_identifier(record.id, "record id")
            self._validate_identifier(record.project_id, "project_id")
            if len(record.embedding) != self.dimension:
                raise VectorStoreConfigurationError(
                    f"Vector {record.id!r} has dimension {len(record.embedding)}; "
                    f"expected {self.dimension}"
                )
            if record.chunk_ordinal < 0:
                raise VectorStoreConfigurationError("chunk_ordinal cannot be negative")
            _validate_text_length(record.source_id, "source_id", 512)
            _validate_text_length(record.source_type, "source_type", 128)
            _validate_text_length(record.content_hash, "content_hash", 128)
            metadata_json = json.dumps(
                record.metadata, ensure_ascii=False, sort_keys=True, default=str
            )
            _validate_text_length(metadata_json, "metadata JSON", 65535)
            rows.append(
                {
                    "id": record.id,
                    "project_id": record.project_id,
                    "source_id": record.source_id,
                    "source_type": record.source_type,
                    "chunk_ordinal": record.chunk_ordinal,
                    "content_hash": record.content_hash,
                    "metadata_json": metadata_json,
                    "vector": [float(value) for value in record.embedding],
                }
            )
        self.ensure_collection()
        try:
            result = self._client.upsert(
                collection_name=self.collection_name,
                data=rows,
            )
        except Exception as exc:
            raise VectorStoreTransportError(f"Milvus upsert failed: {exc}") from exc
        return _mutation_count(result, fallback=len(rows))

    def search(
        self,
        *,
        project_id: str,
        vector: Sequence[float],
        limit: int = 10,
        source_types: Sequence[str] | None = None,
    ) -> list[VectorMatch]:
        self._validate_identifier(project_id, "project_id")
        if len(vector) != self.dimension:
            raise VectorStoreConfigurationError(
                f"Query dimension is {len(vector)}; expected {self.dimension}"
            )
        if not 1 <= limit <= 1000:
            raise VectorStoreConfigurationError("Search limit must be between 1 and 1000")
        expression = f"project_id == {_quote_expression(project_id)}"
        if source_types:
            if len(source_types) > 50:
                raise VectorStoreConfigurationError("Too many source type filters")
            quoted_types = ", ".join(_quote_expression(source_type) for source_type in source_types)
            expression += f" and source_type in [{quoted_types}]"
        self.ensure_collection()
        try:
            response = self._client.search(
                collection_name=self.collection_name,
                data=[[float(value) for value in vector]],
                filter=expression,
                limit=limit,
                output_fields=[
                    "project_id",
                    "source_id",
                    "source_type",
                    "chunk_ordinal",
                    "content_hash",
                    "metadata_json",
                ],
                search_params={"metric_type": "COSINE", "params": {"ef": max(64, limit)}},
            )
        except Exception as exc:
            raise VectorStoreTransportError(f"Milvus search failed: {exc}") from exc
        hits = response[0] if response else []
        return [self._normalize_hit(hit, project_id) for hit in hits]

    def delete(
        self,
        *,
        project_id: str,
        ids: Sequence[str] | None = None,
        source_id: str | None = None,
    ) -> int:
        self._validate_identifier(project_id, "project_id")
        if ids is None and source_id is None:
            expression = f"project_id == {_quote_expression(project_id)}"
        else:
            conditions = [f"project_id == {_quote_expression(project_id)}"]
            if ids is not None:
                if not ids:
                    return 0
                for record_id in ids:
                    self._validate_identifier(record_id, "record id")
                quoted = ", ".join(_quote_expression(value) for value in ids)
                conditions.append(f"id in [{quoted}]")
            if source_id is not None:
                conditions.append(f"source_id == {_quote_expression(source_id)}")
            expression = " and ".join(conditions)
        self.ensure_collection()
        try:
            result = self._client.delete(
                collection_name=self.collection_name,
                filter=expression,
            )
        except Exception as exc:
            raise VectorStoreTransportError(f"Milvus delete failed: {exc}") from exc
        return _mutation_count(result, fallback=0)

    def health(self) -> bool:
        try:
            self._client.list_collections()
            return True
        except Exception:
            return False

    @staticmethod
    def _validate_identifier(value: str, name: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise VectorStoreConfigurationError(
                f"{name} contains unsupported characters or is too long"
            )

    @staticmethod
    def _normalize_hit(hit: Any, expected_project_id: str) -> VectorMatch:
        if isinstance(hit, Mapping):
            entity = hit.get("entity")
            entity = entity if isinstance(entity, Mapping) else hit
            record_id = str(hit.get("id") or entity.get("id") or "")
            distance = hit.get("distance", hit.get("score", 0.0))
        else:
            entity = getattr(hit, "entity", {}) or {}
            record_id = str(getattr(hit, "id", ""))
            distance = getattr(hit, "distance", 0.0)
        project_id = str(entity.get("project_id") or "")
        if project_id != expected_project_id:
            raise VectorStoreTransportError(
                "Milvus returned a vector outside the requested project"
            )
        metadata_raw = entity.get("metadata_json") or "{}"
        try:
            metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else {}
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return VectorMatch(
            id=record_id,
            project_id=project_id,
            source_id=str(entity.get("source_id") or ""),
            source_type=str(entity.get("source_type") or ""),
            chunk_ordinal=int(entity.get("chunk_ordinal") or 0),
            content_hash=str(entity.get("content_hash") or ""),
            score=float(distance),
            metadata=metadata if isinstance(metadata, Mapping) else {},
        )


def _quote_expression(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _validate_text_length(value: str, name: str, maximum: int) -> None:
    if not value:
        raise VectorStoreConfigurationError(f"{name} must not be empty")
    if len(value) > maximum:
        raise VectorStoreConfigurationError(f"{name} exceeds {maximum} characters")


def _mutation_count(result: Any, *, fallback: int) -> int:
    if isinstance(result, Mapping):
        for key in ("upsert_count", "insert_count", "delete_count"):
            value = result.get(key)
            if isinstance(value, int):
                return value
    return fallback
