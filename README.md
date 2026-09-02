# mtnOS Virtual Gate

A small Raspberry Pi kiosk server that reads newline-terminated USB RFID scanner input, validates each media identifier against mtnOS, and updates the connected browser immediately.

## Configure

Edit `config.toml`:

```toml
mntos-server = "https://your-mtnos-host"
mtnos-username = "your-mtnos-username"
mtnos-password = "your-mtnos-password"
control-device = "192.168.1.50"
logo = "/assets/logo.png"
```

The scanner must operate as a USB keyboard and append Enter after each scan. `mntos-server` is used as the API base URL and `control-device` is sent as `deviceIdentifier`.

## Run

Python 3.11 or newer is required. The server listens on port `8080` by default:

```sh
python3 server.py
```

Open `http://localhost:8080` in Chromium. For a fullscreen kiosk session:

```sh
chromium --kiosk --noerrdialogs --disable-infobars http://localhost:8080
```

The browser receives results over Server-Sent Events. `/health` is available for a service monitor.

Authentication is refreshed automatically every `auth-refresh-hours` (12 by
default). If credentials are missing, login fails, or mtnOS rejects the token,
the gate silently falls back to direct validation.

## Python API client

`mtnos_client.py` provides the captured access-control operations:

```python
from mtnos_client import MtnOSClient

client = MtnOSClient("https://your-mtnos-host")
client.login("username", "password")
medias = client.fetch_client_medias("client-id")
client.set_active_media("client-id", "media-id", current_media_id="current-media-id")
```

Login uses the Keycloak password-grant endpoint captured separately from the
HAR files. Login cookies are retained automatically; `access_token` (or
equivalent token fields) is sent as a Bearer token.

## systemd

Install a unit such as `/etc/systemd/system/mtnos-gate.service`, replacing the working directory and user for the Pi:

```ini
[Unit]
Description=mtnOS virtual gate
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/mtnOS-virtual-gate
ExecStart=/usr/bin/python3 /home/pi/mtnOS-virtual-gate/server.py
Restart=always
RestartSec=3
StandardInput=tty
TTYPath=/dev/ttyUSB0

[Install]
WantedBy=multi-user.target
```

Enable it with `sudo systemctl enable --now mtnos-gate`. If the scanner is configured as a keyboard device rather than a serial/TTY input, run the server in the desktop session so the scanner's keystrokes are directed to its terminal, or adapt the input source to the scanner's device node.