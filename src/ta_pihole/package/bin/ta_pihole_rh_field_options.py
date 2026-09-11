"""
Custom REST endpoint backing the live "Fields"/"Values" pickers on the input forms.

Registered via globalConfig.json options.restHandlers (handlerType EAI, action
'list'). Unlike the account/settings/input handlers in this TA, this one is a raw
splunk.admin.MConfigHandler subclass rather than going through splunktaucclib's
AdminExternalHandler, since there's no backing conf-file schema here - the "list"
of results is computed live from a real call to the selected Pi-hole account,
not read from a stored conf stanza.

Given account=<name>&dataset=<summary|queries|top_domains|top_clients|top_lists>,
returns the field names actually present on a live sample from that dataset, so
the picker can never drift out of sync with what the real API returns (the root
cause of earlier picklist entries - client, reply, response_time - not matching
real event field names).
"""

import logging

import import_declare_test
import splunk.admin as admin

from pihole_client import PiholeClient, PiholeApiError, PiholeAuthError
from pihole_common import flatten, get_account, get_proxy_settings

log = logging.getLogger("splunk.ta_pihole_field_options")

# path, query params for a minimal one-record sample, and the key under which
# the list of records sits in the response (None = the response itself is the record).
DATASETS = {
    "summary": {"path": "/api/stats/summary", "params": {}, "list_key": None},
    "queries": {"path": "/api/queries", "params": {"length": 1}, "list_key": "queries"},
    "top_domains": {"path": "/api/stats/top_domains", "params": {"count": 1}, "list_key": "domains"},
    "top_clients": {"path": "/api/stats/top_clients", "params": {"count": 1}, "list_key": "clients"},
}

# Fields never offered as a toggle because the modular input always includes them
# regardless of selection (see the matching ALWAYS_KEPT/mandatory logic in the
# corresponding *_helper.py).
ALWAYS_EXCLUDED = {
    "queries": {"id"},
}


def _sample_fields(client, dataset_name):
    spec = DATASETS[dataset_name]
    data = client.get(spec["path"], params=spec["params"])
    if spec["list_key"] is None:
        flat = flatten(data)
        # Only numeric fields are usable as a metric value.
        return {k for k, v in flat.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    rows = data.get(spec["list_key"]) or []
    if not rows:
        return set()
    return set(flatten(rows[0]).keys())


def _discover(session_key, account_name, dataset):
    account = get_account(session_key, account_name)
    proxies = get_proxy_settings(session_key)
    with PiholeClient(
        base_url=account["base_url"], password=account["password"],
        verify_tls=account["verify_tls"], proxies=proxies,
    ) as client:
        if dataset == "top_lists":
            fields = set()
            for ds in ("top_domains", "top_clients"):
                fields |= _sample_fields(client, ds)
            return fields
        return _sample_fields(client, dataset)


class PiholeFieldOptionsHandler(admin.MConfigHandler):
    def setup(self):
        if self.requestedAction == admin.ACTION_LIST:
            self.supportedArgs.addOptArg("account")
            self.supportedArgs.addOptArg("dataset")

    def handleList(self, confInfo):
        session_key = self.getSessionKey()
        args = self.callerArgs.data
        account_name = (args.get("account") or [None])[0]
        dataset = (args.get("dataset") or [None])[0]

        valid_dataset = dataset in DATASETS or dataset == "top_lists"
        if not account_name or not valid_dataset:
            return  # nothing selected yet - empty option list, not an error

        try:
            fields = _discover(session_key, account_name, dataset)
        except (PiholeAuthError, PiholeApiError) as e:
            log.warning("field discovery failed for account=%s dataset=%s: %s",
                        account_name, dataset, e)
            return
        except Exception as e:
            log.exception("unexpected error during field discovery for account=%s dataset=%s: %s",
                           account_name, dataset, e)
            return

        excluded = ALWAYS_EXCLUDED.get(dataset, set())
        for name in sorted(fields - excluded):
            entry = confInfo[name]
            entry["label"] = name


admin.init(PiholeFieldOptionsHandler, admin.CONTEXT_NONE)
