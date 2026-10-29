from pathlib import Path

import pytest

from agent_veriq.core.models import ApiSpec
from agent_veriq.core.openapi_loader import load_spec_file
from agent_veriq.core.openapi_parser import parse_spec

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> ApiSpec:
        return parse_spec(load_spec_file(FIXTURES / name))

    return _load
