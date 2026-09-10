piHole Add-on for Splunk (ta_pihole)
=====================================

What it collects
-----------------
This add-on polls a Pi-hole instance's REST API (Pi-hole v6+, session-based auth)
for three kinds of data:

1. Stats summary (metrics)      - /api/stats/summary
   Query totals/blocked/cached/forwarded, unique domains, client counts, and
   domains-on-blocklist count. Written as metrics (log-to-metrics) to a
   METRICS index. Sourcetype: pihole:stats:metrics

2. Query log (events)           - /api/queries
   One event per DNS query (domain, client, query type, status, reply,
   response time, upstream). Sourcetype: pihole:dns:query
   Incremental via KV Store checkpoint (safe for Splunk Cloud/SHC); a small
   time-window overlap is used to avoid boundary gaps (may occasionally
   duplicate a query at the edge of a collection window).

3. Top domains / top clients (events) - /api/stats/top_domains, /api/stats/top_clients
   Periodic top-N snapshot, one event per domain/client per run.
   Sourcetypes: pihole:stats:top_domains, pihole:stats:top_clients

Field/metric selection (live, server-driven)
-----------------------------------------------
Each of the three inputs has a multiselect - Values (stats summary) or Fields
(query log, top domains/clients) - that controls what's actually written.
Unlike earlier versions, these pickers are NOT a hardcoded list: selecting an
account populates the dropdown with a live call to your actual Pi-hole (a
one-record sample), so the options always match real field names for your
Pi-hole version. This fixed a bug in 1.0.0 where the query-log picker offered
"client", "reply", and "response_time" as options that never matched any real
event field (Pi-hole's API nests these as client.ip/client.name and
reply.type/reply.time), so selecting them silently dropped that data.

- Stats summary "Values": one entry per numeric field in /api/stats/summary,
  named "pihole.<flattened_field>" (e.g. pihole.queries_total). NOTE: this is
  a rename from 1.0.0's curated dotted names (pihole.queries.total) - update
  any saved searches/dashboards built against the old metric names.
- Query log "Fields": one entry per field Pi-hole actually returns on a query
  record. "id" is mandatory and always included in every event regardless of
  selection - it's not offered as a toggle. The event's _time is always taken
  from Pi-hole's own query time, even if "time" itself is deselected.
- Top domains/clients "Fields": one entry per raw field Pi-hole returns for
  that list type (e.g. domain/count for top domains; ip/name/count for top
  clients - NOTE: renamed from 1.0.0's client_ip/client_name to match the raw
  API field names). "account", "rank", and "total_queries" are synthesized by
  this add-on (not real API fields) and are always kept regardless of
  selection.

A blank/empty selection on any of these falls back to "all fields" rather
than silently dropping all data - so an input saved before ever opening the
picker still ingests everything, same as before this feature existed.

If "top_clients" (or top_domains) comes back empty even though the input runs
without errors, check Pi-hole's privacy level under Settings > Privacy:
level 2+ hides domain detail and level 3+ hides client identities on these
endpoints - that's Pi-hole intentionally withholding the data, not a bug in
this add-on. A warning is logged (visible in the TA's internal log / the
monitoring dashboard) whenever a top-list call returns zero rows.

Required Pi-hole permissions
-----------------------------
The account used just needs to be able to log in to the Pi-hole web/API
(regular admin password or an application password generated under
Settings > Web Interface / API in the Pi-hole UI - recommended, since it's
independently revocable). No special roles/permissions exist in Pi-hole
beyond that.

Authentication
---------------
Pi-hole v6+ uses short-lived session tokens (SID), not a static API key:
the add-on logs in via POST /api/auth with the configured password, uses the
returned SID for the duration of each collection run, and logs out
afterward. Sessions are capped concurrently on the Pi-hole side, so the
add-on does not hold a session open between runs.

Proxy support
-------------
Standard TA proxy tab (Configuration > Proxy) is honored on every API call,
including login.

Indexes / sourcetypes
----------------------
- Stats summary requires a METRICS index (datatype=metric).
- Query log and top-lists inputs require a regular events index.
- Default sourcetypes are listed above; do not rename the underlying
  sourcetypes without also updating props.conf/transforms.conf.

Upgrade notes
--------------
meta.restRoot is "ta_pihole" - do not change this in future versions, it
would orphan stored accounts/passwords and break the KV Store checkpoint
keys used by the query-log input.
