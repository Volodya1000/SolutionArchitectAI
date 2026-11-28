import pytest

from tools.check_sqlalchemy_mocks import session_mock_lines


@pytest.mark.parametrize(
    "source",
    [
        "from unittest.mock import AsyncMock\nfrom sqlalchemy.ext.asyncio import AsyncSession\n"
        "value = AsyncMock(spec=AsyncSession)",
        "from unittest.mock import MagicMock as M\nfrom sqlalchemy.orm import Session as S\n"
        "value = M(spec_set=S)",
        "import unittest.mock as m\nimport sqlalchemy.ext.asyncio as db\n"
        "value = m.Mock(db.AsyncSession)",
        "from unittest import mock as m\nfrom sqlalchemy import orm\n"
        "value = m.MagicMock(spec=orm.Session)",
        "import unittest.mock\nimport sqlalchemy.orm\n"
        "value = unittest.mock.Mock(spec_set=sqlalchemy.orm.Session)",
        "from unittest.mock import Mock\nfrom sqlalchemy.orm import Session\n"
        "value = Mock(spec=Session())",
        "from unittest.mock import Mock\nfrom sqlalchemy.orm.session import Session as S\n"
        "value = Mock(spec=S)",
        "from unittest.mock import AsyncMock\nfrom sqlalchemy.ext.asyncio.session import AsyncSession\n"
        "value = AsyncMock(spec_set=AsyncSession)",
    ],
)
def test_session_mocks_are_rejected_regardless_of_import_aliases(source: str) -> None:
    assert session_mock_lines(source) == [3]


@pytest.mark.parametrize(
    "source",
    [
        "from unittest.mock import AsyncMock\nfrom sqlalchemy.ext.asyncio import AsyncSession\n"
        "value = AsyncSession()",
        "from unittest.mock import AsyncMock\nvalue = AsyncMock(spec=ExternalModel)",
        "from unittest.mock import Mock\nvalue = Mock(return_value=Session)",
        "class Session: pass\nfrom unittest.mock import Mock\nvalue = Mock(spec=Session)",
        "from other import Mock\nfrom sqlalchemy.orm import Session\nvalue = Mock(spec=Session)",
    ],
)
def test_external_doubles_and_real_sessions_remain_allowed(source: str) -> None:
    assert session_mock_lines(source) == []
