import json
import time

import import_declare_test
from solnlib import log
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi

from pihole_client import PiholeClient, PiholeAuthError, PiholeApiError
from pihole_common import APP, get_account, get_proxy_settings, get_log_level, flatten

SOURCETYPE = "pihole:dns:query"
PAGE_LENGTH = 100
MAX_PAGES_PER_RUN = 500          # safety cap so one run can't loop forever
OVERLAP_SECONDS = 5              # re-request a small overlap window to avoid boundary gaps
FIRST_RUN_LOOKBACK_SECONDS = 900  # how far back to start on a brand-new input
ALWAYS_KEPT_FIELDS = {"id"}      # mandatory - always emitted regardless of selection


def logger_for_input(input_name):
    return log.Logs().get_logger(f"{APP.lower()}_{input_name}")


def validate_input(definition: smi.ValidationDefinition):
    return


def _filter_fields(flat, selected_fields):
    """Restrict a flattened record to selected_fields (falls back to all fields
    if the selection is empty, so a blank config never silently drops all data).
    'id' is always kept regardless of selection - it's mandatory, not offered as
    a togglable option (see ALWAYS_EXCLUDED in ta_pihole_rh_field_options.py).
    Note: the event's _time is taken from the record BEFORE this filter runs, so
    deselecting 'time' only removes it from the event body, not from _time."""
    if not selected_fields:
        return flat
    return {k: v for k, v in flat.items() if k in selected_fields or k in ALWAYS_KEPT_FIELDS}


def _fetch_queries_page(client, from_ts, until_ts, cursor):
    params = {"from": from_ts, "until": until_ts, "length": PAGE_LENGTH}
    if cursor is not None:
        params["cursor"] = cursor
    return client.get("/api/queries", params=params)


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter):
    for input_name, input_item in inputs.inputs.items():
        normalized_input_name = input_name.split("/")[-1]
        logger = logger_for_input(normalized_input_name)
        session_key = inputs.metadata["session_key"]
        try:
            logger.setLevel(get_log_level(logger, session_key))
            log.modular_input_start(logger, normalized_input_name)

            account_name = input_item.get("account")
            index = input_item.get("index")
            account = get_account(session_key, account_name)
            proxies = get_proxy_settings(session_key)

            selected_raw = input_item.get("fields_to_ingest") or ""
            selected_fields = {v.strip() for v in selected_raw.split(",") if v.strip()}

            ckpt = checkpointer.KVStoreCheckpointer(f"{APP}_checkpoints", session_key, APP)
            last_until = ckpt.get(normalized_input_name)
            now = int(time.time())
            from_ts = int(last_until) - OVERLAP_SECONDS if last_until else now - FIRST_RUN_LOOKBACK_SECONDS
            until_ts = now

            total_written = 0
            newest_time_seen = from_ts

            with PiholeClient(
                base_url=account["base_url"], password=account["password"],
                verify_tls=account["verify_tls"], proxies=proxies, logger=logger,
            ) as client:
                cursor = None
                for _ in range(MAX_PAGES_PER_RUN):
                    page = _fetch_queries_page(client, from_ts, until_ts, cursor)
                    records = page.get("queries", [])
                    if not records:
                        break

                    for record in records:
                        flat = flatten(record)
                        q_time = flat.get("time")
                        try:
                            event_time = float(q_time) if q_time is not None else None
                        except (TypeError, ValueError):
                            event_time = None
                        if event_time and event_time > newest_time_seen:
                            newest_time_seen = event_time

                        emitted = _filter_fields(flat, selected_fields)

                        event_writer.write_event(
                            smi.Event(
                                data=json.dumps(emitted, ensure_ascii=False, default=str),
                                index=index,
                                sourcetype=SOURCETYPE,
                                source=normalized_input_name,
                                time=event_time,  # None -> Splunk uses ingest time as fallback
                            )
                        )
                        total_written += 1

                    # Only checkpoint after a full run's worth of events are written.
                    next_cursor = page.get("cursor")
                    if not next_cursor or next_cursor == cursor:
                        break
                    cursor = next_cursor

            ckpt.update(normalized_input_name, newest_time_seen)

            log.events_ingested(
                logger, input_name, SOURCETYPE, total_written, index, account=account_name,
            )
            log.modular_input_end(logger, normalized_input_name)
        except (PiholeAuthError, PiholeApiError) as e:
            log.log_exception(logger, e, "pihole_api_error",
                               msg_before=f"Pi-hole API error in input {normalized_input_name}: ")
        except Exception as e:
            log.log_exception(logger, e, "pihole_queries_error",
                               msg_before=f"Unhandled exception in input {normalized_input_name}: ")
