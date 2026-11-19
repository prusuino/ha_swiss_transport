"""A rejected real-time token opens one reauthentication and leaves the
departure board running."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.swiss_transport.const import (
    CONF_ENTRY_TYPE,
    CONF_LIMIT,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
    ENTRY_TYPE_STATION,
)
from custom_components.swiss_transport.coordinator import OjpAuthError, SwissTransportCoordinator

BOARD = {"station": "Luzern", "departures": [], "latitude": None, "longitude": None}


def _board(hass: HomeAssistant, station_id: str, token: str | None = "bad-token") -> SwissTransportCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=f"station_{station_id}", title="Board",
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_STATION, CONF_STATION_ID: station_id, CONF_STATION_NAME: "Board", CONF_LIMIT: 5},
        options={"ojp_token": token} if token else {},
    )
    entry.add_to_hass(hass)
    return SwissTransportCoordinator(hass, entry)


def _reauth_flows(hass: HomeAssistant) -> list:
    return hass.config_entries.flow.async_progress_by_handler(DOMAIN, match_context={"source": SOURCE_REAUTH})


async def test_rejected_token_starts_one_reauth_and_keeps_the_board(hass: HomeAssistant, enable_custom_integrations) -> None:
    first = _board(hass, "8505000")
    second = _board(hass, "8507000")
    with (
        patch("custom_components.swiss_transport.coordinator.async_fetch_stationboard", side_effect=lambda *a: dict(BOARD)),
        patch("custom_components.swiss_transport.coordinator.async_fetch_ojp_stationboard", side_effect=OjpAuthError(401)),
    ):
        data = await first._async_update_data()
        await first._async_update_data()
        await second._async_update_data()
        await hass.async_block_till_done()
    assert data["station"] == "Luzern"
    flows = _reauth_flows(hass)
    assert len(flows) == 1
    assert flows[0]["step_id"] == "reauth_confirm"


async def test_accepted_token_starts_no_reauth(hass: HomeAssistant, enable_custom_integrations) -> None:
    board = _board(hass, "8505000", "good-token")
    with (
        patch("custom_components.swiss_transport.coordinator.async_fetch_stationboard", side_effect=lambda *a: dict(BOARD)),
        patch("custom_components.swiss_transport.coordinator.async_fetch_ojp_stationboard", return_value={}),
        patch("custom_components.swiss_transport.coordinator._apply_ojp"),
    ):
        await board._async_update_data()
        await hass.async_block_till_done()
    assert _reauth_flows(hass) == []
