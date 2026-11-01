# Save power while asleep

Panel Server → panel → Display → **Save power while asleep**. Enable the setting
and save the screen settings (or Save & push). It is off by default. A non-zero
Blank after time is required; a visible dimmed clock keeps normal performance.

While fully blanked, the agent temporarily lowers policy0's CPU maximum to the
current minimum supported by its Linux policy. On the tested CM5 that is 1.5 GHz.
Touch, presence wake, identify, reload and a doorbell restore the previous maximum
(normally 2.4 GHz on CM5). The governor, minimum frequency, voltage and firmware
configuration are unchanged. An administrator's existing lower maximum is preserved.

The setting uses the existing authenticated display configuration. The browser
reports screen transitions immediately through its local agent connection; it
cannot supply CPU limits or filesystem paths. Every connected browser page must
have reported blanked within 25 seconds. Disconnect restores performance immediately;
stale heartbeats restore within approximately 27 seconds. This works without the
configuration server or Home Assistant. Lighting, Bluetooth, HA updates and the
five-second performance sampler continue normally.

A root-owned `/run/pi-panel-idle-power.json` records the previous ceiling before
it changes. Normal shutdown and agent updates restore it; after an abrupt crash,
the service restart restores it before accepting new screen state. A reboot resets
the kernel limit and clears `/run`. If the agent is forcibly killed and its automatic
restart is also disabled, the lower ceiling can remain until the agent starts again
or the device reboots. A ceiling changed externally is not overwritten by cleanup.

The Display page and on-demand screen diagnostics report the agent's power-saving
status. Older agents report no status; devices without accessible CPU policy
controls report that the feature is unavailable and keep running.

This reduces idle frequency boosts, not the CM5's minimum CPU frequency or every
source of board heat. Temperature savings depend on workload, enclosure and cooling;
do not assume a fixed reduction. Wake performance and doorbell streaming must be
verified when changing supported hardware.
