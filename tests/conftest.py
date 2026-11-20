"""Shared fixtures for the Swiss Transport tests.

Nothing is fetched from the network. The older tests patch the readers per
test; tests that set the integration up request `api`, which answers every
request of the client session from memory at a fixed moment (see
`tests/common.py`).
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from .common import NOW, FakeApi


@pytest.fixture
def api(hass: HomeAssistant, enable_custom_integrations, aioclient_mock, freezer) -> FakeApi:
    """The faked services, with the clock stopped at `NOW`."""
    freezer.move_to(NOW)
    return FakeApi(aioclient_mock)
