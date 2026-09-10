"""Shared config-reading helpers for the ta_pihole modular inputs."""

from urllib.parse import quote

from solnlib import conf_manager

APP = "ta_pihole"   # must match meta.restRoot in globalConfig.json


def to_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_conf(session_key, conf_name):
    cm = conf_manager.ConfManager(
        session_key, APP,
        realm=f"__REST_CREDENTIAL__#{APP}#configs/conf-{conf_name}")
    return cm.get_conf(conf_name)


def get_account(session_key, account_name):
    """Returns dict: base_url, password, verify_tls (bool)."""
    stanza = get_conf(session_key, f"{APP}_account").get(account_name)
    return {
        "base_url": stanza.get("base_url"),
        "password": stanza.get("password"),
        "verify_tls": to_bool(stanza.get("verify_tls"), default=True),
    }


def get_proxy_settings(session_key):
    try:
        stanza = get_conf(session_key, f"{APP}_settings").get("proxy")
    except Exception:
        return None
    if not to_bool(stanza.get("proxy_enabled"), default=False):
        return None
    ptype = stanza.get("proxy_type", "http")
    if ptype == "socks5" and to_bool(stanza.get("proxy_rdns"), default=False):
        ptype = "socks5h"  # remote DNS resolution
    auth = ""
    if stanza.get("proxy_username"):
        auth = f'{quote(stanza["proxy_username"], safe="")}:{quote(stanza.get("proxy_password", ""), safe="")}@'
    url = f'{ptype}://{auth}{stanza["proxy_url"]}:{stanza["proxy_port"]}'
    return {"http": url, "https": url}


def get_log_level(logger, session_key):
    return conf_manager.get_log_level(
        logger=logger, session_key=session_key, app_name=APP,
        conf_name=f"{APP}_settings",
    )


def flatten(record, parent_key=""):
    """Flatten nested dicts with '_' joins, normalize keys to lowercase snake_case.
    Used by BOTH the modular inputs (to build emitted events/metrics) and the
    field-discovery REST endpoint (to populate the Fields/Values pickers), so the
    picklist always shows the exact keys that will actually appear on an event -
    no more hardcoded field-name guesses that can drift from the real API shape."""
    out = {}
    for k, v in record.items():
        key = f"{parent_key}_{k}" if parent_key else k
        key = key.lower()
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out
