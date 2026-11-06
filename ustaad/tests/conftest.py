"""
tests/conftest.py — pytest configuration for offline unit test isolation.
"""
from __future__ import annotations

import os
import pytest
from agent.config import get_settings


@pytest.fixture(autouse=True)
def isolate_unit_tests(monkeypatch, tmp_path):
    """
    Ensure unit tests run strictly in offline simulation mode without
    external network dependencies.
    """
    monkeypatch.setenv("SIMULATOR", "1")
    monkeypatch.setenv("HINDSIGHT_API_KEY", "")
    monkeypatch.setenv("HINDSIGHT_BASE_URL", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

