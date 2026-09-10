# piHole Add-on for Splunk (ta_pihole)

A Splunk Technology Add-on (TA) that collects DNS query statistics, query logs,
and top domains/clients from a [Pi-hole](https://pi-hole.net/) instance via its
REST API, built with Splunk's [UCC framework](https://github.com/splunk/addonfactory-ucc-generator).

**Version:** 1.1.0 · **Author:** Aaron Stone · **Splunk compatibility:** Enterprise & Cloud, Python 3.9+

---

## Features

- **Stats summary** (`pihole_stats_summary`) — polls `/api/stats/summary` and
  writes query totals, blocked %, client counts, etc. as **metrics**
  (log-to-metrics) to a metrics index.
- **Query log** (`pihole_queries`) — polls `/api/queries` and writes one
  **event** per DNS query (domain, client, type, status, reply, upstream).
  Incremental collection via KV Store checkpoint, safe for Splunk Cloud /
  search head clustering.
- **Top domains / top clients** (`pihole_top_lists`) — polls
  `/api/stats/top_domains` and `/api/stats/top_clients` for periodic top-N
  snapshots.
- **Live field/metric discovery** — the Fields/Values picker on each input is
  populated by a real call to your Pi-hole, not a hardcoded list, so the
  options always match what your Pi-hole version actually returns.
- Session-based authentication (Pi-hole v6+ `/api/auth`), with automatic
  re-login on session expiry and proper logout after each collection run.
- Standard TA proxy support, encrypted credential storage, and a live
  connectivity check when you save an account.

## Requirements

- Splunk Enterprise or Splunk Cloud, Python 3.9+ (tested forward-compatible
  with 3.13)
- Pi-hole v6+ (session-based `/api/auth`; earlier Pi-hole versions using a
  static API token are not supported)
- Network access from the Splunk indexer/heavy forwarder running this TA to
  your Pi-hole's web interface port

## Installation

1. Download the packaged `.tar.gz`/`.spl` from [Releases](../../releases) (or
   build it yourself — see [Development](#development) below).
2. Splunk Web → **Apps → Manage Apps → Install app from file**, or extract
   into `$SPLUNK_HOME/etc/apps/` and restart Splunk.
3. Create two indexes ahead of time (or let your index management process
   create them):
   - a regular **events** index for query-log / top-list data
   - a **metrics** index (`datatype = metric`) for the stats-summary data

## Configuration

### 1. Create a Pi-hole account

**Configuration → Account → Add**

| Field | Description |
|---|---|
| Name | A unique name for this connection |
| Pi-hole base URL | e.g. `https://pi.hole` — no trailing slash, no `/api` suffix |
| Password | Your Pi-hole admin password, or (recommended) an **application password** generated under Pi-hole's *Settings → Web Interface/API* — independently revocable |
| Verify TLS certificate | Uncheck only if your Pi-hole uses a self-signed cert you can't add to the trust store |

Saving the account performs a live login test against Pi-hole and rejects the
save if authentication fails.

### 2. (Optional) Configure a proxy

**Configuration → Proxy** — standard UCC proxy tab, honored on every API call.

### 3. Add inputs

**Inputs → Create New Input**, choose one of:

| Input | Writes to | Notes |
|---|---|---|
| Pi-hole Stats Summary (metrics) | a **metrics** index | "Values" picker: which summary metrics to ingest |
| Pi-hole Query Log (events) | an events index | "Fields" picker: which query fields to ingest. `id` is always included |
| Pi-hole Top Domains/Clients (events) | an events index | "Collections": top_domains and/or top_clients. "Count": how many entries per list. "Fields": which fields to ingest |

For every input: pick the **Account** you created, then open the **Fields**/
**Values** dropdown — it calls your Pi-hole live and lists the fields actually
present on a sample record. Leaving the picker empty ingests every available
field (safe default; nothing is silently dropped).

## Data collected

| Sourcetype | Index type | Source |
|---|---|---|
| `pihole:stats:metrics` | metrics | `/api/stats/summary` |
| `pihole:dns:query` | events | `/api/queries` |
| `pihole:stats:top_domains` | events | `/api/stats/top_domains` |
| `pihole:stats:top_clients` | events | `/api/stats/top_clients` |

`pihole:dns:query` ships with CIM field aliases (`domain AS query`,
`client AS src`, `type AS record_type`, `upstream AS dest`) for alignment with
the Network Resolution data model.

### Example searches

```spl
# Recent blocked queries
index=pihole sourcetype=pihole:dns:query status=GRAVITY
| table _time domain client_ip status

# Block rate over time
| mstats avg(pihole.queries_percent_blocked) as pct_blocked
  WHERE index=pihole_metrics span=5m

# Top blocked domains snapshot
index=pihole sourcetype=pihole:stats:top_domains
| sort -count | table domain count
```

## Known limitations

- **`top_clients` returns nothing**: Pi-hole's **privacy level** (Settings →
  Privacy) suppresses this data — level 2+ hides domain detail, level 3+
  hides client identity — on the corresponding API endpoints. This is
  Pi-hole intentionally withholding the data, not a bug in the TA. The
  modular input logs a warning whenever a top-list call returns zero rows.
- The query-log input uses a small time-window overlap to avoid boundary
  gaps between collection runs, which can occasionally re-ingest a query at
  the edge of a window (dedupe on `id` in SPL if this matters for your use
  case, since `id` is always present).
- Only Pi-hole v6+'s session-based auth is supported (no legacy static API
  token support).

## Development

Built with [`splunk-add-on-ucc-framework`](https://pypi.org/project/splunk-add-on-ucc-framework/).

```bash
pip install splunk-add-on-ucc-framework
ucc-gen build --source package --config globalConfig.json --ta-version <version> -o output
ucc-gen package --path output/ta_pihole
```

### Repo layout

```
globalConfig.json        # UCC UI/config schema (account, proxy, 3 inputs, custom REST handler)
package/
  bin/
    pihole_client.py                 # Pi-hole session-auth REST client (login/logout/retry)
    pihole_common.py                 # shared config readers + flatten() field-naming util
    pihole_stats_summary_helper.py   # metrics input
    pihole_queries_helper.py         # query-log input (KV Store checkpointed)
    pihole_top_lists_helper.py       # top-domains/top-clients input
    ta_pihole_rh_account.py          # account REST handler override (live connectivity test)
    ta_pihole_rh_field_options.py    # custom REST endpoint powering the live Fields/Values pickers
  default/
    props.conf, transforms.conf      # sourcetype config, log-to-metrics schema, CIM aliases
  lib/requirements.txt               # solnlib pinned to 7.0.0 (avoids a grpc/otel dependency
                                      # introduced in 8.x that breaks on Splunk's Python 3.9)
```

### Portability

This TA targets Splunk's bundled Python 3.9+. After every `ucc-gen build`,
strip the compiled `charset_normalizer` package (pulled in by `requests`;
`chardet` is vendored as the pure-Python fallback) and re-run a portability
check before packaging:

```bash
rm -rf output/ta_pihole/lib/charset_normalizer output/ta_pihole/lib/*__mypyc*.so
```

### Validation

```bash
ucc-gen validate --addon-path output/ta_pihole --included-tags cloud
```

Currently passes with **0 errors / 0 failures / 0 future_failures**.

## Versioning

This project follows [Semantic Versioning](https://semver.org/): MAJOR for
breaking config/field/metric-name changes, MINOR for new features (e.g. new
inputs or pickers), PATCH for bug fixes.

## License

Add your license of choice here (e.g. Apache 2.0, matching most Splunk
add-ons in the ecosystem).
