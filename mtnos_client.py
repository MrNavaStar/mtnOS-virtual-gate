"""Small client for the mtnOS access-control API."""

from __future__ import annotations

import http.cookiejar
import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
import time
from collections.abc import Mapping
from typing import Any


LOG = logging.getLogger("virtual-gate.mtnos-client")


class MtnOSClientError(RuntimeError):
    """Raised when an mtnOS request fails or returns an unexpected payload."""


class MtnOSAuthenticationError(MtnOSClientError):
    """Raised when mtnOS rejects the current authentication token."""


class MtnOSClient:
    """Authenticated client for fetching and changing a client's media."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10,
        token_refresh_hours: float = 12,
        context: ssl.SSLContext | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token_refresh_seconds = token_refresh_hours * 60 * 60
        self._cookies = http.cookiejar.CookieJar()
        handlers: list[Any] = [urllib.request.HTTPCookieProcessor(self._cookies)]
        if context is not None:
            handlers.insert(0, urllib.request.HTTPSHandler(context=context))
        self._opener = urllib.request.build_opener(*handlers)
        self._context = context
        self._authorization: str | None = None
        self._logged_in_at: float | None = None
        self._credentials: tuple[str | None, str | None] | None = None

    def configure(
        self,
        base_url: str,
        *,
        timeout: float,
        token_refresh_hours: float,
        context: ssl.SSLContext | None,
        context_key: tuple[object, ...],
        credentials: tuple[str | None, str | None],
    ) -> None:
        """Apply runtime settings and discard authentication when its identity changes."""
        normalized_url = base_url.rstrip("/")
        if (
            normalized_url != self.base_url
            or context_key != getattr(self, "_context_key", None)
            or credentials != self._credentials
        ):
            self.base_url = normalized_url
            self._context = context
            self._context_key = context_key
            handlers: list[Any] = [urllib.request.HTTPCookieProcessor(self._cookies)]
            if context is not None:
                handlers.insert(0, urllib.request.HTTPSHandler(context=context))
            self._opener = urllib.request.build_opener(*handlers)
            self._authorization = None
            self._logged_in_at = None
        self.timeout = timeout
        self.token_refresh_seconds = token_refresh_hours * 60 * 60
        self._credentials = credentials

    @property
    def authenticated(self) -> bool:
        return self._authorization is not None

    def login_if_needed(self, username: str, password: str) -> bool:
        """Refresh the token when it is absent or older than the configured interval."""
        if (
            self._authorization is not None
            and self._logged_in_at is not None
            and time.monotonic() - self._logged_in_at < self.token_refresh_seconds
        ):
            return True
        self.login(username, password)
        return self.authenticated

    def login(
        self,
        username: str,
        password: str,
        *,
        extra_fields: Mapping[str, Any] | None = None,
    ) -> Any:
        """Log in and retain any session cookie returned by mtnOS.

        The login path is configurable for deployments with a different
        Keycloak realm or route.
        """
        payload: dict[str, Any] = {
            "grant_type": "password",
            "client_id": "mtnos-home-app",
            "username": username,
            "password": password,
        }
        if extra_fields:
            payload.update(extra_fields)
        result = self._request(
            "POST",
            "/auth/realms/mtnos/protocol/openid-connect/token",
            form=payload,
        )
        if isinstance(result, Mapping):
            token = result.get("accessToken") or result.get("access_token") or result.get("token")
            if token:
                self._authorization = f"{result.get('token_type', 'Bearer')} {token}"
                self._logged_in_at = time.monotonic()
        return result

    def fetch_client_medias(
        self,
        client_id: str,
        *,
        page: int = 0,
        items_per_page: int = 20,
    ) -> Any:
        """Return the paginated media payload for a client."""
        query = urllib.parse.urlencode({
            "clientId": client_id,
            "page": page,
            "itemsPerPage": items_per_page,
        })
        return self._request(
            "GET",
            f"/api/access-control/v2/medias/paginated?{query}",
        )

    def validate_media(self, device_identifier: str, media_identifier: str) -> Any:
        """Validate a scanned media identifier for a gate device."""
        query = urllib.parse.urlencode({
            "deviceIdentifier": device_identifier,
            "mediaIdentifier": media_identifier,
        })
        return self._request(
            "GET",
            f"/api/access-control/v2/validation/?{query}",
        )

    def set_active_media(
        self,
        client_id: str,
        media_id: str,
        *,
        current_media_id: str | None = None,
    ) -> Any:
        """Set a client's selected media using the recorded replacement API.

        ``media_id`` is the API object's ``id`` field, not its RFID serial
        number. The replacement endpoint requires both serial numbers, so the
        client's media list is used to resolve them.
        """
        medias = self.fetch_client_medias(client_id)
        records = self._media_records(medias)
        target = self._find_media(records, media_id)
        current = self._find_current_media(records, current_media_id, target)
        target_serial = self._media_serial(target)
        current_serial = self._media_serial(current)
        return self._request(
            "POST",
            "/api/access-control/v1/replacement/by-media",
            body={
                "currentMediaSerialNumber": current_serial,
                "replacementMediaSerialNumber": target_serial,
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        form: Mapping[str, Any] | None = None,
    ) -> Any:
        url = urllib.parse.urljoin(f"{self.base_url}/", path.lstrip("/"))
        headers = {"Accept": "application/json"}
        if self._authorization:
            headers["Authorization"] = self._authorization
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        target = urllib.parse.urlsplit(url).path
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                LOG.info("mtnOS HTTP %s %s -> %s", method, target, response.status)
                raw = response.read()
        except urllib.error.HTTPError as error:
            LOG.warning("mtnOS HTTP %s %s -> %s", method, target, error.code)
            if error.code in (401, 403):
                self._authorization = None
                self._logged_in_at = None
                raise MtnOSAuthenticationError(
                    f"{method} {target} rejected authentication with HTTP {error.code}"
                ) from error
            raise MtnOSClientError(
                f"{method} {target} failed with HTTP {error.code}"
            ) from error
        except urllib.error.URLError as error:
            reason = str(error.reason)
            LOG.error("mtnOS HTTP %s %s failed: %s", method, target, reason)
            raise MtnOSClientError(
                f"{method} {target} failed with a network error: {reason}"
            ) from error
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            LOG.error("mtnOS HTTP %s %s returned invalid JSON", method, target)
            raise MtnOSClientError(f"{method} {target} returned invalid JSON") from error

    @staticmethod
    def _media_records(payload: Any) -> list[Mapping[str, Any]]:
        records = payload.get("content") if isinstance(payload, Mapping) else payload
        if not isinstance(records, list) or not all(isinstance(item, Mapping) for item in records):
            raise MtnOSClientError("media response does not contain a content list")
        return records

    @staticmethod
    def _find_media(records: list[Mapping[str, Any]], media_id: str) -> Mapping[str, Any]:
        for record in records:
            if str(record.get("id")) == media_id:
                return record
        raise MtnOSClientError(f"media {media_id!r} was not found")

    @classmethod
    def _find_current_media(
        cls,
        records: list[Mapping[str, Any]],
        current_media_id: str | None,
        target: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if current_media_id is not None:
            return cls._find_media(records, current_media_id)
        for record in records:
            if record is not target and record.get("active") is True:
                return record
        raise MtnOSClientError(
            "current active media could not be identified from the media active field; "
            "pass current_media_id"
        )

    @staticmethod
    def _media_serial(media: Mapping[str, Any]) -> str:
        serial = media.get("serialNumber")
        if not serial:
            raise MtnOSClientError("media record has no serialNumber")
        return str(serial)