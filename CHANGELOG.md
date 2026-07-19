# Changelog

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
