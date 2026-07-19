"""Constants for the Swiss Transport integration."""
DOMAIN = "swiss_transport"

# Public timetable API of opendata.ch (backed by search.ch). No key required.
API_BASE = "https://transport.opendata.ch/v1"

# The source enforces a rate limit; poll conservatively. A departure board
# is still useful at this cadence because it shows the next several
# departures, not just one.
UPDATE_INTERVAL_SECONDS = 90
FETCH_TIMEOUT_SECONDS = 30

# How many upcoming departures to fetch/show by default.
DEFAULT_LIMIT = 8
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
