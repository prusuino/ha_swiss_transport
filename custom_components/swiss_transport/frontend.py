"""Serving of the bundled Lovelace card (swiss-transport-card.js).

Registers a static path so the card file bundled in this integration's
frontend/ directory is reachable under /swiss_transport_files/. Adding it as a
Lovelace resource is left to the user: writing into another component's
storage is not an integration's job, and the resource list belongs to the
dashboard configuration the user controls. The README documents the one-time
registration.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "swiss-transport-card.js"
CARD_URL_BASE = f"/{DOMAIN}_files/{CARD_FILENAME}"
_REGISTERED_FLAG = f"{DOMAIN}_card_served"


async def async_serve_card(hass: HomeAssistant, version: str) -> None:
    """Make the bundled card file reachable over HTTP.

    Idempotent per HA run; safe to call from every config entry setup. The
    file is served without cache headers, so an updated card takes effect
    after a browser reload even though the user's resource URL never changes.
    """
    if hass.data.get(_REGISTERED_FLAG):
        return
    hass.data[_REGISTERED_FLAG] = True

    card_path = Path(__file__).parent / "frontend" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_BASE, str(card_path), cache_headers=False)]
    )
    _LOGGER.debug("Serving the bundled card at %s (version %s)", CARD_URL_BASE, version)
