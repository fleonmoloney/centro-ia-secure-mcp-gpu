from pathlib import Path

import pytest

from secmcp.guard import Guard
from secmcp.tools import Toolbox

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def toolbox():
    return Toolbox(DATA / "docs", DATA / "private")


@pytest.fixture
def guard(toolbox):
    return Guard.build(toolbox, ("ejemplo.uy",), ("CANARIO-7f3a91",))
