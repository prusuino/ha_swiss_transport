import json
from pathlib import Path
"""Constants for the Swiss Transport integration."""
DOMAIN = "swiss_transport"

# Public timetable API of opendata.ch. Since October 2026 it answers from its
# own copy of the national timetable and real-time feed of
# opentransportdata.swiss. No key required.
API_BASE = "https://transport.opendata.ch/v1"

# The API is shared by thousands of applications and has no fixed limit per
# client, but throttles one that asks too often; poll conservatively. A
# departure board is still useful at this cadence because it shows the next
# several departures, not just one, and the real-time feed behind it is
# renewed every 30 seconds.
UPDATE_INTERVAL_SECONDS = 90
# A connection search is the costlier request and its answer changes less
# from minute to minute, so saved routes are asked for less often.
CONNECTION_UPDATE_INTERVAL_SECONDS = 300
# Once the API answers HTTP 429 it is throttling this client — every further
# poll is a wasted request. Back off this long, then probe again.
RATE_LIMIT_BACKOFF_SECONDS = 1800
# /connections answered in up to 36.5 s in measurements; 30 s cut those off.
FETCH_TIMEOUT_SECONDS = 45

# How many upcoming departures to fetch/show by default.
DEFAULT_LIMIT = 8

# How a train line is named: "category" ("S" for S9, the digit counts as run id,
# the long-standing label), "full" ("S9") or "number" ("9"). Bus and tram always
# show the number.
LINE_LABEL_CATEGORY = "category"
LINE_LABEL_FULL = "full"
LINE_LABEL_NUMBER = "number"
LINE_LABELS = [LINE_LABEL_CATEGORY, LINE_LABEL_FULL, LINE_LABEL_NUMBER]
DEFAULT_LINE_LABEL = LINE_LABEL_CATEGORY
MAX_LIMIT = 20

# Which kind of config entry this is: a station departure board, or a
# saved connection (from -> to). Entries created before this distinction
# have no CONF_ENTRY_TYPE key; treat that as a station board.
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_STATION = "station"
ENTRY_TYPE_CONNECTION = "connection"

CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_LIMIT = "limit"
CONF_TRANSPORTATIONS = "transportations"
CONF_LINE_LABEL = "line_label"

# Optional real-time enrichment via the official opentransportdata.swiss
# Open Journey Planner (OJP 2.0) API. When a token is configured, the station
# board is enriched with second-accurate delays, platform changes and
# disruption messages. Delays, cancellations and occupancy come from
# transport.opendata.ch without a token.
CONF_OJP_TOKEN = "ojp_token"
# Optional, station boards with a token only: show just these lines in these
# directions. A list of ids "<line>|<direction>", e.g. "6|H", as the OJP
# answer names them (H outward, R return). At a tram or bus stop the two
# directions leave from the two sides of the street, and the direction is
# what tells them apart everywhere: the Haltekante the answer also carries is
# missing at many stops, and a short-turn journey keeps its direction while
# its destination changes. Empty: the whole stop.
CONF_DIRECTIONS = "directions"
# With a direction filter the board is asked for this many times the wanted
# rows (the other directions are thrown away), up to DIRECTION_FETCH_MAX.
DIRECTION_FETCH_FACTOR = 3
DIRECTION_FETCH_MAX = 60
OJP_ENDPOINT = "https://api.opentransportdata.swiss/ojp20"
OJP_REQUESTOR_REF = "HA-Swiss-Transport"

# Connection (from -> to) config keys.
CONF_FROM_ID = "from_id"
CONF_FROM_NAME = "from_name"
CONF_TO_ID = "to_id"
CONF_TO_NAME = "to_name"

DEFAULT_CONNECTION_LIMIT = 6
MAX_CONNECTION_LIMIT = 12

# Canonical transportation-type filter values (language-independent), matching
# the API's `transportations` query parameter. Empty = all types.
TRANSPORT_TYPES = [
    "train",
    "tram",
    "bus",
    "ship",
    "cableway",
]

# Global dashboard time controls — a single datetime + mode selector that every
# card can follow, letting you look up the timetable for any moment (and as a
# departure or arrival time). Created once, owned by the first-loaded entry.
CONTROL_TIME_UNIQUE = f"{DOMAIN}_time"
CONTROL_MODE_UNIQUE = f"{DOMAIN}_mode"
TIME_ENTITY_ID = "datetime.swiss_transport_time"
MODE_ENTITY_ID = "select.swiss_transport_mode"
CONTROLS_OWNER = f"{DOMAIN}_controls_owner"

MODE_LIVE = "live"        # live board / next connections, now (with real-time)
MODE_DEPART = "depart"    # timetable departing at the selected time
MODE_ARRIVE = "arrive"    # timetable arriving by the selected time
MODES = [MODE_LIVE, MODE_DEPART, MODE_ARRIVE]

# The integration's own version, shown on the service card. Read from the
# manifest so that a release never needs to touch two places.
VERSION: str = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))["version"]
