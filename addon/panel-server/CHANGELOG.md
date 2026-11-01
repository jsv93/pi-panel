# Changelog

## 0.22.2

- Remove the separate secure diagnostics console, operator login, HTTPS
  listener and additional agent connection introduced in 0.21.0–0.22.1.
- Restore the original panel agent and dashboard behavior. Existing panel
  configuration, enrollment keys and provisioning SSH credentials are preserved.
- Remove the retired management policy, TLS files and audit database from the
  add-on data directory on startup. Normal SSH behavior is unchanged.
