"""Global date/time control for the dashboard.

A single datetime entity every card can follow to look up the timetable for a
chosen moment. Created once (owned by the first-loaded entry); its value is
restored across restarts.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import CONTROL_TIME_UNIQUE, CONTROLS_OWNER, DOMAIN, TIME_ENTITY_ID
from .controls import controls_device_info
from .localization import t


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # Singleton: only the first entry to reach here creates the control.
    owner = hass.data.get(CONTROLS_OWNER)
    if owner is not None and owner != entry.entry_id:
        return
    hass.data[CONTROLS_OWNER] = entry.entry_id
    async_add_entities([SwissTransportTime(hass, entry)])


class SwissTransportTime(RestoreEntity, DateTimeEntity):
    """The dashboard-wide selected moment."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:clock-edit-outline"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._value: datetime | None = None
        self._attr_name = t("control_time_name", hass)
        self._attr_unique_id = CONTROL_TIME_UNIQUE
        self._attr_device_info = controls_device_info(hass)
        self.entity_id = TIME_ENTITY_ID

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "unknown", "unavailable"):
            self._value = dt_util.parse_datetime(last.state)
        if self._value is None:
            self._value = dt_util.now()

    @property
    def native_value(self) -> datetime | None:
        return self._value

    async def async_set_value(self, value: datetime) -> None:
        self._value = value
        self.async_write_ha_state()
