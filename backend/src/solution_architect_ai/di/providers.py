import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from hashlib import sha256

import httpx
from dishka import Provider, Scope, from_context, provide
from langchain_openai import ChatOpenAI
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from solution_architect_ai.application.chat import ChatService
from solution_architect_ai.application.generation import GenerationPolicy, RunWorker
from solution_architect_ai.application.ports import LLM, ResourceProbe, StoreFactory
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.infrastructure.health import LocalResourceProbe
from solution_architect_ai.infrastructure.llm import LangChainLLM
from solution_architect_ai.persistence.factory import PostgresFactory


def database_url(settings: Settings) -> URL:
    db = settings.database
    return URL.create(
        "postgresql+psycopg",
        username=db.user,
        password=db.credentials.password.get_secret_value(),
        host=db.host,
        port=db.port,
        database=db.database,
    )


class AppProvider(Provider):
    settings = from_context(Settings, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def engine(self, settings: Settings) -> AsyncIterator[AsyncEngine]:
        engine = create_async_engine(
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
    def stores(self, engine: AsyncEngine) -> StoreFactory:
        sessions = async_sessionmaker[AsyncSession](engine, expire_on_commit=False)
        return PostgresFactory(sessions)

    @provide(scope=Scope.APP)
    async def llm(self, settings: Settings) -> AsyncIterator[LLM]:
        profile = settings.llm
        async with AsyncExitStack() as stack:
            sync_client = stack.enter_context(httpx.Client(trust_env=False))
            client = await stack.enter_async_context(httpx.AsyncClient(trust_env=False))
            model = ChatOpenAI(
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
    def worker(self, stores: StoreFactory, llm: LLM, settings: Settings) -> RunWorker:
        profile = settings.llm
        policy = GenerationPolicy(
            concurrency=profile.concurrency,
            deadline=profile.retry.deadline_seconds,
            retries=profile.retry.network_retries,
            requests=profile.retry.max_total_requests,
            backoff=profile.retry.backoff_initial,
            input_budget=profile.context_window - profile.output_limit - 256,
            backoff_max=profile.retry.backoff_max,
            jitter=profile.retry.jitter,
        )
        return RunWorker(stores, llm, policy)

    @provide(scope=Scope.REQUEST)
    def service(
        self, stores: StoreFactory, settings: Settings, probe: ResourceProbe
    ) -> ChatService:
        profile = settings.llm.model_dump(mode="json", exclude={"api_key"})
        digest = sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        return ChatService(stores, settings.llm.model, digest, probe)

    @provide(scope=Scope.APP)
    def resource_probe(self, settings: Settings) -> ResourceProbe:
        return LocalResourceProbe((settings.git.root, settings.storage.root))
