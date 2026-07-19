"""Swiss Transport – Home Assistant Integration (departure boards)."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_CONNECTION
from .coordinator import SwissConnectionCoordinator, SwissTransportCoordinator
from .dashboard import async_remove_orphan_cards, async_remove_station_card
from .frontend import async_register_card

_LOGGER = logging.getLogger(__name__)

_ORPHAN_SWEEP_SCHEDULED = f"{DOMAIN}_orphan_sweep_scheduled"

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        integration = await async_get_integration(hass, DOMAIN)
        await async_register_card(hass, str(integration.version))
    except Exception:  # noqa: BLE001 - card registration must never block setup
        _LOGGER.exception("Automatic registration of the bundled Lovelace card failed")

    if not hass.data.get(_ORPHAN_SWEEP_SCHEDULED):
        hass.data[_ORPHAN_SWEEP_SCHEDULED] = True

        async def _sweep(_event) -> None:
            try:
                await async_remove_orphan_cards(hass)
            except Exception:  # noqa: BLE001 - cleanup must never break startup
                _LOGGER.exception("Orphaned departures-dashboard card sweep failed")

        if hass.is_running:
            hass.async_create_task(_sweep(None))
        else:
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _sweep)

    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONNECTION:
        coordinator = SwissConnectionCoordinator(hass, entry)
    else:
        coordinator = SwissTransportCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the station's auto-added dashboard card when the entry is deleted."""
    try:
        await async_remove_station_card(hass, entry.entry_id)
    except Exception:  # noqa: BLE001 - dashboard cleanup must never block entry removal
        _LOGGER.exception("Automatic departures-dashboard card removal failed for %s", entry.entry_id)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator: SwissTransportCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
