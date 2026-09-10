[pihole_stats_summary://<name>]
account = The Pi-hole connection to use for this input.
index = Must be a metrics index (datatype=metric). Data is written as log-to-metrics events and converted at index time. (Default: default)
interval = How often to poll /api/stats/summary, in seconds. This is a single lightweight call per run. (Default: 60)
metrics_to_ingest = Which metrics to write to the metrics index each run. Unselected metrics are dropped before writing (the underlying API call still returns all of them; this just reduces metrics volume).
python.required = {3.7|3.9|3.13}
* For Python scripts only, selects which Python version to use.
* Set to "3.9" to use the Python 3.9 version.
* Set to "3.13" to use the Python 3.13 version.
* Optional.
* Default: not set

[pihole_queries://<name>]
account = The Pi-hole connection to use for this input.
fields_to_ingest = Which fields of each DNS query record to keep. The event timestamp is always taken from Pi-hole's own query time regardless of whether 'time' is selected here.
index = Splunk events index for individual DNS query records. (Default: default)
interval = How often to poll /api/queries for new DNS query log entries, in seconds. Query volume can be high on busy networks; avoid setting this too low. (Default: 300)
python.required = {3.7|3.9|3.13}
* For Python scripts only, selects which Python version to use.
* Set to "3.9" to use the Python 3.9 version.
* Set to "3.13" to use the Python 3.13 version.
* Optional.
* Default: not set

[pihole_top_lists://<name>]
account = The Pi-hole connection to use for this input.
fields_to_ingest = Which fields to keep on each top-domain/top-client record. Fields that don't apply to a given list (e.g. domain on a top-clients record) are simply absent.
index = Splunk events index for top-domains/top-clients snapshot records. (Default: default)
interval = How often to poll the top-domains/top-clients snapshot, in seconds. (Default: 300)
lists_to_collect = Which top-N snapshots to collect each run. (Default: top_domains,top_clients)
top_count = How many top entries to request per list (Pi-hole's 'count' query parameter). (Default: 25)
python.required = {3.7|3.9|3.13}
* For Python scripts only, selects which Python version to use.
* Set to "3.9" to use the Python 3.9 version.
* Set to "3.13" to use the Python 3.13 version.
* Optional.
* Default: not set
