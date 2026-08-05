---
title: Midnight 911
description: Instructions on how to set up the Midnight 911 integration.
ha_category:
  - Safety
  - Alarm
ha_release: 0.4.0
ha_iot_class: Cloud Push
ha_config_flow: true
ha_codeowners:
  - '@midnight-security/midnight-team'
ha_domain: midnight_alerts
ha_platforms:
  - alarm_control_panel
  - button
ha_integration_type: service
---

> **DRAFT — not a Core integration today.** This integration is currently
> distributed only via HACS; see the main [README](../README.md) for how to
> install it. This file is written in the format Home Assistant Core's own
> docs use (front matter, section layout) because it's a working draft of
> the documentation that would be submitted to
> [home-assistant/home-assistant.io](https://github.com/home-assistant/home-assistant.io)
> if and when the integration moves into Home Assistant Core - see
> [`CORE_INTEGRATION.md`](../CORE_INTEGRATION.md) for that roadmap. Front
> matter fields (`ha_release`, etc.) will need updating at submission time
> to match whatever's actually true then.

The **Midnight 911** integration connects Home Assistant to
[Midnight Security](https://www.midnight.security), a professional security
monitoring service, in two complementary ways:

- A **Trigger Alert** button (and the `button.press` action) that sends an
  alert straight to Midnight's US-based monitoring center.
- **Midnight Alarm**, a native `alarm_control_panel` platform — a full
  arm/disarm system with PIN-protected users, entry/exit delay, sensor
  groups, and a one-time import wizard for households moving off the
  third-party **Alarmo** integration.

Midnight works in partnership with [RapidSOS](https://www.rapidsos.com) to
validate alerts and reach the 911 center associated with your address,
contacting local emergency services on your behalf if the alert is
validated or goes without a response from you. Wire an alarm area's
triggered state, or the button, into an automation that calls Midnight and
you get monitored dispatch on top of hardware you already own.

<div class='note warning'>

This integration can result in a real dispatch to emergency services.
Configure and test it carefully, and always keep your monitored address
up to date.

</div>

## Use cases

- **Escalate a sensor to a monitored alert.** Wire the **Trigger Alert**
  button into an automation instead of pressing it directly — for example,
  triggering it when a glass-break or smoke sensor fires and nobody
  dismisses the automation's confirmation prompt within a couple of
  minutes.
- **Run a full alarm system.** Add one or more **areas**, each with its own
  arm-away/home/night/vacation modes, exit/entry delay, and PIN-protected
  users — the same day-to-day experience as a physical alarm panel, using
  sensors you've already got in Home Assistant.
- **Move off Alarmo.** If you're already running the third-party Alarmo
  integration, **Import from Alarmo** carries your areas, users (PINs keep
  working immediately — no re-entry), and sensor groups straight over.

## Prerequisites

1. Sign up for a [Midnight Security](https://www.midnight.security) account.
2. Enter your home address on the Midnight Security dashboard and generate
   an API key — the address you enter there, not anything typed into Home
   Assistant, is what a real dispatch is sent to.
3. Make sure Home Assistant has an active internet connection — it must be
   able to reach Midnight's API for both setup and alert delivery.

{% include integrations/config_flow.md %}

## Configuration

During setup you'll be asked for:

| Field | Description |
| --- | --- |
| API Key | The API key from your Midnight Security account. **Optional** - leave it blank to set up the alarm system (areas, sensors, PINs, arming/disarming) without dispatching to Midnight yet. Everything works locally either way; only the **Trigger Alert** button needs a key, and it logs a clear error instead of doing anything if pressed without one. Leaving it blank raises a Repair (Settings → System → Repairs) prompting you to add one when you're ready - confirming it opens the same "Reauthenticate" prompt used for a rejected key, and the issue clears itself once a working key is saved. |
| Send crash reports to Midnight Security | Off by default. Helps diagnose bugs faster - only the error type and message are sent, never your address, API key, or alert data. Changeable anytime from Reconfigure; reauthenticating a rejected key leaves it untouched. |

If you do provide a key, setup also verifies that Home Assistant's own
configured location (Settings → System → General) is within 1000 feet of
the address on file for it, and blocks completing setup if they don't
match closely enough — this catches a key pasted into the wrong Home
Assistant instance, or a stale `hass.config` location, before it could
send a real emergency dispatch to the wrong place. This same check runs
again every time the integration loads (e.g. after a restart); if Home
Assistant's location drifts out of sync afterward, it's surfaced as a
Repair (Settings → System → Repairs) rather than breaking the integration
outright. None of this runs at all if the key is left blank - there's
nothing to validate yet.

Left the key blank, or want to change either field later? Settings →
Devices & services → Midnight 911 → **Reconfigure** opens the same form
again, pre-filled with your current key (if any) and crash-reporting
choice, and goes through the same location check if you provide a key.
This is the one place to revisit either setting after initial setup -
there's no separate Configure/options screen duplicating it.

If a *stored* API key stops validating (revoked, rotated, etc.), Home
Assistant automatically prompts for a new one - via a "Reauthenticate"
notification on the integration's card, no need to remove and re-add it.
The new key goes through the same location check described above.

This creates the **Midnight 911** hub and the **Trigger Alert** button.
Everything below is optional, added afterward from the hub's own **Add**
menu (Settings → Devices & services → Midnight 911 → Add), and takes effect
immediately with no restart required.

### Adding an alarm area

Add → **Area**. An area is one arm/disarm partition (most households only
need one, named e.g. "Home").

| Field | Description |
| --- | --- |
| Name | Shown as the area's device name and entity name. |
| Arm modes | Which of Away / Home / Night / Vacation / Custom bypass this area supports. |

The area is created with default timers (60s exit delay, 60s entry delay,
30-minute trigger duration once set off). To change them per mode, open the
area's device, choose **Reconfigure → Edit name and timers**.

### Attaching sensors to an area

From the area's **Reconfigure → Manage sensors** step, pick any
`binary_sensor` entities that should feed this area. These options apply to
sensors newly picked in that same step (already-attached sensors keep
whatever they were given — see [Known limitations](#known-limitations)):

| Field | Description |
| --- | --- |
| Sensors | The `binary_sensor` entities to attach or detach. |
| Hold arming open until closed | If still open when the exit delay ends, wait for it to close instead of finishing arming with it open. |
| Debounce (seconds) | The sensor must stay open this long before it counts as a real trip, filtering a momentary blip. `0` disables debouncing. |
| Always on | This sensor triggers the alarm regardless of arm state, even while disarmed - for a smoke/water sensor that should always be monitored. |
| Entry delay override (seconds) | Overrides the area mode's own entry delay for just this sensor. Leave blank to use the area's default. |
| Arm modes | Restrict this sensor to only trigger while armed in specific modes. Leave blank for no restriction (triggers in any mode the area is armed in). |

A sensor attached to an area triggers the alarm (after that mode's entry
delay) whenever it opens while the area is armed in a mode that mode's
membership allows.

### Adding users and PINs

Add → **User**. No PIN is required to arm or disarm until at least one user
exists — after that, every arm/disarm action needs a matching code.

| Field | Description |
| --- | --- |
| Name | For your own reference. |
| PIN code | Leave blank for a user who can arm/disarm without entering a code. |
| Can arm / Can disarm | Which actions this user's code is allowed to perform. |
| Override code | When arming with this code, open sensors are bypassed (no holding for `arm_on_close`, no aborting on `use_exit_delay`) instead of blocking the arm. |
| Enabled | A disabled user's code stops working without deleting them. |
| Areas | Restrict this user's code to specific areas. Leave blank for no restriction (works in every area). |

### Sensor groups (N-of-M confirmation)

Add → **Sensor group**. Requires a configurable number of member sensors to
trip within a time window before it counts as one confirmed event — useful
for filtering a single pet-triggered motion sensor out of a multi-sensor
room.

| Field | Description |
| --- | --- |
| Member sensors | The sensors this group cross-checks. |
| Confirmation window (seconds) | How far apart member trips can be and still count together. |
| Sensors required to confirm | How many members must trip within the window. |
| Confirmation mode | **Count window** (the default, above) or **Weighted decay** (below). |

Grouping a sensor here doesn't attach it to an area — each member also
needs to be individually attached via that area's **Manage sensors** step,
same as any other sensor.

#### Weighted/decaying confirmation

Pick **Weighted decay** as the confirmation mode for a second step where
each member gets its own weight instead of every sensor counting equally.
A trip adds that sensor's weight to a running score; the score decays over
time; the group confirms once the score crosses a threshold. This suits a
mix of sensors with different reliability - e.g. a window sensor weighted
higher than a pet-prone motion sensor - where a strict N-of-M count either
under- or over-reacts.

| Field | Description |
| --- | --- |
| Per-member weight | How much one trip from this sensor adds to the group's score. |
| Decay per minute | How much the score drops per minute since the last trip. |
| Threshold | The score needed to confirm - crossing it counts as one confirmed event. |

The score isn't persisted across a Home Assistant restart, the same as the
count-window mode's tally - both start fresh after a restart.

### Importing from Alarmo

Add → **Import from Alarmo**, available whenever Alarmo's own storage file
is found on this Home Assistant instance. It shows a preview (areas, users,
sensor groups, sensors, and automations found) before you confirm.

- PINs carry over in their original hashed form and keep working
  immediately — no re-entry.
- Automations are **never** imported (Alarmo's own automation engine is
  exactly what this integration avoids) — only counted, so you know how
  many to recreate as ordinary Home Assistant automations.
- Sensors that don't exist as entities in this Home Assistant instance are
  skipped and reported by count, not silently dropped.
- Running the import again is a safe no-op — nothing already imported gets
  duplicated.

## Supported functions

| Entity | Type | Description |
| --- | --- | --- |
| Trigger Alert | Button | Sends an alert to Midnight's monitoring center for the address on your account. |
| *(area name)* | Alarm Control Panel | One per configured area. Supports arm away/home/night/vacation/custom bypass (per what's enabled on that area), disarm, and manual trigger, each optionally requiring a user's PIN. |

## Data updates

This integration is push-only (`cloud_push`) — nothing is polled on a
schedule. The button sends a single request to Midnight's API at the
moment it's pressed. Alarm area entities are fully event-driven: state
changes are written the moment a sensor trips or a timer elapses, never on
an interval.

## Examples

A typical automation triggers the alert button when a security-relevant
sensor fires without being acknowledged, for example:

```yaml
automation:
  - alias: "Escalate unacknowledged glass break to Midnight"
    trigger:
      - trigger: state
        entity_id: binary_sensor.living_room_glass_break
        to: "on"
    condition:
      - condition: state
        entity_id: input_boolean.alert_acknowledged
        state: "off"
    action:
      - delay: "00:02:00"
      - condition: state
        entity_id: input_boolean.alert_acknowledged
        state: "off"
      - action: button.press
        target:
          entity_id: button.midnight_911_trigger_alert
```

An alarm area is a normal `alarm_control_panel` entity, so it works with
any automation that domain supports — for example, escalating to Midnight
once an area has been sitting in `triggered` for a while:

```yaml
automation:
  - alias: "Escalate an unresolved Midnight Alarm trigger"
    trigger:
      - trigger: state
        entity_id: alarm_control_panel.home
        to: "triggered"
        for: "00:01:00"
    action:
      - action: button.press
        target:
          entity_id: button.midnight_911_trigger_alert
```

<div class='note'>

The YAML above is a starting point to hand-adapt. For a ready-made version
of each with no copy-pasting required, see the bundled blueprints below -
including one that generalizes the second example to work with any
alarm_control_panel entity, Alarmo included.

</div>

### Ready-made blueprints

This repo bundles six blueprints under
[`blueprints/automation/midnight_alerts/`](https://github.com/midnight-security/midnight-homeassistant-911/tree/master/blueprints/automation/midnight_alerts) —
the direct replacement for Alarmo's own built-in "notification," "device
switching," and "automatic arming" automation features, as real, editable
Home Assistant automations instead of rules stored inside the
integration:

| Blueprint | What it does |
| --- | --- |
| [Notify on Trigger](https://github.com/midnight-security/midnight-homeassistant-911/blob/master/blueprints/automation/midnight_alerts/notify_on_trigger.yaml) | Runs any action you choose (a notification, a script, turning on a siren or lights - anything) the moment an area enters `triggered`. |
| [Notify on State Change](https://github.com/midnight-security/midnight-homeassistant-911/blob/master/blueprints/automation/midnight_alerts/notify_on_state_change.yaml) | The broader version of the above - pick any set of states (armed, disarmed, triggered, etc.) to run an action on, with `trigger.to_state.attributes.changed_by` available for templating (the equivalent of Alarmo's `{{changed_by}}` wildcard). |
| [Re-arm After Timeout](https://github.com/midnight-security/midnight-homeassistant-911/blob/master/blueprints/automation/midnight_alerts/rearm_after_timeout.yaml) | Automatically re-arms an area into a mode you choose if it's left disarmed longer than a configurable timeout. |
| [Auto-Arm Away When Everyone Leaves](https://github.com/midnight-security/midnight-homeassistant-911/blob/master/blueprints/automation/midnight_alerts/auto_arm_away_when_everyone_leaves.yaml) | Arms an area away once every tracked `person` entity has left home. Alarmo's own docs say this specific recipe needs a hand-written automation too - this is that automation, ready to use. |
| [Retry Arm on Failed Arm](https://github.com/midnight-security/midnight-homeassistant-911/blob/master/blueprints/automation/midnight_alerts/retry_arm_on_failed_to_arm.yaml) | Sends an actionable notification with a "Retry Arm" button whenever a sensor without exit delay blocks arming - the equivalent of Alarmo's actionable "failed to arm" push notification. |
| [Dispatch on Trigger](https://github.com/midnight-security/midnight-homeassistant-911/blob/master/blueprints/automation/midnight_alerts/dispatch_on_trigger.yaml) | Presses the Trigger Alert button once **any** alarm_control_panel entity - not just a Midnight Alarm area - has stayed `triggered` for a grace period you set. Point it at an Alarmo area to let Alarmo drive Midnight's real 911 dispatch while you keep using Alarmo's own UI for the alarm itself. |

To use one: **Settings → Automations & Scenes → Blueprints → Import
Blueprint**, paste that blueprint's GitHub link above, then create an
automation from it like any other blueprint - pick the area (and whatever
else the blueprint asks for) from the dropdowns.

"Retry Arm on Failed Arm" listens for `midnight_alerts_arm_failed`, an event this
integration fires whenever a sensor configured without exit delay opens
mid-arming and aborts it - the equivalent of Alarmo's own
`alarmo_failed_to_arm` event. Its data includes `entity_id` (the area),
`sensor` (what caused the abort), and `mode` (what was being armed into),
if you'd rather build your own automation around it than use the
blueprint.

These aren't yet published to the official community blueprint exchange
(forum.home-assistant.io) - importing directly by the GitHub link above
works today without waiting on that.

## Troubleshooting

### Can't set up the integration

#### Symptom: "Invalid API key"

The config flow shows an `invalid_auth` error.

##### Resolution

Double-check the API key was copied in full from your Midnight Security
account, with no extra whitespace. If it still fails, generate a new key
and try again.

#### Symptom: "Failed to connect to Midnight Alerts"

The config flow shows a `cannot_connect` error.

##### Resolution

1. Confirm Home Assistant has an active internet connection.
2. Check [Midnight Security's status](https://www.midnight.security) for
   any ongoing service disruption.
3. Try again after a few minutes.

#### Symptom: "This Home Assistant instance's configured location..." (`location_mismatch`)

Home Assistant's own configured location (Settings → System → General) is
more than 1000 feet from the address on file for the API key being used.

##### Resolution

1. If Home Assistant's configured location is wrong (e.g. it was set up
   with default/placeholder coordinates), fix it under Settings → System →
   General, then retry.
2. If Home Assistant's location is actually correct, the address on file
   for this API key is wrong or belongs to a different location - update it
   on your midnight.security account, then retry.
3. If this error appears later as a Repair (Settings → System → Repairs)
   rather than during setup, it means the two were in sync at setup time but
   have since drifted - the integration keeps working, but won't be
   accurately located until this is resolved.

#### Symptom: "No address is on file for this API key yet" (`no_account_location`)

##### Resolution

Finish the address/location step on your midnight.security account
dashboard for this API key, then retry setup.

### Pressing the button doesn't seem to do anything

Check the Home Assistant logs for `custom_components.midnight_alerts` — a
failed alert logs an error there rather than surfacing a UI notification.
This is almost always the same connectivity or account issue as above,
just happening at alert time instead of setup time.

### A PIN is rejected when arming or disarming

Check the user's **Enabled**, **Can arm**, and **Can disarm** fields — a
disabled user's code stops matching entirely, and a code that doesn't have
permission for the action you're attempting is rejected rather than
silently ignored.

### A sensor doesn't trigger the alarm

1. Confirm it's actually attached to the area via that area's **Manage
   sensors** step — attaching it to a sensor group alone isn't enough.
2. If it's in a sensor group, confirm enough other members tripped inside
   the group's confirmation window — a single sensor in a group never
   triggers the alarm on its own.
3. If it has a debounce value set, confirm it stayed open at least that
   long.

### "Import from Alarmo" isn't offered, or aborts immediately

- **Not offered / "No Alarmo storage file was found"** — Alarmo isn't
  installed on this Home Assistant instance, or hasn't been set up yet.
- **"a version this importer doesn't understand"** — open Alarmo itself
  once first and let it finish its own migration, then retry the import.

## Removing the integration

This integration follows standard integration removal. Removing an
individual area, user, sensor group, or the whole integration cleans up
its device(s) automatically — nothing is left behind to remove by hand.
After removing the whole integration, no further alerts can be sent by
Home Assistant, and no areas can be armed, until it's re-added.

{% include integrations/remove_device_service.md %}

Removing the integration from Home Assistant does not cancel your Midnight
Security account or monitoring plan — manage or cancel that separately at
[midnight.security](https://www.midnight.security).

## Availability

- **United States** only today, with Canada planned.
- Requires an active internet connection at the time an alert is triggered
  (arming, disarming, and sensor-driven triggering within Home Assistant
  itself work fully offline — only *forwarding* an alert to Midnight needs
  connectivity).

## Known limitations

- No automatic re-delivery or retry queue on temporary connectivity loss —
  a failed alert must be triggered again once connectivity is restored.
- Only a single Midnight Security account (config entry) is supported per
  Home Assistant instance.
- Alarmo automations are never imported, only counted — recreate the ones
  you still need as ordinary Home Assistant automations.
- A sensor with its entry delay turned off entirely (triggers instantly,
  regardless of the area mode's own entry delay) is fully functional but
  currently only settable via **Import from Alarmo** - there's no manual
  UI field for it yet.
- The **Manage sensors** step's "hold arming open until closed" and
  "debounce" options only apply to sensors newly attached in that same
  submission — changing them for an already-attached sensor means
  detaching and re-attaching it.
