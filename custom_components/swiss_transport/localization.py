"""Runtime string localization (entity names, dashboard content).

Home Assistant's built-in translation system only covers config/options flow
text. Entity names and card content are set by this integration's code, so we
do a minimal lookup here keyed by hass.config.language, falling back to English.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant

SUPPORTED_LANGUAGES = ("de", "en", "fr", "it")

STRINGS: dict[str, dict[str, str]] = {
    "device_name": {
        "de": "ÖV-Abfahrten {station}",
        "en": "Departures {station}",
        "fr": "Départs {station}",
        "it": "Partenze {station}",
    },
    "sensor_departures_name": {
        "de": "Abfahrten",
        "en": "Departures",
        "fr": "Départs",
        "it": "Partenze",
    },
    "mode_station": {
        "de": "Ankunfts-/Abfahrtstafel einer Haltestelle",
        "en": "Arrival/departure board of a station",
        "fr": "Tableau des arrivées/départs d'un arrêt",
        "it": "Tabellone arrivi/partenze di una fermata",
    },
    "mode_connection": {
        "de": "Verbindung (von → nach)",
        "en": "Connection (from → to)",
        "fr": "Liaison (de → à)",
        "it": "Collegamento (da → a)",
    },
    "connection_device_name": {
        "de": "{frm} → {to}",
        "en": "{frm} → {to}",
        "fr": "{frm} → {to}",
        "it": "{frm} → {to}",
    },
    "sensor_connection_name": {
        "de": "Verbindungen",
        "en": "Connections",
        "fr": "Liaisons",
        "it": "Collegamenti",
    },
    "dashboard_title": {
        "de": "ÖV Abfahrten",
        "en": "Departures",
        "fr": "Départs TP",
        "it": "Partenze TP",
    },
    "controls_device_name": {
        "de": "ÖV Dashboard-Steuerung",
        "en": "Departures dashboard controls",
        "fr": "Commandes du tableau de bord",
        "it": "Controlli del cruscotto",
    },
    "control_time_name": {
        "de": "ÖV Zeitpunkt",
        "en": "Timetable moment",
        "fr": "Moment horaire",
        "it": "Momento orario",
    },
    "control_mode_name": {
        "de": "ÖV Modus",
        "en": "Timetable mode",
        "fr": "Mode horaire",
        "it": "Modalità orario",
    },
    "control_card_title": {
        "de": "Zeitpunkt & Modus",
        "en": "Time & mode",
        "fr": "Heure et mode",
        "it": "Ora e modalità",
    },
    "mode_all": {
        "de": "Alle",
        "en": "All",
        "fr": "Tous",
        "it": "Tutti",
    },
    "transport_train": {
        "de": "Zug",
        "en": "Train",
        "fr": "Train",
        "it": "Treno",
    },
    "transport_tram": {
        "de": "Tram",
        "en": "Tram",
        "fr": "Tram",
        "it": "Tram",
    },
    "transport_bus": {
        "de": "Bus",
        "en": "Bus",
        "fr": "Bus",
        "it": "Bus",
    },
    "transport_ship": {
        "de": "Schiff",
        "en": "Ship",
        "fr": "Bateau",
        "it": "Battello",
    },
    "transport_cableway": {
        "de": "Seilbahn",
        "en": "Cableway",
        "fr": "Téléphérique",
        "it": "Funivia",
    },
}

TRANSPORT_TYPE_KEYS = {
    "train": "transport_train",
    "tram": "transport_tram",
    "bus": "transport_bus",
    "ship": "transport_ship",
    "cableway": "transport_cableway",
}


def get_language(hass: HomeAssistant) -> str:
    lang = (hass.config.language or "en").lower().split("-")[0]
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def t(key: str, hass: HomeAssistant, **kwargs) -> str:
    lang = get_language(hass)
    template = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    return template.format(**kwargs) if kwargs else template


def transport_type_label(value: str, hass: HomeAssistant) -> str:
    key = TRANSPORT_TYPE_KEYS.get(value)
    return t(key, hass) if key else value
