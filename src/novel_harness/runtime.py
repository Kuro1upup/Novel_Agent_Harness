"""Lazy application dependency container."""

from __future__ import annotations

from functools import cached_property

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from novel_harness.agents import (
    ContinuityChecker,
    FactChecker,
    MemoryExtractor,
    PlotPlanner,
    ResearchAgent,
    RevisionAgent,
    SceneWriter,
    StyleAnalyzer,
)
from novel_harness.config import Settings, get_settings
from novel_harness.providers import (
    CacheProvider,
    ContentFetcher,
    EmbeddingProvider,
    LLMProvider,
    ObjectStore,
    SearchProvider,
    VectorStore,
    build_cache_provider,
    build_content_fetcher,
    build_embedding_provider,
    build_llm_provider,
    build_object_store,
    build_search_provider,
    build_vector_store,
)
from novel_harness.services import (
    DocumentService,
    GenerationService,
    MemoryService,
    ResearchService,
)
from novel_harness.storage import create_mysql_engine, create_session_factory


class Runtime:
    """Construct external clients only when a use case actually needs them."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        engine: Engine | None = None,
        session_factory: sessionmaker[Session] | None = None,
        llm_provider: LLMProvider | None = None,
        search_provider: SearchProvider | None = None,
        object_store: ObjectStore | None = None,
        vector_store: VectorStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        content_fetcher: ContentFetcher | None = None,
        cache_provider: CacheProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._engine = engine
        self._session_factory = session_factory
        self._llm_provider = llm_provider
        self._search_provider = search_provider
        self._object_store = object_store
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._content_fetcher = content_fetcher
        self._cache_provider = cache_provider

    @cached_property
    def engine(self) -> Engine:
        return self._engine or create_mysql_engine(self.settings.database_url)

    @cached_property
    def session_factory(self) -> sessionmaker[Session]:
        return self._session_factory or create_session_factory(self.engine)

    @cached_property
    def llm_provider(self) -> LLMProvider:
        return self._llm_provider or build_llm_provider(self.settings)

    @cached_property
    def search_provider(self) -> SearchProvider:
        return self._search_provider or build_search_provider(self.settings)

    @cached_property
    def object_store(self) -> ObjectStore:
        return self._object_store or build_object_store(self.settings)

    @cached_property
    def vector_store(self) -> VectorStore:
        return self._vector_store or build_vector_store(self.settings)

    @cached_property
    def embedding_provider(self) -> EmbeddingProvider:
        return self._embedding_provider or build_embedding_provider(self.settings)

    @cached_property
    def content_fetcher(self) -> ContentFetcher:
        return self._content_fetcher or build_content_fetcher(self.settings)

    @cached_property
    def cache_provider(self) -> CacheProvider:
        return self._cache_provider or build_cache_provider(self.settings)

    def document_service(self, session: Session) -> DocumentService:
        return DocumentService(
            session,
            object_store=self.object_store,
            vector_store=self.vector_store,
            embedding_provider=self.embedding_provider,
            max_upload_bytes=self.settings.max_upload_bytes,
        )

    def research_service(self, session: Session) -> ResearchService:
        llm = None if self.settings.llm_provider == "mock" else self.llm_provider
        return ResearchService(
            session,
            ResearchAgent(self.search_provider, llm),
            content_fetcher=(
                self.content_fetcher if self.settings.research_fetch_enabled else None
            ),
            object_store=self.object_store,
            vector_store=self.vector_store,
            embedding_provider=self.embedding_provider,
            max_fetches=self.settings.research_fetch_max_sources,
        )

    def memory_service(self, session: Session) -> MemoryService:
        llm = None if self.settings.llm_provider == "mock" else self.llm_provider
        return MemoryService(
            session,
            object_store=self.object_store,
            vector_store=self.vector_store,
            embedding_provider=self.embedding_provider,
            extractor=MemoryExtractor(llm),
            cache_provider=self.cache_provider,
            cache_ttl_seconds=self.settings.redis_cache_ttl_seconds,
        )

    def generation_service(self, session: Session) -> GenerationService:
        llm = None if self.settings.llm_provider == "mock" else self.llm_provider
        return GenerationService(
            session,
            object_store=self.object_store,
            vector_store=self.vector_store,
            embedding_provider=self.embedding_provider,
            style_analyzer=StyleAnalyzer(llm),
            plot_planner=PlotPlanner(llm),
            scene_writer=SceneWriter(llm),
            continuity_checker=ContinuityChecker(llm),
            fact_checker=FactChecker(llm),
            revision_agent=RevisionAgent(llm),
            originality_max_contiguous_chars=(self.settings.originality_max_contiguous_chars),
            originality_max_ngram_overlap=(self.settings.originality_max_ngram_overlap),
            context_max_characters=self.settings.context_max_characters,
            context_retrieval_limit=self.settings.context_retrieval_limit,
        )
