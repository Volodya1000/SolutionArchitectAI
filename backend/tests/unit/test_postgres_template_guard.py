import pytest

from backend.test_helpers.postgres_isolation import isolated_test_database
from solution_architect_ai.config.models import DatabaseSettings


@pytest.mark.anyio
@pytest.mark.parametrize("database", ["solution_architect", "postgres", "development"])
async def test_database_isolation_rejects_non_test_templates_before_connecting(
    database: str,
) -> None:
    with pytest.raises(ValueError, match="dedicated migrated _test template"):
        async with isolated_test_database(DatabaseSettings(database=database)):
            pytest.fail("A non-test template must never be cloned")
