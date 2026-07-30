# Path to Home Assistant Core

This document tracks what's required to move `midnight_alerts` from a
HACS-distributed custom integration into `home-assistant/core`.

Status of individual rules is tracked in [`quality_scale.yaml`](quality_scale.yaml),
which follows the same format Home Assistant Core uses to validate
integrations via `hassfest`. This file explains the process and the "why"
behind each requirement.

## Process overview

1. Meet **Bronze** tier on the [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) — this is the mandatory minimum for any new integration, not an optional goal.
2. Add brand assets — as of Home Assistant 2026.3.0, custom integrations can bundle these directly rather than filing a PR against [home-assistant/brands](https://github.com/home-assistant/brands) (that central repo submission is now mainly for after the integration is actually merged into core).
3. Write documentation for [home-assistant/home-assistant.io](https://github.com/home-assistant/home-assistant.io) — draft lives at [`docs/midnight_alerts.markdown`](docs/midnight_alerts.markdown), to be submitted as its own PR against that repo once Bronze is met.
4. Open a PR to [home-assistant/core](https://github.com/home-assistant/core) moving the integration from `custom_components/midnight_alerts` to `homeassistant/components/midnight_alerts`.
5. Integration owner: `@midnight-security/midnight-team` (see `manifest.json` and `.github/CODEOWNERS`) — both individual GitHub usernames and org teams are accepted as codeowners.

## Bronze tier — required now

| Rule | Requirement | Status |
|---|---|---|
| `config-flow` | Set up via the UI | Done |
| `unique-config-entry` | Prevent duplicate setup | Done |
| `entity-unique-id` | Entities have a stable unique ID | Done |
| `has-entity-name` | Entities set `has_entity_name = True` | Done |
| `test-before-configure` | Config flow tests the connection before creating the entry | Done |
| `test-before-setup` | `async_setup_entry` verifies connectivity before completing setup | Done |
| `runtime-data` | Use `ConfigEntry.runtime_data`, not `hass.data[DOMAIN]` | Done |
| `config-flow-test-coverage` | Automated tests cover the config flow | Done — `tests/components/midnight_alerts/test_config_flow.py`, 100% line coverage of `config_flow.py` |
| `brands` | Branding assets available | Done — `custom_components/midnight_alerts/brand/` |
| `dependency-transparency` | Third-party API code lives in a documented, pinned dependency rather than inline in the integration | **Todo** — see note below |
| `docs-high-level-description` | Docs describe the product/service at a high level | Done — `docs/midnight_alerts.markdown` |
| `docs-installation-instructions` | Step-by-step setup instructions | Done — `docs/midnight_alerts.markdown` |
| `docs-removal-instructions` | How to remove the integration | Done — `docs/midnight_alerts.markdown` |
| `action-setup` | Service actions registered in `async_setup` | Exempt — no custom service actions |
| `appropriate-polling` | Sensible polling interval | Exempt — `cloud_push`, not polling |
| `docs-actions` / `docs-triggers` / `docs-conditions` | Docs for services/triggers/conditions | Exempt — none provided |
| `common-modules` | Shared patterns live in common modules | Done — `pin.py`, `sensors.py`, `alarm_state.py`, `sensor_groups.py`, `alarmo_import.py` |
| `entity-event-setup` | Entity events subscribed in correct lifecycle method | Done — both platforms are push/callback-driven, no polling |

### Note on `dependency-transparency`

Home Assistant's actual new-integration PR checklist states: *"All API
specific code has to be part of a third party library hosted on PyPi."*
Right now `api.py`'s `MidnightAlertsApiClient` lives directly inside the
component. Satisfying this rule for real means extracting that client into
its own published PyPI package and depending on it via `requirements` in
`manifest.json` — a separate, larger effort from the rest of this checklist
(see "Not today" below).

## Silver / Gold / Platinum — roadmap, not required for initial acceptance

Tracked in `quality_scale.yaml` for completeness, but none of these block
getting into core. `action-exceptions`, `parallel-updates`, `diagnostics`,
`entity-translations`, and `exception-translations` are now done. Still
open, to revisit later: `reauthentication-flow` and `test-coverage`
(Silver), `icon-translations` and `reconfiguration-flow` (Gold — the latter
is about the top-level API-key entry, not the alarm feature's own subentry
reconfigure flows, which already work), `strict-typing` (Platinum).

## Not today — separate coding sessions

- Add test coverage for `api.py` / `__init__.py` / `button.py` (config flow is now covered, but the rest of the integration isn't — needed for the Silver `test-coverage` rule)
- Extract `api.py` into a standalone PyPI package
- Add `strict-typing` (mypy) once the above lands

## Housekeeping before the actual `home-assistant/core` PR

- Remove the `version` field from `manifest.json` (core integrations don't
  carry one — it's a HACS/custom-integration-only field). Do **not** remove
  it now; it's still needed for this repo's own semantic-release/HACS
  pipeline until the day the code actually moves into core.
- Update `manifest.json`'s `documentation` field to point at the real
  `https://www.home-assistant.io/integrations/midnight_alerts/` URL once
  the docs PR is merged, instead of this repo's own `docs/` file.
- Add a `quality_scale` field to `manifest.json` once Bronze is actually met.
