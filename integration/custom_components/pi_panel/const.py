"""Shared constants for the Pi Panel integration."""

DOMAIN = "pi_panel"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_PASSWORD = "password"

DEFAULT_PORT = 8099

# Panels heartbeat every 30s, so polling faster only reports the same numbers
# again. The server's own online/offline threshold is 90s.
SCAN_INTERVAL_S = 30

# Marks a request as coming from Home Assistant rather than the server's own
# GUI. The server refuses config writes from whichever side does not own the
# config; this is how it tells them apart. Not a credential -- both sides are
# already authenticated -- it is what makes "config happens in exactly one
# place" enforced rather than merely intended.
CLIENT_HEADER = "X-Panel-Client"
CLIENT_NAME = "homeassistant"

OWNER_SERVER = "server"
OWNER_HA = "homeassistant"
