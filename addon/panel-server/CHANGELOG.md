# Changelog

## 0.22.0

- Make secure diagnostics configurable in Home Assistant, with a private native
  HTTPS listener, named account, explicit device permissions and audit storage.
- Open the diagnostics link in a new tab at its configured HTTPS address.
- Add a separate outbound agent WSS channel with signed certificate discovery,
  exact certificate pinning and signing-key challenge authentication.
- Retain fixed read-only health checks, expiring sessions and the working kiosk.
  No interactive shell is exposed. Add a real TLS and agent-loop test to CI.

## 0.21.0

- Add an opt-in secure diagnostics console with named operators, role and
  device permissions, HTTPS/WSS requirements, audit records and expiring sessions.
- Reuse the existing agent's signed health diagnostic request. No shell,
  screenshots, agent update or kiosk change is introduced.
- Keep diagnostics disabled until the management policy and TLS are configured.
  Installing the update preserves existing dashboard and Home Assistant access.
- Gate release image builds on management security and dashboard regression tests.

See the main repository's `docs/SECURE-MANAGEMENT.md` for setup and limitations.
