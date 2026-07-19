"""Config flow for the Swiss Transport integration.

Add a station in two steps: type part of its name, then pick the exact stop
from the search results. Repeatable — add the integration again for another
station. Options let you adjust the number of departures and the transport
types shown.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ENTRY_TYPE,
    CONF_FROM_ID,
    CONF_FROM_NAME,
    CONF_LIMIT,
    CONF_OJP_TOKEN,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TO_ID,
    CONF_TO_NAME,
    CONF_TRANSPORTATIONS,
    DEFAULT_CONNECTION_LIMIT,
    DEFAULT_LIMIT,
    DOMAIN,
    ENTRY_TYPE_CONNECTION,
    ENTRY_TYPE_STATION,
    MAX_CONNECTION_LIMIT,
    MAX_LIMIT,
    TRANSPORT_TYPES,
)
from .coordinator import async_search_stations
from .localization import t, transport_type_label

CONF_QUERY = "query"
CONF_MODE = "mode"
CONF_FROM_QUERY = "from_query"
CONF_TO_QUERY = "to_query"
MODE_STATION = "station"
MODE_CONNECTION = "connection"


def _limit_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=1, max=MAX_LIMIT, step=1, mode=NumberSelectorMode.BOX)
    )


def _token_selector() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _effective_token(hass) -> str:
    """The OJP token currently configured anywhere in the integration. The
    token is integration-wide: set once, it applies to every station board."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        tok = (entry.options.get(CONF_OJP_TOKEN) or entry.data.get(CONF_OJP_TOKEN) or "").strip()
        if tok:
            return tok
    return ""


def _apply_token_everywhere(hass, token: str, current_entry_id: str | None = None) -> None:
    """Keep the OJP token consistent across all entries so it can be managed
    from any one of them. Options are the single source of truth; the token is
    stripped from entry .data. The current entry's options are set by the
    caller's returned result, so only its .data is cleaned here."""
    token = (token or "").strip()
    for entry in hass.config_entries.async_entries(DOMAIN):
        new_options = dict(entry.options)
        new_data = dict(entry.data)
        changed = False
        if entry.entry_id != current_entry_id:
            if token:
                if new_options.get(CONF_OJP_TOKEN) != token:
                    new_options[CONF_OJP_TOKEN] = token
                    changed = True
            elif CONF_OJP_TOKEN in new_options:
                new_options.pop(CONF_OJP_TOKEN)
                changed = True
        if CONF_OJP_TOKEN in new_data:
            new_data.pop(CONF_OJP_TOKEN)
            changed = True
        if changed:
            hass.config_entries.async_update_entry(entry, data=new_data, options=new_options)


def _transport_selector(hass) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=v, label=transport_type_label(v, hass))
                for v in TRANSPORT_TYPES
            ],
            multiple=True,
            mode=SelectSelectorMode.LIST,
            sort=False,
        )
    )


class SwissTransportConfigFlow(ConfigFlow, domain=DOMAIN):
    """Search for a station, then pick it."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SwissTransportOptionsFlow()

    def __init__(self) -> None:
        self._results: dict[str, dict] = {}
        self._from: dict | None = None  # chosen origin (connection mode)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            if user_input[CONF_MODE] == MODE_CONNECTION:
                return await self.async_step_connection()
            return await self.async_step_station()

        schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=MODE_STATION): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=MODE_STATION, label=t("mode_station", self.hass)),
                            SelectOptionDict(value=MODE_CONNECTION, label=t("mode_connection", self.hass)),
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_station(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            query = (user_input.get(CONF_QUERY) or "").strip()
            try:
                stations = await async_search_stations(self.hass, query)
            except Exception:  # noqa: BLE001 - map to form error
                errors["base"] = "cannot_connect"
            else:
                if not stations:
                    errors["base"] = "no_stations_found"
                else:
                    self._results = {s["id"]: s for s in stations}
                    return await self.async_step_pick()

        schema = vol.Schema({vol.Required(CONF_QUERY, default=""): str})
        return self.async_show_form(step_id="station", data_schema=schema, errors=errors)

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            station = self._results.get(user_input[CONF_STATION_ID])
            if station is None:
                return await self.async_step_user()

            await self.async_set_unique_id(f"station_{station['id']}")
            self._abort_if_unique_id_configured()

            transportations = user_input.get(CONF_TRANSPORTATIONS) or []
            data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_STATION,
                CONF_STATION_ID: station["id"],
                CONF_STATION_NAME: station["name"],
                CONF_LIMIT: int(user_input.get(CONF_LIMIT, DEFAULT_LIMIT)),
                CONF_TRANSPORTATIONS: transportations,
            }
            token = (user_input.get(CONF_OJP_TOKEN) or "").strip()
            if token:
                data[CONF_OJP_TOKEN] = token
            return self.async_create_entry(
                title=t("device_name", self.hass, station=station["name"]),
                data=data,
            )

        options = [
            SelectOptionDict(value=s["id"], label=s["name"])
            for s in self._results.values()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_STATION_ID): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN, sort=False)
                ),
                vol.Optional(CONF_LIMIT, default=DEFAULT_LIMIT): _limit_selector(),
                vol.Optional(CONF_TRANSPORTATIONS, default=[]): _transport_selector(self.hass),
                # Pre-filled with the token already configured elsewhere so a
                # new station inherits it without re-entering.
                vol.Optional(CONF_OJP_TOKEN, default=_effective_token(self.hass)): _token_selector(),
            }
        )
        return self.async_show_form(step_id="pick", data_schema=schema)

    # --- Connection mode: search origin, then destination ---

    async def async_step_connection(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Search for the origin and destination stations by name."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                from_hits = await async_search_stations(self.hass, (user_input.get(CONF_FROM_QUERY) or "").strip())
                to_hits = await async_search_stations(self.hass, (user_input.get(CONF_TO_QUERY) or "").strip())
            except Exception:  # noqa: BLE001 - map to form error
                errors["base"] = "cannot_connect"
            else:
                if not from_hits or not to_hits:
                    errors["base"] = "no_stations_found"
                else:
                    self._results = {f"from:{s['id']}": s for s in from_hits}
                    self._results.update({f"to:{s['id']}": s for s in to_hits})
                    return await self.async_step_connection_pick()

        schema = vol.Schema(
            {
                vol.Required(CONF_FROM_QUERY, default=""): str,
                vol.Required(CONF_TO_QUERY, default=""): str,
            }
        )
        return self.async_show_form(step_id="connection", data_schema=schema, errors=errors)

    async def async_step_connection_pick(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick the exact origin and destination, plus the number of connections."""
        if user_input is not None:
            frm = self._results.get(user_input[CONF_FROM_ID])
            to = self._results.get(user_input[CONF_TO_ID])
            if frm is None or to is None:
                return await self.async_step_connection()

            await self.async_set_unique_id(f"connection_{frm['id']}_{to['id']}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=t("connection_device_name", self.hass, frm=frm["name"], to=to["name"]),
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_CONNECTION,
                    CONF_FROM_ID: frm["id"],
                    CONF_FROM_NAME: frm["name"],
                    CONF_TO_ID: to["id"],
                    CONF_TO_NAME: to["name"],
                    CONF_LIMIT: int(user_input.get(CONF_LIMIT, DEFAULT_CONNECTION_LIMIT)),
                },
            )

        from_options = [
            SelectOptionDict(value=k, label=s["name"])
            for k, s in self._results.items() if k.startswith("from:")
        ]
        to_options = [
            SelectOptionDict(value=k, label=s["name"])
            for k, s in self._results.items() if k.startswith("to:")
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_FROM_ID): SelectSelector(
                    SelectSelectorConfig(options=from_options, mode=SelectSelectorMode.DROPDOWN, sort=False)
                ),
                vol.Required(CONF_TO_ID): SelectSelector(
                    SelectSelectorConfig(options=to_options, mode=SelectSelectorMode.DROPDOWN, sort=False)
                ),
                vol.Optional(CONF_LIMIT, default=DEFAULT_CONNECTION_LIMIT): NumberSelector(
                    NumberSelectorConfig(min=1, max=MAX_CONNECTION_LIMIT, step=1, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="connection_pick", data_schema=schema)


class SwissTransportOptionsFlow(OptionsFlow):
    """Adjust the number of results (and, for a station board, the transport
    types shown)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        is_connection = self.config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONNECTION
        data = self.config_entry.data
        options = self.config_entry.options

        if user_input is not None:
            new = {CONF_LIMIT: int(user_input.get(CONF_LIMIT, DEFAULT_LIMIT))}
            if not is_connection:
                new[CONF_TRANSPORTATIONS] = user_input.get(CONF_TRANSPORTATIONS) or []
                token = (user_input.get(CONF_OJP_TOKEN) or "").strip()
                if token:
                    new[CONF_OJP_TOKEN] = token
                # The token is integration-wide: sync it to every other entry
                # (and clean it out of .data) so it can be managed from here.
                _apply_token_everywhere(self.hass, token, current_entry_id=self.config_entry.entry_id)
            return self.async_create_entry(data=new)

        default_limit = int(
            options.get(CONF_LIMIT, data.get(CONF_LIMIT, DEFAULT_CONNECTION_LIMIT if is_connection else DEFAULT_LIMIT))
        )
        fields: dict = {}
        if is_connection:
            fields[vol.Optional(CONF_LIMIT, default=default_limit)] = NumberSelector(
                NumberSelectorConfig(min=1, max=MAX_CONNECTION_LIMIT, step=1, mode=NumberSelectorMode.BOX)
            )
        else:
            fields[vol.Optional(CONF_LIMIT, default=default_limit)] = _limit_selector()
            fields[
                vol.Optional(
                    CONF_TRANSPORTATIONS,
                    default=list(options.get(CONF_TRANSPORTATIONS, data.get(CONF_TRANSPORTATIONS) or [])),
                )
            ] = _transport_selector(self.hass)
            fields[
                vol.Optional(CONF_OJP_TOKEN, default=_effective_token(self.hass))
            ] = _token_selector()
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
