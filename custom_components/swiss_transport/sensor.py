"""Departure-board sensor: state = next departure time, attributes = the
full list of upcoming departures for the station."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    CONF_ENTRY_TYPE,
    CONF_FROM_ID,
    CONF_FROM_NAME,
    CONF_STATION_NAME,
    CONF_TO_ID,
    CONF_TO_NAME,
    DOMAIN,
    ENTRY_TYPE_CONNECTION,
)
from .coordinator import SwissConnectionCoordinator, SwissTransportCoordinator
from .dashboard import async_add_station_card
from .device import connection_device_info, device_info
from .localization import t

_LOGGER = logging.getLogger(__name__)
ATTRIBUTION = "Data: transport.opendata.ch (search.ch)"
# The station board additionally resolves the address via OpenStreetMap and,
# when a token is configured, real-time data via opentransportdata.swiss.
ATTRIBUTION_STATION = (
    "Data: transport.opendata.ch (search.ch). Address: © OpenStreetMap contributors"
)
ATTRIBUTION_OJP = "Real-time: opentransportdata.swiss (OJP)"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONNECTION:
        sensor = SwissConnectionSensor(hass, coordinator, entry)
    else:
        sensor = SwissTransportDeparturesSensor(hass, coordinator, entry)
    async_add_entities([sensor])

    async def _add_card(hass: HomeAssistant, entry: ConfigEntry, entity_id: str) -> None:
        try:
            await async_add_station_card(hass, entry, entity_id)
        except Exception:  # noqa: BLE001 - dashboard setup must never break the sensor
            _LOGGER.exception("Automatic dashboard card setup failed")

    hass.async_create_task(_add_card(hass, entry, sensor.entity_id))


class SwissTransportDeparturesSensor(CoordinatorEntity[SwissTransportCoordinator], SensorEntity):
    """Next departure at a station; the full board is in the attributes."""

    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:train"

    @property
    def attribution(self) -> str:
        """Credit every source actually used, including the optional OJP
        real-time feed when the board was enriched with it."""
        base = ATTRIBUTION_STATION
        if (self.coordinator.data or {}).get("realtime"):
            return f"{base}. {ATTRIBUTION_OJP}"
        return base

    def __init__(
        self, hass: HomeAssistant, coordinator: SwissTransportCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._hass_ref = hass
        self._entry = entry
        name = entry.data.get(CONF_STATION_NAME) or entry.title
        self._attr_name = t("sensor_departures_name", hass)
        self._attr_unique_id = f"{entry.entry_id}_departures"
        self._attr_device_info = device_info(hass, entry)
        self.entity_id = f"sensor.swiss_transport_{slugify(name)}"

    @property
    def native_value(self):
        deps = (self.coordinator.data or {}).get("departures") or []
        if not deps:
            return None
        # device_class timestamp expects a timezone-aware datetime.
        return datetime.fromtimestamp(deps[0]["departure_ts"], tz=timezone.utc)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        deps = data.get("departures") or []
        return {
            "station_id": data.get("station_id"),
            "station_name": data.get("station_name"),
            "address": data.get("address"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "departure_count": len(deps),
            # True when the board was enriched with opentransportdata.swiss
            # OJP real-time data (fresher delays, cancellations, occupancy).
            "realtime": bool(data.get("realtime")),
            # Active disruption messages for the station (OJP only).
            "alerts": data.get("alerts") or [],
            # The whole board — the bundled card renders this; also handy for
            # templates and automations.
            "departures": deps,
        }


class SwissConnectionSensor(CoordinatorEntity[SwissConnectionCoordinator], SensorEntity):
    """Next connection for a saved from -> to route; the full list is in the
    attributes and rendered by the connection card."""

    _attr_has_entity_name = False
    _attr_attribution = ATTRIBUTION
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:transit-connection-variant"

    def __init__(
        self, hass: HomeAssistant, coordinator: SwissConnectionCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._hass_ref = hass
        self._entry = entry
        frm = entry.data.get(CONF_FROM_NAME) or ""
        to = entry.data.get(CONF_TO_NAME) or ""
        self._attr_name = t("sensor_connection_name", hass)
        self._attr_unique_id = f"{entry.entry_id}_connections"
        self._attr_device_info = connection_device_info(hass, entry)
        self.entity_id = f"sensor.swiss_transport_{slugify(f'{frm}_{to}')}"

    @property
    def native_value(self):
        cons = (self.coordinator.data or {}).get("connections") or []
        if not cons:
            return None
        return datetime.fromtimestamp(cons[0]["departure_ts"], tz=timezone.utc)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        cons = data.get("connections") or []
        return {
            "from_name": data.get("from_name") or self._entry.data.get(CONF_FROM_NAME),
            "to_name": data.get("to_name") or self._entry.data.get(CONF_TO_NAME),
            # Station IDs let the bundled card query the timetable for a chosen
            # time directly (global date/time selection on the dashboard).
            "from_id": self._entry.data.get(CONF_FROM_ID),
            "to_id": self._entry.data.get(CONF_TO_ID),
            "connection_count": len(cons),
            "connections": cons,
        }
