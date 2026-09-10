import os
from pathlib import Path

import pytest

pytest_plugins = []

_basetemp = Path(__file__).resolve().parent.parent / ".pytest_tmp"
_basetemp.mkdir(exist_ok=True)
os.environ["TMP"] = str(_basetemp)
os.environ["TEMP"] = str(_basetemp)


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: async test")
    config.option.basetemp = str(_basetemp)
