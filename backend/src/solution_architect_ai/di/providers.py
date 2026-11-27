import json
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from hashlib import sha256

import httpx
from dishka import Provider, Scope, from_context, provide
from dishka.dependency_source import CompositeDependencySource
from langchain_openai import ChatOpenAI
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from solution_architect_ai.application.capacity import GenerationCapacity
from solution_architect_ai.application.generation import RunWorker
from solution_architect_ai.application.protocols.chat_protocols import (
    LLM,
    ChatStore,
    ResourceProbe,
    TokenCounter,
)
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.chat_service import ChatService
from solution_architect_ai.config.models import DatabaseSettings, LLMSettings
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.health import LocalResourceProbe
from solution_architect_ai.infrastructure.llm import LangChainLLM
from solution_architect_ai.persistence.store import SqlAlchemyStore
from solution_architect_ai.persistence.store_context import SqlAlchemyStoreContext


def database_url(settings: Settings) -> URL:
    db: DatabaseSettings = settings.database
    return URL.create(
        "postgresql+psycopg",
        username=db.user,
        password=db.credentials.password.get_secret_value(),
        host=db.host,
        port=db.port,
        database=db.database,
    )


class AppProvider(Provider):
    settings: CompositeDependencySource = from_context(Settings, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def engine(self, settings: Settings) -> AsyncGenerator[AsyncEngine]:
        engine: AsyncEngine = create_async_engine(
            database_url(settings),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
            pool_size=5,
            max_overflow=2,
            pool_timeout=3,
        )
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide(scope=Scope.APP)
    def database_sessions(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker[AsyncSession](engine, expire_on_commit=False)

    @provide(scope=Scope.APP)
    def chat_store_context(
        self, database_sessions: async_sessionmaker[AsyncSession]
    ) -> StoreContext[ChatStore]:
        return SqlAlchemyStoreContext(database_sessions, SqlAlchemyStore)

    @provide(scope=Scope.APP)
    async def llm(self, settings: Settings) -> AsyncGenerator[LLM]:
        profile: LLMSettings = settings.llm
        stack: AsyncExitStack
        async with AsyncExitStack() as stack:
            sync_client: httpx.Client = stack.enter_context(httpx.Client(trust_env=False))
            client: httpx.AsyncClient = await stack.enter_async_context(
                httpx.AsyncClient(trust_env=False)
            )
            model: ChatOpenAI = ChatOpenAI(
                model=profile.model,
                base_url=profile.base_url,
                api_key=profile.api_key or "local-no-external-key",
                temperature=profile.temperature,
                max_completion_tokens=profile.output_limit,
                max_retries=0,
                timeout=profile.retry.request_timeout_seconds,
                http_async_client=client,
                http_client=sync_client,
                http_socket_options=(),
                streaming=True,
                stream_usage=False,
            )
            yield LangChainLLM(model)

    @provide(scope=Scope.APP)
    def chat_token_counter(self, settings: Settings) -> TokenCounter:
        return LangChainTokenCounter(settings.llm.approximate_chars_per_token)

    @provide(scope=Scope.APP)
    def chat_worker(
        self,
        chat_store_context: StoreContext[ChatStore],
        llm: LLM,
        settings: Settings,
        chat_token_counter: TokenCounter,
        capacity: GenerationCapacity,
    ) -> RunWorker:
        profile: LLMSettings = settings.llm
        generation_policy: GenerationPolicy = GenerationPolicy(
            concurrency=profile.concurrency,
            deadline=profile.retry.deadline_seconds,
            retries=profile.retry.network_retries,
            requests=profile.retry.max_total_requests,
            backoff=profile.retry.backoff_initial,
            input_budget=profile.context_window - profile.output_limit,
            backoff_max=profile.retry.backoff_max,
            jitter=profile.retry.jitter,
        )
        if chat_token_counter.count([]) >= generation_policy.input_budget:
            raise ValueError("output limit leaves no input budget for the system prompt")
        return RunWorker(chat_store_context, llm, generation_policy, chat_token_counter, capacity)

    @provide(scope=Scope.APP)
    def capacity(self, settings: Settings) -> GenerationCapacity:
        return GenerationCapacity(settings.llm.concurrency)

    @provide(scope=Scope.APP)
    def chat_service(
        self,
        chat_store_context: StoreContext[ChatStore],
        settings: Settings,
        resource_probe: ResourceProbe,
    ) -> ChatService:
        profile: dict[str, object] = settings.llm.model_dump(mode="json", exclude={"api_key"})
        config_digest: str = sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        return ChatService(chat_store_context, settings.llm.model, config_digest, resource_probe)

    @provide(scope=Scope.APP)
    def resource_probe(self, settings: Settings) -> ResourceProbe:
        return LocalResourceProbe((settings.git.root, settings.storage.root))
