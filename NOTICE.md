# Data Sources & Attribution

This integration retrieves data at runtime from the following third-party
services. It is unofficial and not affiliated with, endorsed by, or supported
by any of them or by any transport operator.

## 1. Timetable & departures — transport.opendata.ch (search.ch)

The station boards and connections come from the **transport.opendata.ch** API,
a free service operated by [Opendata.ch](https://opendata.ch/) that is backed by
the timetable of **search.ch**. The API requires no account or key. Please keep
usage reasonable — it is a community service with rate limits.

**Attribution:** *Data: transport.opendata.ch (search.ch)*

## 2. Transport mode pictograms — SBB design system

Transport-mode icons are taken from the **SBB pictogram library**
(`sbb-design-systems/picto-library`, Apache-2.0 licence) and are used in
their original blue/white form, in a timetable/orientation context. A copy of
the licence ships next to the files as
`custom_components/swiss_transport/frontend/LICENSE-pictograms.txt`. The
pictograms are not the SBB logo; the SBB trademarks remain with SBB.

## 3. Line colours — Traewelling/line-colors

The operator line colours of buses and trams (badge background and text)
come from the **Traewelling/line-colors** collection (`line-colors-CH.csv`),
published under **CC0 1.0** (public domain dedication). The table ships as
`custom_components/swiss_transport/frontend/line-colors.json` and is
regenerated with `scripts/generate_line_colors.py`.

## 4. Real-time data (optional) — opentransportdata.swiss (OJP 2.0)

When you configure an API token, station boards are additionally enriched with
real-time information (fresher delays, cancellations, platform changes,
disruption messages and occupancy) from the **Open Journey Planner (OJP 2.0)**
API of [opentransportdata.swiss](https://opentransportdata.swiss/), the official
Swiss open-transport-data platform operated by the *Systemaufgabe
Kundeninformation (SKI)*. A free token is required and obtained by the user.
The data is published as Open Government Data; reuse is permitted with source
attribution. This feature is entirely optional — without a token the
integration works purely from transport.opendata.ch.

**Attribution:** *Real-time: opentransportdata.swiss (OJP)*

## 5. Station address — OpenStreetMap / Nominatim

To show a human-readable address under a station name, the integration performs
a one-time reverse-geocoding lookup per station via **OpenStreetMap Nominatim**.
OpenStreetMap data is © OpenStreetMap contributors, licensed under the
[Open Database License (ODbL)](https://www.openstreetmap.org/copyright).

**Attribution:** *Address: © OpenStreetMap contributors*

---

Every entity this integration creates sets Home Assistant's `attribution`
attribute to credit the sources actually used (surfaced in the entity's "More
Info" dialog). If you build dashboards or republish this data, please keep that
attribution visible.
