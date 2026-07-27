# Third-Party Notices

This project vendors source code from other open-source projects. Each is
listed below along with its license and provenance, per the attribution
requirements of the licenses involved.

---

## Alarmo

- **Source:** https://github.com/nielsfaber/alarmo
- **Copyright:** © nielsfaber and Alarmo contributors
- **License:** Apache License, Version 2.0 (same license as this project — see [LICENSE](LICENSE))
- **Original version vendored:** tag [`v1.10.18`](https://github.com/nielsfaber/alarmo/releases/tag/v1.10.18), commit `b06a42c3f84ddd04833b0bbc088ec873728511cd`
- **Unmodified reference copy:** [`custom_components/midnight_alerts/vendor/alarmo/`](custom_components/midnight_alerts/vendor/alarmo/) — kept as a pristine snapshot of the upstream release, used only as a reference point for diffing against future Alarmo updates. It is **not** loaded at runtime.
- **Runtime location (modified):** the alarm panel now runs as part of the `midnight_alerts` integration itself, at [`custom_components/midnight_alerts/alarm_control_panel.py`](custom_components/midnight_alerts/alarm_control_panel.py) (the Home Assistant platform entry point) and [`custom_components/midnight_alerts/alarmo/`](custom_components/midnight_alerts/alarmo/) (Alarmo's internal modules: coordinator, storage, sensors, automations, MQTT, websocket API, sidebar panel, and frontend).

### Modifications from the original (per License §4(b))

Home Assistant only discovers one config-flow domain and one set of platforms
per top-level `custom_components/<domain>/` folder, so Alarmo could not be
merged into `midnight_alerts` as unmodified vendored code — it needed to
become part of the same integration domain instead of its own. The following
changes were made to the files under `custom_components/midnight_alerts/`
(alarm_control_panel.py and the `alarmo/` package) relative to the pinned
upstream release:

- Removed Alarmo's own `AlarmoConfigFlow`/config entry and manifest entirely;
  its setup (coordinator, storage, services, panel, websocket API) is now
  triggered directly from `midnight_alerts`'s own config entry instead of a
  separate one.
- Extracted the coordinator, device registration, and service-registration
  logic that lived in Alarmo's own `__init__.py` into `alarmo/coordinator.py`,
  called from `midnight_alerts/__init__.py`.
- Moved `alarm_control_panel.py` to the top level of `midnight_alerts` (a
  Home Assistant requirement for platform discovery) and moved Alarmo's
  other internal modules (`automations.py`, `card.py`, `event.py`,
  `helpers.py`, `mqtt.py`, `panel.py`, `sensors.py`, `store.py`,
  `websockets.py`, and `frontend/`) into an `alarmo/` subpackage; import
  paths were adjusted accordingly.
- `alarmo/const.py`: `NAME` (the device name/model and sidebar panel title)
  changed from `"Alarmo"` to `"Midnight 911 – Alarm Panel"` so the merged
  integration presents as one product. `DOMAIN` (`"alarmo"`) was
  intentionally left unchanged — it's used only as an internal
  `hass.data`/storage-key namespace, not as a registered Home Assistant
  integration domain, so existing `.storage/alarmo.storage` data keeps
  loading unchanged.
- `alarmo/panel.py`: changed how the frontend bundle's file path is resolved
  (from a `custom_components/<domain>/` root assumption to a path relative to
  the module's own new location).
- `services.yaml`'s entity-picker selectors now filter on
  `integration: midnight_alerts` instead of `integration: alarmo`, matching
  the platform's new owning domain; the `enable_user`/`disable_user` services
  are now registered under the `midnight_alerts` service domain instead of
  `alarmo` (the `arm`/`disarm`/`skip_delay` entity services already follow
  the owning platform automatically and needed no change).
- Merged Alarmo's `services.yaml`, `icons.json`, and `translations/*.json`
  content into `midnight_alerts`'s own copies of those files.

No changes were made to Alarmo's actual alarm logic (arming/disarming,
sensors, automations, MQTT, sensor groups, user codes) or its frontend.

- **Trademark note:** "Alarmo" is nielsfaber's project name. The Apache License does not grant trademark rights (§6); it is used here only to name and credit the original project this feature is built on.

To pull a newer Alarmo release: update the reference copy at
`custom_components/midnight_alerts/vendor/alarmo/` from the new upstream
release/tag, diff it against the previous reference copy to see what
upstream changed, then manually re-apply the relevant changes to
`custom_components/midnight_alerts/alarm_control_panel.py` and
`custom_components/midnight_alerts/alarmo/` (which are no longer a 1:1 copy
of upstream and can't be re-vendored automatically).
