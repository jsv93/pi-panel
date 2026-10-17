# Bluetooth proxy source

`bt-proxy-3929ecb.tar.gz` is the unmodified source archive from
[denvera/bt-proxy](https://github.com/denvera/bt-proxy), commit
`3929ecb5c684069545281d4043a4c39d9cfad0e9`, package version 1.0.3.
The upstream `pyproject.toml` declares the MIT license. The archive retains
upstream metadata, README, authorship and source comments.

SHA-256: `dbd8adb622cff8ae089d3a7948ad3aa053f2434a7a994ed308d70d19d62d9c35`.

The provisioning installer verifies this hash before extraction, adds an
HA/loopback peer allowlist and removes GATT capability flags. The systemd unit
uses zero GATT slots. No upstream source is fetched at runtime; pinned Python
dependencies are installed from PyPI. This is a Linux ESPHome-compatible API
service, not ESPHome firmware. Its API is plaintext and restricted to the HA
host resolved from the panel's configured LAN HA URL.
