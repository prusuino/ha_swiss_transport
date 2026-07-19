# Changelog

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
