"""Global mode selector for the dashboard: live / departure / arrival.

- live: show the live board / next connections now (with real-time).
- depart: show the timetable departing at the selected time.
- arrive: show the timetable arriving by the selected time.

Created once (owned by the first-loaded entry); restored across restarts.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONTROL_MODE_UNIQUE,
    CONTROLS_OWNER,
    MODE_ENTITY_ID,
    MODE_LIVE,
    MODES,
)
from .controls import controls_device_info
from .localization import t


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # Singleton: only the entry that owns the controls creates it.
    owner = hass.data.get(CONTROLS_OWNER)
    if owner is not None and owner != entry.entry_id:
        return
    hass.data[CONTROLS_OWNER] = entry.entry_id
    async_add_entities([SwissTransportModeSelect(hass, entry)])


class SwissTransportModeSelect(RestoreEntity, SelectEntity):
    """Whether cards show the live board or the timetable for the chosen time."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:clock-time-four-outline"
    _attr_should_poll = False
    _attr_options = MODES
    _attr_translation_key = "mode"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._current = MODE_LIVE
        self._attr_name = t("control_mode_name", hass)
        self._attr_unique_id = CONTROL_MODE_UNIQUE
        self._attr_device_info = controls_device_info(hass)
        self.entity_id = MODE_ENTITY_ID

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in MODES:
            self._current = last.state

    @property
    def current_option(self) -> str:
        return self._current

    async def async_select_option(self, option: str) -> None:
        if option in MODES:
            self._current = option
            self.async_write_ha_state()
