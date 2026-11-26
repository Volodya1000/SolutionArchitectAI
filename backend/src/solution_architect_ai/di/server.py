import uvicorn

from solution_architect_ai.di.main import bootstrap


def main() -> None:
    settings = bootstrap()
    uvicorn.run(
        "solution_architect_ai.di.main:create_app",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
        workers=1,
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
