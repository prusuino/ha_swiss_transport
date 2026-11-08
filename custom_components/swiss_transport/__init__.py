"""Swiss Transport – Home Assistant Integration (departure boards)."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CONF_ENTRY_TYPE, CONTROLS_OWNER, DOMAIN, ENTRY_TYPE_CONNECTION
from .coordinator import SwissConnectionCoordinator, SwissTransportCoordinator

type SwissTransportConfigEntry = ConfigEntry[SwissTransportCoordinator | SwissConnectionCoordinator]
from .issues import async_clear_entry_issues
from .frontend import async_serve_card
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

# datetime + select provide the single, dashboard-wide time/mode controls;
# their platforms create one entity each (guarded by CONTROLS_OWNER).
PLATFORMS = ["sensor", "datetime", "select"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions; they do not depend on a config entry."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SwissTransportConfigEntry) -> bool:
    try:
        integration = await async_get_integration(hass, DOMAIN)
        await async_serve_card(hass, str(integration.version))
    except Exception:  # noqa: BLE001 - serving the card must never block setup
        _LOGGER.exception("Serving the bundled Lovelace card failed")

    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONNECTION:
        coordinator = SwissConnectionCoordinator(hass, entry)
    else:
        coordinator = SwissTransportCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: SwissTransportConfigEntry) -> None:
    await entry.runtime_data.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: SwissTransportConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_clear_entry_issues(hass, entry.entry_id)
        # If this entry owned the shared controls, release ownership so another
        # entry recreates them on its next reload / the next restart.
        if hass.data.get(CONTROLS_OWNER) == entry.entry_id:
            hass.data.pop(CONTROLS_OWNER, None)
    return unloaded
