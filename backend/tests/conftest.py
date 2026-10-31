import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()
    yield
    cache.clear()
