"""
Shared Pi-hole (FTL v6+) REST API client.

Pi-hole uses session-based authentication, not a static API key:
  1. POST /api/auth with {"password": "..."} -> {"session": {"sid": ..., "csrf": ..., "validity": ...}}
  2. Send the sid back as the X-FTL-SID header on every subsequent call.
  3. DELETE /api/auth to log out (sessions are capped concurrently and time out on
     inactivity, so callers should log in, do their work, and log out promptly rather
     than holding a session open indefinitely).

Docs: https://docs.pi-hole.net/api/auth/ (each Pi-hole also self-hosts exact-version
docs at http://<host>/api/docs).
"""

import time

import requests


class PiholeAuthError(Exception):
    """Raised when login fails (bad password) or a session cannot be established."""


class PiholeApiError(Exception):
    """Raised for non-auth HTTP/API failures after retries are exhausted."""


class PiholeClient:
    def __init__(self, base_url, password, verify_tls=True, proxies=None,
                 timeout=30, logger=None):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.verify_tls = verify_tls
        self.proxies = proxies
        self.timeout = timeout
        self.log = logger
        self.session = requests.Session()
        self.sid = None
        self.csrf = None

    # -- context manager: guarantees logout even on error ------------------
    def __enter__(self):
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logout()
        return False

    # -- auth ----------------------------------------------------------------
    def login(self):
        url = f"{self.base_url}/api/auth"
        try:
            r = self.session.post(
                url, json={"password": self.password},
                proxies=self.proxies, timeout=self.timeout, verify=self.verify_tls,
            )
        except requests.RequestException as e:
            raise PiholeAuthError(f"could not reach Pi-hole at {self.base_url}: {e}")

        if r.status_code == 401:
            raise PiholeAuthError("Pi-hole rejected the configured password")
        if not r.ok:
            raise PiholeAuthError(f"login failed: HTTP {r.status_code} {r.text[:200]}")

        try:
            payload = r.json()
            session = payload["session"]
        except (ValueError, KeyError) as e:
            raise PiholeAuthError(f"unexpected login response shape: {e}")

        if not session.get("valid"):
            raise PiholeAuthError("Pi-hole reported the session as invalid (2FA/TOTP required?)")

        self.sid = session["sid"]
        self.csrf = session.get("csrf")
        if self.log:
            self.log.debug("pihole login ok, session validity=%ss", session.get("validity"))
        return session

    def logout(self):
        if not self.sid:
            return
        url = f"{self.base_url}/api/auth"
        try:
            self.session.delete(
                url, headers={"X-FTL-SID": self.sid},
                proxies=self.proxies, timeout=self.timeout, verify=self.verify_tls,
            )
        except requests.RequestException as e:
            if self.log:
                self.log.warning("pihole logout call failed (session will expire on its own): %s", e)
        finally:
            self.sid = None
            self.csrf = None

    # -- requests --------------------------------------------------------------
    def get(self, path, params=None, max_retries=5, _retried_auth=False):
        if not self.sid:
            self.login()
        url = f"{self.base_url}{path}"
        headers = {"X-FTL-SID": self.sid}

        for attempt in range(max_retries):
            try:
                r = self.session.get(
                    url, params=params, headers=headers,
                    proxies=self.proxies, timeout=self.timeout, verify=self.verify_tls,
                )
            except requests.RequestException as e:
                if self.log:
                    self.log.warning("attempt=%d transient error calling %s: %s", attempt, path, e)
                time.sleep(min(2 ** attempt, 60))
                continue

            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", min(2 ** attempt, 60)))
                if self.log:
                    self.log.warning("429 rate limited on %s, sleeping %ss", path, wait)
                time.sleep(wait)
                continue

            if r.status_code == 401:
                if _retried_auth:
                    raise PiholeAuthError(f"session expired/rejected on {path} even after re-login")
                if self.log:
                    self.log.info("session expired, re-authenticating")
                self.sid = None
                self.login()
                return self.get(path, params=params, max_retries=max_retries, _retried_auth=True)

            if not r.ok:
                raise PiholeApiError(f"GET {path} failed: HTTP {r.status_code} {r.text[:300]}")

            try:
                return r.json()
            except ValueError as e:
                raise PiholeApiError(f"GET {path} returned non-JSON body: {e}")

        raise PiholeApiError(f"giving up on {path} after {max_retries} attempts")
