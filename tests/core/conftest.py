import tempfile

import pytest
import trio


@pytest.fixture
def touch_path():
    with tempfile.TemporaryDirectory() as base_dir:
        yield trio.Path(base_dir) / 'touch.txt'
