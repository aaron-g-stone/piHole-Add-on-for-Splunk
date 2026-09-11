import json
import time

import import_declare_test
from solnlib import log
from splunklib import modularinput as smi

from pihole_client import PiholeClient, PiholeAuthError, PiholeApiError
from pihole_common import APP, get_account, get_proxy_settings, get_log_level, flatten

SOURCETYPE = "pihole:stats:metrics"


def logger_for_input(input_name):
    return log.Logs().get_logger(f"{APP.lower()}_{input_name}")


def validate_input(definition: smi.ValidationDefinition):
    # Live connectivity is validated when the account is saved
    # (see ta_pihole_rh_account.py); nothing additional to check here.
    return


def _summary_to_metrics(summary, account_name, selected_metrics=None):
    """Flatten the /api/stats/summary response and emit one metric per numeric
    field, named "pihole.<flattened_key>" - the same flattening used by the
    live field-discovery endpoint (see ta_pihole_rh_field_options.py), so a
    metric selected in the "Values" picker always matches a metric actually
    produced here. Restricted to selected_metrics if given (falls back to all
    metrics if empty/None, so a blank selection never silently drops all data).
    Non-numeric fields (e.g. status strings) are skipped - metric values must
    be numeric."""
    flat = flatten(summary)
    records = []
    for key, value in flat.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        metric_name = f"pihole.{key}"
        if selected_metrics and metric_name not in selected_metrics:
            continue
        records.append({"metric_name": metric_name, "value": value, "account": account_name})
    return records


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

            selected_raw = input_item.get("metrics_to_ingest") or ""
            selected_metrics = {v.strip() for v in selected_raw.split(",") if v.strip()}

            with PiholeClient(
                base_url=account["base_url"], password=account["password"],
                verify_tls=account["verify_tls"], proxies=proxies, logger=logger,
            ) as client:
                summary = client.get("/api/stats/summary")

            records = _summary_to_metrics(summary, account_name, selected_metrics)
            now = time.time()
            for record in records:
                event_writer.write_event(
                    smi.Event(
                        data=json.dumps(record, ensure_ascii=False),
                        index=index,
                        sourcetype=SOURCETYPE,
                        source=normalized_input_name,
                        time=now,
                    )
                )

            log.events_ingested(
                logger, input_name, SOURCETYPE, len(records), index, account=account_name,
            )
            log.modular_input_end(logger, normalized_input_name)
        except (PiholeAuthError, PiholeApiError) as e:
            log.log_exception(logger, e, "pihole_api_error",
                               msg_before=f"Pi-hole API error in input {normalized_input_name}: ")
        except Exception as e:
            log.log_exception(logger, e, "pihole_stats_summary_error",
                               msg_before=f"Unhandled exception in input {normalized_input_name}: ")
