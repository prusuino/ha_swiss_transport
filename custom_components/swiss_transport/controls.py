"""Shared device_info for the global dashboard controls (time + mode)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .localization import t


def controls_device_info(hass: HomeAssistant) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, "controls")},
        name=t("controls_device_name", hass),
        manufacturer="Swiss Transport",
        model="Dashboard controls",
        entry_type=None,
    )
