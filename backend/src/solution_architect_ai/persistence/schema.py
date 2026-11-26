from functools import cache
from pathlib import Path

from alembic.script import ScriptDirectory


@cache
def migration_heads() -> frozenset[str]:
    scripts = ScriptDirectory(str(Path(__file__).with_name("migrations")))
    return frozenset(scripts.get_heads())
