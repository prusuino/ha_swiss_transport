# Security Policy

## Supported Versions

Only the latest release is supported. Please update to the latest version before reporting an issue.

## Reporting a Vulnerability

This integration reads public timetable data from transport.opendata.ch over HTTPS and has no write access to any external system. Two things go beyond that: the optional opentransportdata.swiss (OJP) real-time token, which is stored in the config entry like any other integration secret and sent only as a bearer token in requests to that API, and the coordinates of each configured station, which are sent once to OpenStreetMap's Nominatim service to resolve the station address. No other data leaves your instance. If you believe you have found a security issue (e.g. in how the token is handled, how data is parsed or how entities are exposed), please report it privately via [GitHub Security Advisories](../../security/advisories/new) rather than opening a public issue.

For anything that is not security-sensitive (bugs, feature requests), please use the regular [Issues](../../issues) tab instead.
