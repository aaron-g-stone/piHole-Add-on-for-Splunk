
import import_declare_test

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    SingleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
from splunktaucclib.rest_handler.error import RestError
import logging

from pihole_client import PiholeClient, PiholeAuthError, PiholeApiError
from pihole_common import to_bool, get_proxy_settings


util.remove_http_proxy_env_vars()


special_fields = [
    field.RestField(
        'name',
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.Pattern(
                regex=r"""^[a-zA-Z]\w*$""",
            ),
            validator.String(
                max_len=100,
                min_len=1,
            )
        )
    )
]

fields = [
    field.RestField(
        'base_url',
        required=True,
        encrypted=False,
        default=None,
        validator=validator.Pattern(
            regex=r"""^(?:(?:https?|ftp|opc\.tcp):\/\/)?(?:\S+(?::\S*)?@)?(?:(?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])(?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){2}(?:\.(?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-4]))|(?:(?:[a-z\u00a1-\uffff0-9]+-?_?)*[a-z\u00a1-\uffff0-9]+)(?:\.(?:[a-z\u00a1-\uffff0-9]+-?)*[a-z\u00a1-\uffff0-9]+)*(?:\.(?:[a-z\u00a1-\uffff]{2,}))?)(?::\d{2,5})?(?:\/[^\s]*)?$""",
        )
    ),
    field.RestField(
        'password',
        required=True,
        encrypted=True,
        default=None,
        validator=validator.String(
            max_len=255,
            min_len=1,
        )
    ),
    field.RestField(
        'verify_tls',
        required=False,
        encrypted=False,
        default=True,
        validator=None
    )
]
model = RestModel(fields, name=None, special_fields=special_fields)


endpoint = SingleModel(
    'ta_pihole_account',
    model,
    config_name='account',
    need_reload=False,
)


class PiholeAccountHandler(AdminExternalHandler):
    """Adds a live connectivity check (real /api/auth login) on account create/edit,
    so a bad URL or password is caught at save time instead of on the first input run."""

    def handleCreate(self, confInfo):
        self._validate_connection()
        AdminExternalHandler.handleCreate(self, confInfo)

    def handleEdit(self, confInfo):
        self._validate_connection()
        AdminExternalHandler.handleEdit(self, confInfo)

    def _validate_connection(self):
        base_url = self.payload.get('base_url')
        password = self.payload.get('password')
        verify_tls = to_bool(self.payload.get('verify_tls'), default=True)

        # On edit, an unchanged password field may arrive masked/empty rather than
        # resent in cleartext; only re-validate live when we actually have both
        # a URL and a password value to test against.
        if not base_url or not password:
            return

        try:
            session_key = self.getSessionKey()
        except Exception:
            session_key = None

        proxies = None
        if session_key:
            try:
                proxies = get_proxy_settings(session_key)
            except Exception:
                proxies = None  # best-effort; don't block save on proxy lookup issues

        client = PiholeClient(
            base_url=base_url, password=password, verify_tls=verify_tls, proxies=proxies,
        )
        try:
            client.login()
            client.logout()
        except PiholeAuthError as e:
            raise RestError(400, f"Could not authenticate to Pi-hole: {e}")
        except PiholeApiError as e:
            raise RestError(400, f"Could not connect to Pi-hole: {e}")


if __name__ == '__main__':
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=PiholeAccountHandler,
    )
