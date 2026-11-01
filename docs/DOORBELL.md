# Doorbell camera

Open a panel in Panel Server, select **Doorbell**, choose a camera and enable
the popup. Save & push, wait for the panel to reconnect, then use **Test doorbell**.
This uses the saved camera and duration. The selected camera must support
Home Assistant's native WebRTC API; still-image, map and HLS-only cameras show
an explicit unsupported message. No snapshot is presented as live video.

The panel wakes, opens muted live video, then disconnects on Close, timeout,
sleep, page hiding, reload or connection failure. It does not request a microphone.
Repeated rings extend the same view, capped at five minutes total. No camera
connection remains active between rings. Existing lighting and media configuration
is untouched. Other panel controls resume when the popup closes.

## A real ring

Choose a ring trigger in the server: a binary sensor rings only on off → on;
an event entity or input button rings on a new timestamp. Initial state load,
attribute-only updates and recovery from unavailable do not ring the panel.
For event entities that also report other events, use an HA automation with an
appropriate event-type condition instead of selecting the entity directly.

Alternatively, any Home Assistant automation can use a **Fire event** action:

```yaml
actions:
  - event: pi_panel_doorbell
    event_data:
      panel_id: study-7543  # Replace with the ID shown on your Doorbell page.
```

Each recipient needs an explicit panel ID. Cameras and durations are taken from
that panel's cached server configuration, never from the event payload. The panel
subscribes using its existing authenticated HA WebSocket, so HA must be reachable
and its configured account must have camera access. Normal offline room control
does not depend on this feature. Rings are transient, not queued for later replay.

## Security and load testing

The server test endpoint requires an administrator session, a non-simple CSRF
header, an enabled saved camera and an online panel. It limits repeat requests
and audits successful submissions; “sent” confirms HA accepted the event, not
that a frame reached the screen. HA performs camera authorization and signaling.
No raw camera address, extra shell, public listener or camera credential is added.
Use HTTPS for remote server/HA access; this feature retains the existing transport
configuration and does not claim to encrypt an existing HTTP LAN deployment.

Compare Diagnostics → Live before, during and after a ring: CPU, RAM, temperature
and network traffic. A short test establishes playback load and cleanup, not
thermal equilibrium. Video resolution and frame rate depend on the selected camera.
