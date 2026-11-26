import os

from solution_architect_ai.di.server import main as serve


def main() -> None:
    # The container must accept its proxy's traffic; Compose publishes on loopback by default.
    os.environ.setdefault(
        "SAA_SERVER__HOST",
        "0.0.0.0",  # nosec B104
    )
    serve()


if __name__ == "__main__":
    main()
