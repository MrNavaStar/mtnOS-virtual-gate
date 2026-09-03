#!/usr/bin/env python3
"""mtnOS virtual gate kiosk server."""

from __future__ import annotations

import json
import logging
import queue
import ssl
import sys
import threading
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tomllib

from mtnos_client import MtnOSAuthenticationError, MtnOSClient, MtnOSClientError

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.toml"
STATIC_DIR = ROOT / "web"
LOG = logging.getLogger("virtual-gate")


def ssl_context_from_config(config: dict) -> ssl.SSLContext | None:
    """Build an SSL context that honors a self-signed certificate when configured."""
    ca_file = config.get("tls-ca-file")
    if ca_file:
        return ssl.create_default_context(cafile=str(ca_file))
    if config.get("tls-verify", True) is False:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    return None


def load_config() -> dict:
    with CONFIG_PATH.open("rb") as config_file:
        config = tomllib.load(config_file)
    required = ("mtnos-server", "control-device")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"Missing config values: {', '.join(missing)}")
    return config


class State:
    def __init__(self) -> None:
        self._clients: set[queue.Queue[dict]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[dict]:
        client: queue.Queue[dict] = queue.Queue()
        with self._lock:
            self._clients.add(client)
        return client

    def unsubscribe(self, client: queue.Queue[dict]) -> None:
        with self._lock:
            self._clients.discard(client)

    def publish(self, payload: dict) -> None:
        with self._lock:
            clients = tuple(self._clients)
        for client in clients:
            client.put(payload)


def normalize_media_identifier(raw_value: str) -> str:
    """Normalize scanner input before sending it to mtnOS."""
    normalized = raw_value.strip()
    while normalized.startswith(";"):
        normalized = normalized[1:].lstrip()
    return normalized


def client_id_from_photo_url(photo_url: str | None) -> str | None:
    if not photo_url:
        return None
    path_parts = urllib.parse.urlparse(photo_url).path.strip("/").split("/")
    try:
        contact_index = path_parts.index("contact")
    except ValueError:
        return None
    return path_parts[contact_index + 1] if contact_index + 1 < len(path_parts) else None


def validate_media(media_identifier: str, config: dict) -> dict:
    """Validate without authentication, preserving the original gate behavior."""
    LOG.info("Starting direct media validation for %s", media_identifier)
    query = urllib.parse.urlencode({
        "deviceIdentifier": config["control-device"],
        "mediaIdentifier": media_identifier,
    })
    url = f"{config['mtnos-server'].rstrip('/')}/api/access-control/v2/validation/?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    timeout = float(config.get("request-timeout-seconds", 10))
    context = ssl_context_from_config(config)
    opener = (
        urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
        if context is not None
        else urllib.request.build_opener()
    )
    with opener.open(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
        LOG.info("Direct media validation succeeded for %s: validationCode=%s", media_identifier, result.get("validationCode"))
        return result


def validate_scanned_media(
    media_identifier: str,
    config: dict,
    client: MtnOSClient,
    *,
    use_authentication: bool,
) -> dict:
    if not use_authentication:
        LOG.info("Validating %s without mtnOS authentication", media_identifier)
        return validate_media(media_identifier, config)
    try:
        LOG.info("Validating %s with mtnOS authentication", media_identifier)
        result = client.validate_media(config["control-device"], media_identifier)
    except MtnOSAuthenticationError:
        LOG.warning("mtnOS authentication was rejected; using direct validation")
        return validate_media(media_identifier, config)
    if result.get("validationCode") != "MEDIA_INACTIVE":
        LOG.info("Authenticated validation completed for %s: validationCode=%s", media_identifier, result.get("validationCode"))
        return result

    LOG.info("Media %s is inactive; attempting activation", media_identifier)

    client_id = client_id_from_photo_url(result.get("clientPhotoUrl"))
    media_id = result.get("mediaId")
    if not client_id or not media_id:
        LOG.warning("Inactive media response has no client or media ID")
        return result

    try:
        client.set_active_media(client_id, str(media_id))
        LOG.info("Media activation request succeeded for %s; validating again", media_identifier)
        result = client.validate_media(config["control-device"], media_identifier)
        LOG.info("Post-activation validation completed for %s: validationCode=%s", media_identifier, result.get("validationCode"))
        return result
    except MtnOSAuthenticationError:
        LOG.warning("mtnOS authentication expired during activation; using direct validation")
        return validate_media(media_identifier, config)
    except MtnOSClientError:
        LOG.exception("Could not silently activate inactive media %s", media_identifier)
        return result


def scan_loop(
    config: dict,
    state: State,
    client: MtnOSClient,
    username: str | None,
    password: str | None,
) -> None:
    for raw_value in sys.stdin:
        media_identifier = normalize_media_identifier(raw_value)
        if not media_identifier:
            continue
        LOG.info("Validating scanned media identifier %s", media_identifier)
        state.publish({"type": "scanning", "mediaIdentifier": media_identifier})
        try:
            use_authentication = False
            if username and password:
                try:
                    use_authentication = client.login_if_needed(username, password)
                    LOG.info("mtnOS authentication is available for scan: %s", use_authentication)
                except MtnOSClientError:
                    LOG.warning("mtnOS login failed; using direct validation", exc_info=True)
            result = validate_scanned_media(
                media_identifier,
                config,
                client,
                use_authentication=use_authentication,
            )
            state.publish({"type": "validation", "result": result})
        except Exception as error:
            LOG.exception("Validation request failed")
            state.publish({"type": "error", "message": str(error), "mediaIdentifier": media_identifier})


class Handler(BaseHTTPRequestHandler):
    state: State
    config: dict

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/events":
            self.send_events()
        elif path == "/config":
            self.send_json({"controlDevice": self.config["control-device"], "logo": self.config.get("logo", "")})
        elif path == "/health":
            self.send_json({"status": "ok"})
        else:
            self.send_static(path)

    def send_events(self) -> None:
        client = self.state.subscribe()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    payload = client.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.state.unsubscribe(client)

    def send_static(self, path: str) -> None:
        relative_path = "index.html" if path == "/" else path.removeprefix("/")
        file_path = (STATIC_DIR / relative_path).resolve()
        if STATIC_DIR not in file_path.parents or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}.get(file_path.suffix, "application/octet-stream")
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = MtnOSClient(
        config["mntos-server"],
        timeout=float(config.get("request-timeout-seconds", 10)),
        token_refresh_hours=float(config.get("auth-refresh-hours", 12)),
        context=ssl_context_from_config(config),
    )
    username = config.get("mtnos-username")
    password = config.get("mtnos-password")
    if username and password:
        LOG.info("mtnOS credentials configured; attempting initial login")
        try:
            authenticated = client.login_if_needed(username, password)
            LOG.info("Initial mtnOS login completed; authenticated=%s", authenticated)
        except MtnOSClientError:
            LOG.warning("Initial mtnOS login failed; using direct validation", exc_info=True)
    else:
        LOG.warning("mtnOS credentials are not configured; using direct validation")
    state = State()
    Handler.state = state
    Handler.config = config
    threading.Thread(
        target=scan_loop,
        args=(config, state, client, username, password),
        daemon=True,
    ).start()
    address = (config.get("listen-host", "0.0.0.0"), int(config.get("listen-port", 8080)))
    server = ThreadingHTTPServer(address, Handler)
    LOG.info("Kiosk server listening on http://%s:%s", *address)
    server.serve_forever()


if __name__ == "__main__":
    main()
