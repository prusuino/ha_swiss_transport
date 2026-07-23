# Changelog

## 1.2.1 — 2026-07-24

Fixes "too many requests" (HTTP 429) from transport.opendata.ch.

- **Connection polling slowed to 5 minutes** (station boards keep their 90 s cadence). The API allows only 1000 connection queries per day — the previous 90 s poll used 960 of those for a single saved route, so a second route exhausted the quota by midday.
- **Automatic backoff on HTTP 429** — when the daily quota is exhausted, the affected entry pauses for 30 minutes instead of hammering the API, and resumes its normal cadence with the next successful update.

## 1.2.0 — 2026-07-20

Timetable browsing (any date/time, departures or arrivals) and connection details.

- **Timetable browsing** — two new global helper entities, `datetime.swiss_transport_time` and `select.swiss_transport_mode` (`live` / `depart` / `arrive`), let every card show the board for **any date and time** instead of only the live view. A new **`swiss-transport-controls-card`** (Live / Departure / Arrival toggle + date/time picker) is added to the top of the auto-created dashboard and switches all its cards at once; manually placed cards follow via the new `datetime_entity`/`mode_entity` card options. Timetable data is fetched by the browser directly from transport.opendata.ch; in timetable mode the planned schedule is shown (no real-time enrichment) with a "Timetable: …" banner.
- **Arrivals board** — in arrival mode station boards flip to an arrivals view: label "Ankünfte"/"Arrivals" and the direction column switches from *Nach/To* to *Von/From*, showing where each service comes from. Connection cards interpret the selected time as the latest arrival.
- **Connection card: platforms & transfers** — platform columns for both departure and arrival (hidden when empty, as on the station board), plus a transfer line per connection: the change station with its arrival → onward platform.
- **New sensor attributes**: connection entries gain `changes` (transfer stations with platforms); the connection sensor exposes the from/to station ids.

## 1.1.0 — 2026-07-19

Optional real-time enrichment.

- **Real-time via opentransportdata.swiss (OJP 2.0)** — configure a free API token to enrich station boards with fresher, second-accurate delays, **cancellations**, platform changes, **disruption messages** and **occupancy**. Entirely optional: without a token everything keeps working from transport.opendata.ch. The token is entered once (in the station's setup or Configure dialog) and enriches every board.
- **Card additions** (station board): cancelled departures are struck through and marked, a disruption banner is shown above the board, and an occupancy column appears when data is available. New visual-editor toggles `show_occupancy` and `show_alerts`, plus `max_alerts` to control how many disruption messages are shown before "+N more" (0 = all).
- **New sensor attributes**: `realtime` (bool) and `alerts` (disruption messages); `departures` entries gain `cancelled` and `occupancy` when real-time is enabled.
- **Attribution**: the station sensor now credits every source actually used — transport.opendata.ch (search.ch), OpenStreetMap contributors (address), and opentransportdata.swiss (OJP, when real-time is active). See NOTICE.md.

## 1.0.0 — 2026-07-19

Initial release.

- **Departure boards** — the live Abfahrtstafel of any Swiss public transport station (train, tram, bus, ship, cableway). Search by name when adding the integration, repeatable for more stations. One sensor per station: state = next departure (timestamp), attributes = the full upcoming board plus the reverse-geocoded station address.
- **Connections (from → to)** — a saved route, e.g. a daily commute. One sensor per route with the next connections as attributes (departure/arrival times and platforms, delay, duration, transfers, lines used).
- **Two bundled Lovelace cards**, self-registering with a visual editor:
  - `swiss-transport-card` — a real departure board (symbol · time · countdown · destination · platform · info) with a live date/time bar, Swiss-scheme line badges (S-Bahn white, IC/IR red, tram/bus/ship/cableway in mode colors) and transport-mode icons. The platform column is dropped for bus/tram stops.
  - `swiss-transport-connection-card` — a board for a saved route (departure · countdown · line(s) · arrival · duration/transfers).
  - Both show the current date/time and a type label; both can be toggled off in the editor.
- **Automatic dashboard** — an "ÖV Abfahrten" / "Departures" dashboard is created on first setup, with one card per station/connection added and removed automatically.
- Optional filter by transport type and adjustable number of results, live-editable via the options dialog.
- Localized in German, English, French, and Italian.
- Data from the free public transport.opendata.ch timetable API (search.ch); no account required. Provided as-is, without warranty — see the README disclaimer.
