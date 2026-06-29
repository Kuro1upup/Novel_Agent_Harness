"""Lazy application dependency container."""

from __future__ import annotations

from functools import cached_property

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from novel_harness.agents import (
    CharacterAgent,
    ContinuityChecker,
    FactChecker,
    ForeshadowingAgent,
    MemoryExtractor,
    PlotPlanner,
    ResearchAgent,
    RevisionAgent,
    SceneWriter,
    StyleAnalyzer,
    WorldbuildingAgent,
)
from novel_harness.config import Settings, get_settings
from novel_harness.integrations import AuthServiceClient, BillingServiceClient
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
    AgentRunService,
    CreativeService,
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
        auth_client: AuthServiceClient | None = None,
        billing_client: BillingServiceClient | None = None,
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
        self._auth_client = auth_client
        self._billing_client = billing_client

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

    @cached_property
    def auth_client(self) -> AuthServiceClient:
        return self._auth_client or AuthServiceClient(
            self.settings.auth_service_url,
            timeout_seconds=self.settings.auth_request_timeout_seconds,
            internal_api_key=self.settings.billing_internal_api_key,
        )

    @cached_property
    def billing_client(self) -> BillingServiceClient:
        return self._billing_client or BillingServiceClient(
            self.settings.billing_service_url,
            internal_api_key=self.settings.billing_internal_api_key,
            timeout_seconds=self.settings.billing_request_timeout_seconds,
            required=self.settings.billing_required,
        )

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
            agent_runs=self.agent_run_service(session, provider=llm),
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
            agent_runs=self.agent_run_service(session, provider=llm),
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
            agent_runs=self.agent_run_service(session, provider=llm),
        )

    def agent_run_service(
        self,
        session: Session,
        *,
        provider: LLMProvider | None = None,
    ) -> AgentRunService:
        selected = provider
        if selected is None and self.settings.llm_provider != "mock":
            selected = self.llm_provider
        return AgentRunService(
            session,
            provider=selected,
            input_cost_per_million=self.settings.llm_input_cost_per_million,
            output_cost_per_million=self.settings.llm_output_cost_per_million,
            billing_client=self.billing_client if self.settings.billing_enabled else None,
            persistence_factory=(
                self.session_factory
                if session.bind is not None and session.bind.dialect.name != "sqlite"
                else None
            ),
        )

    def creative_service(self, session: Session) -> CreativeService:
        llm = None if self.settings.llm_provider == "mock" else self.llm_provider
        return CreativeService(
            session,
            character_agent=CharacterAgent(llm),
            worldbuilding_agent=WorldbuildingAgent(llm),
            foreshadowing_agent=ForeshadowingAgent(llm),
            agent_runs=self.agent_run_service(session, provider=llm),
        )

    def close(self) -> None:
        """Best-effort shutdown for injected or long-lived provider clients."""

        values = [
            self.__dict__.get(name)
            for name in (
                "llm_provider",
                "search_provider",
                "object_store",
                "vector_store",
                "embedding_provider",
                "content_fetcher",
                "cache_provider",
            )
        ]
        values.extend(
            (
                self._llm_provider,
                self._search_provider,
                self._object_store,
                self._vector_store,
                self._embedding_provider,
                self._content_fetcher,
                self._cache_provider,
            )
        )
        for value in {id(item): item for item in values if item is not None}.values():
            close = getattr(value, "close", None)
            if callable(close):
                close()
        engine = self._engine or self.__dict__.get("engine")
        if engine is not None:
            engine.dispose()

    async def aclose(self) -> None:
        """Close both synchronous providers and async service clients."""

        self.close()
        clients = {
            id(client): client
            for client in (
                self._auth_client,
                self.__dict__.get("auth_client"),
                self._billing_client,
                self.__dict__.get("billing_client"),
            )
            if client is not None
        }
        for client in clients.values():
            await client.aclose()
