import os

# Must happen before `import app`, since app.py raises RuntimeError at import
# time if API_KEY or SECRET_KEY is unset. Setting dummy values here lets the
# whole test suite import the app without needing a real .env file.
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.cache.clear()
    return app_module.app.test_client()
