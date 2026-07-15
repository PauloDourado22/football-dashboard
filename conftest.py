import os

# Must happen before `import app`, since app.py raises RuntimeError at import
# time if API_KEY is unset. Setting a dummy value here lets the whole test
# suite import the app without needing a real .env file.
os.environ.setdefault("API_KEY", "test-key")

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.cache.clear()
    return app_module.app.test_client()
