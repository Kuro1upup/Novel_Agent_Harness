from novel_harness.providers.embedding import DeterministicEmbeddingProvider
from novel_harness.services import DocumentService, ProjectService


def test_document_ingestion_uploads_and_indexes(
    session, fake_object_store, fake_vector_store
) -> None:
    project = ProjectService(session).create(name="测试", genre="都市")
    service = DocumentService(
        session,
        object_store=fake_object_store,
        vector_store=fake_vector_store,
        embedding_provider=DeterministicEmbeddingProvider(),
    )
    document, text = service.ingest_bytes(
        project.id, "sample.md", "# 第一章\n\n这是用于分析的原创样文。"
    )
    assert document.status == "ready"
    assert text.startswith("# 第一章")
    assert fake_object_store.exists(document.object_key)
    assert fake_vector_store.records
