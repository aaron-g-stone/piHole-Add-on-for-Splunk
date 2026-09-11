import json
import time

import import_declare_test
from solnlib import log
from splunklib import modularinput as smi

from pihole_client import PiholeClient, PiholeAuthError, PiholeApiError
from pihole_common import APP, get_account, get_proxy_settings, get_log_level, flatten

SOURCETYPE_DOMAINS = "pihole:stats:top_domains"
SOURCETYPE_CLIENTS = "pihole:stats:top_clients"

# Synthesized dimensions added by this input itself (not raw API fields) - always
# kept regardless of selection, and never offered as a toggle in the Fields picker
# (the live discovery endpoint only samples raw API rows, so it naturally never
# lists these either - see ta_pihole_rh_field_options.py).
ALWAYS_KEPT_FIELDS = {"account", "rank", "total_queries"}


def logger_for_input(input_name):
    return log.Logs().get_logger(f"{APP.lower()}_{input_name}")


def validate_input(definition: smi.ValidationDefinition):
    return


def _filter_fields(record, selected_fields):
    """Restrict a record to selected_fields (falls back to all fields if the
    selection is empty). ALWAYS_KEPT_FIELDS are kept regardless of selection -
    they're synthesized dimensions, not real API fields users can toggle."""
    if not selected_fields:
        return record
    return {k: v for k, v in record.items() if k in selected_fields or k in ALWAYS_KEPT_FIELDS}


def _collect_top_domains(client, count, account_name, selected_fields):
    data = client.get("/api/stats/top_domains", params={"count": count})
    total_queries = data.get("total_queries")
    records = []
    for rank, row in enumerate(data.get("domains", []), start=1):
        # Flatten the raw API row as-is (e.g. domain, count) rather than hand-
        # picking/renaming fields, so these keys always match what the live
        # field-discovery endpoint reports for this dataset.
        record = flatten(row)
        record["rank"] = rank
        record["total_queries"] = total_queries
        record["account"] = account_name
        records.append(_filter_fields(record, selected_fields))
    return records


def _collect_top_clients(client, count, account_name, selected_fields):
    data = client.get("/api/stats/top_clients", params={"count": count})
    total_queries = data.get("total_queries")
    records = []
    for rank, row in enumerate(data.get("clients", []), start=1):
        # Raw fields as returned by Pi-hole (e.g. ip, name, count) - not renamed.
        record = flatten(row)
        record["rank"] = rank
        record["total_queries"] = total_queries
        record["account"] = account_name
        records.append(_filter_fields(record, selected_fields))
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

            lists_raw = input_item.get("lists_to_collect") or "top_domains,top_clients"
            wanted = {v.strip() for v in lists_raw.split(",") if v.strip()}
            try:
                count = int(input_item.get("top_count") or 25)
            except (TypeError, ValueError):
                count = 25

            fields_raw = input_item.get("fields_to_ingest") or ""
            selected_fields = {v.strip() for v in fields_raw.split(",") if v.strip()}

            now = time.time()
            total_written = 0
            zero_result_lists = []

            with PiholeClient(
                base_url=account["base_url"], password=account["password"],
                verify_tls=account["verify_tls"], proxies=proxies, logger=logger,
            ) as client:
                if "top_domains" in wanted:
                    domain_records = _collect_top_domains(client, count, account_name, selected_fields)
                    if not domain_records:
                        zero_result_lists.append("top_domains")
                    for record in domain_records:
                        event_writer.write_event(
                            smi.Event(
                                data=json.dumps(record, ensure_ascii=False, default=str),
                                index=index, sourcetype=SOURCETYPE_DOMAINS,
                                source=normalized_input_name, time=now,
                            )
                        )
                        total_written += 1

                if "top_clients" in wanted:
                    client_records = _collect_top_clients(client, count, account_name, selected_fields)
                    if not client_records:
                        zero_result_lists.append("top_clients")
                    for record in client_records:
                        event_writer.write_event(
                            smi.Event(
                                data=json.dumps(record, ensure_ascii=False, default=str),
                                index=index, sourcetype=SOURCETYPE_CLIENTS,
                                source=normalized_input_name, time=now,
                            )
                        )
                        total_written += 1

            if zero_result_lists:
                # A 200 response with zero rows is common when Pi-hole's privacy
                # level hides client/domain detail (level 2+ hides domains, level
                # 3+ hides client identities) - log it plainly so it's not mistaken
                # for a silent failure. See Settings > Privacy in the Pi-hole UI.
                logger.warning(
                    "%s returned zero rows for: %s. If this is unexpected, check "
                    "Pi-hole's privacy level (Settings > Privacy) - higher levels "
                    "suppress domain/client detail on these endpoints.",
                    normalized_input_name, ", ".join(zero_result_lists),
                )

            log.events_ingested(
                logger, input_name, "pihole:stats:top_lists", total_written, index,
                account=account_name,
            )
            log.modular_input_end(logger, normalized_input_name)
        except (PiholeAuthError, PiholeApiError) as e:
            log.log_exception(logger, e, "pihole_api_error",
                               msg_before=f"Pi-hole API error in input {normalized_input_name}: ")
        except Exception as e:
            log.log_exception(logger, e, "pihole_top_lists_error",
                               msg_before=f"Unhandled exception in input {normalized_input_name}: ")
