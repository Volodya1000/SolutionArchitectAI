import json
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from hashlib import sha256

import httpx
from dishka import Scope, provide
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.agents.requirements_extraction_agent import (
    RequirementsExtractionAgent,
)
from solution_architect_ai.application.capacity import GenerationCapacity
from solution_architect_ai.application.context.context_models import ContextPolicy
from solution_architect_ai.application.context.extraction_context_builder import (
    ExtractionContextBuilder,
)
from solution_architect_ai.application.models.extraction_models import StoredModelProfile
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.models.structured_models import ModelProfile, StructuredMode
from solution_architect_ai.application.protocols.clarification_protocols import (
    ClarificationStoreFactory,
)
from solution_architect_ai.application.protocols.extraction_protocols import (
    ExtractionGraph,
    ExtractionStoreFactory,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.services.requirements_extraction_service import (
    RequirementsExtractionService,
)
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.workflows.clarification_workflow import ClarificationWorkflow
from solution_architect_ai.application.workflows.extraction_steps import (
    ExtractionSteps,
)
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.config.models import LLMSettings
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.clarifications import ClarificationProvider
from solution_architect_ai.di.providers import database_url
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.extraction_graph import LangGraphExtraction
from solution_architect_ai.infrastructure.structured import LangChainStructuredModel
from solution_architect_ai.persistence.extractions.extraction_factory import (
    SqlAlchemyExtractionStoreFactory,
)
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID


def profile_digest(settings: Settings) -> str:
    profile: dict[str, object] = settings.llm.model_dump(mode="json", exclude={"api_key"})
    return sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


class ExtractionProvider(ClarificationProvider):
    @provide(scope=Scope.APP)
    def clarification_agent(self, generator: StructuredOutputGenerator) -> ClarificationAgent:
        return ClarificationAgent(generator)

    @provide(scope=Scope.APP)
    def clarification_workflow(
        self, stores: ClarificationStoreFactory, steps: ExtractionSteps, agent: ClarificationAgent
    ) -> ClarificationWorkflow:
        return ClarificationWorkflow(stores, steps, agent)

    @provide(scope=Scope.APP)
    def extraction_stores(self, engine: AsyncEngine) -> ExtractionStoreFactory:
        sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
            engine, expire_on_commit=False
        )
        return SqlAlchemyExtractionStoreFactory(sessions)

    @provide(scope=Scope.APP)
    async def generator(self, settings: Settings) -> AsyncGenerator[StructuredOutputGenerator]:
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
                streaming=False,
                stream_usage=False,
            )
            policy: GenerationPolicy = GenerationPolicy(
                profile.concurrency,
                profile.retry.deadline_seconds,
                profile.retry.network_retries,
                profile.retry.max_total_requests,
                profile.retry.backoff_initial,
                profile.context_window - profile.output_limit,
                profile.retry.backoff_max,
                profile.retry.jitter,
            )
            yield StructuredOutputGenerator(
                LangChainStructuredModel(model),
                policy,
                LangChainTokenCounter(profile.approximate_chars_per_token, chat_prompt=False),
            )

    @provide(scope=Scope.APP)
    def context_builder(self, settings: Settings) -> ExtractionContextBuilder:
        profile: LLMSettings = settings.llm
        return ExtractionContextBuilder(
            LangChainTokenCounter(profile.approximate_chars_per_token, chat_prompt=False),
            ContextPolicy(
                profile.context_window,
                profile.output_limit,
                profile.service_tokens,
                StructuredMode(profile.structured_mode),
                profile.retry.validation_retries,
            ),
        )

    @provide(scope=Scope.APP)
    def requirements_extraction_agent(
        self, generator: StructuredOutputGenerator
    ) -> RequirementsExtractionAgent:
        return RequirementsExtractionAgent(generator)

    @provide(scope=Scope.APP)
    def extraction_policy(self, settings: Settings) -> ExtractionPolicy:
        profile: LLMSettings = settings.llm
        return ExtractionPolicy(
            ModelProfile(
                profile.model,
                StructuredMode(profile.structured_mode),
                profile.context_window,
                profile.output_limit,
                profile.service_tokens,
            ),
            profile_digest(settings),
            DEFAULT_TASK_ID,
            profile.retry.max_total_requests,
            profile.retry.deadline_seconds,
            profile.retry.request_timeout_seconds,
            profile.retry.network_retries,
            profile.retry.validation_retries,
        )

    @provide(scope=Scope.APP)
    def steps(
        self,
        stores: ExtractionStoreFactory,
        documents: DocumentService,
        builder: ExtractionContextBuilder,
        requirements_extraction_agent: RequirementsExtractionAgent,
        policy: ExtractionPolicy,
    ) -> ExtractionSteps:
        return ExtractionSteps(stores, documents, builder, requirements_extraction_agent, policy)

    @provide(scope=Scope.APP)
    async def graph(
        self, steps: ExtractionSteps, settings: Settings, workflow: ClarificationWorkflow
    ) -> AsyncGenerator[ExtractionGraph]:
        dsn: str = (
            database_url(settings)
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )
        serde: JsonPlusSerializer = JsonPlusSerializer(
            pickle_fallback=False, allowed_json_modules=[], allowed_msgpack_modules=[]
        )
        stack: AsyncExitStack
        async with AsyncExitStack() as stack:
            pool: AsyncConnectionPool[
                AsyncConnection[dict[str, object]]
            ] = await stack.enter_async_context(
                AsyncConnectionPool[AsyncConnection[dict[str, object]]](
                    conninfo=dsn,
                    min_size=1,
                    max_size=2,
                    timeout=3,
                    kwargs={"autocommit": True, "row_factory": dict_row},
                    check=AsyncConnectionPool.check_connection,
                    open=False,
                )
            )
            saver: AsyncPostgresSaver = AsyncPostgresSaver(pool, serde=serde)
            yield LangGraphExtraction(steps, saver, workflow)

    @provide(scope=Scope.APP)
    def extraction_service(
        self, stores: ExtractionStoreFactory, documents: DocumentService, settings: Settings
    ) -> RequirementsExtractionService:
        profile: StoredModelProfile = StoredModelProfile.model_validate(
            settings.llm.model_dump(mode="json", exclude={"api_key"})
        )
        return RequirementsExtractionService(stores, documents, profile, profile_digest(settings))

    @provide(scope=Scope.APP)
    def extraction_worker(
        self,
        stores: ExtractionStoreFactory,
        graph: ExtractionGraph,
        capacity: GenerationCapacity,
        settings: Settings,
        clarifications: ClarificationStoreFactory,
    ) -> ExtractionWorker:
        return ExtractionWorker(
            stores, graph, capacity, settings.llm.retry.deadline_seconds, clarifications
        )
