"""Shared device_info for a Swiss Transport station."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_FROM_NAME, CONF_STATION_NAME, CONF_TO_NAME, DOMAIN


def device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    name = entry.data.get(CONF_STATION_NAME) or entry.title
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=name,
        manufacturer="transport.opendata.ch (search.ch)",
        model="Departure board",
        entry_type=None,
    )


def connection_device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    frm = entry.data.get(CONF_FROM_NAME) or ""
    to = entry.data.get(CONF_TO_NAME) or ""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"{frm} → {to}",
        manufacturer="transport.opendata.ch (search.ch)",
        model="Connection",
        entry_type=None,
    )
