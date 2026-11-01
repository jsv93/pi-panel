# Changelog

## 0.21.0

- Add an opt-in secure diagnostics console with named operators, role and
  device permissions, HTTPS/WSS requirements, audit records and expiring sessions.
- Reuse the existing agent's signed health diagnostic request. No shell,
  screenshots, agent update or kiosk change is introduced.
- Keep diagnostics disabled until the management policy and TLS are configured.
  Installing the update preserves existing dashboard and Home Assistant access.
- Gate release image builds on management security and dashboard regression tests.

See the main repository's `docs/SECURE-MANAGEMENT.md` for setup and limitations.
