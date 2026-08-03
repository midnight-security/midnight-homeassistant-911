# Path to Home Assistant Core

This document tracks what's required to move `midnight_alerts` from a
HACS-distributed custom integration into `home-assistant/core`.

Status of individual rules is tracked in [`quality_scale.yaml`](quality_scale.yaml),
which follows the same format Home Assistant Core uses to validate
integrations via `hassfest`. This file explains the process and the "why"
behind each requirement.

## Process overview

1. Meet **Bronze** tier on the [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) — this is the mandatory minimum for any new integration, not an optional goal.
2. Add brand assets — done, at `custom_components/midnight_alerts/brand/` (icon/logo, dark variants, `@2x`). As of Home Assistant 2026.3.0 (see the [Brands Proxy API announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api)), a `brand/` folder bundled directly in the integration is read automatically and takes priority over the `home-assistant/brands` CDN — no manifest key or extra config needed. **This requires HA Core 2026.3.0+; anything older won't display it.** Filing a PR against [home-assistant/brands](https://github.com/home-assistant/brands) is now a legacy fallback for pre-2026.3 instances, not required for this to work going forward.
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
`entity-translations`, `exception-translations`, and `test-coverage` are
done (99% overall — every module at 100% except `api.py`, tracked below
under `dependency-transparency`). `stale-devices` and the docs-* rules
(`docs-high-level-description`, `docs-installation-instructions`,
`docs-supported-functions`, `docs-use-cases`, `docs-troubleshooting`,
`docs-known-limitations`) are also done, now that `docs/midnight_alerts.markdown`
actually documents the alarm feature (areas, users/PINs, sensor groups,
Alarmo import) instead of only the original button.

Still open, to revisit later: `reauthentication-flow` (Silver),
`icon-translations` and `reconfiguration-flow` (Gold — the latter is about
the top-level API-key entry, not the alarm feature's own subentry
reconfigure flows, which already work), `strict-typing` (Platinum).
`dynamic-devices` is flagged but not resolved — each area subentry gets
its own device added/removed live, and real core integrations disagree on
whether that counts as "dynamic" for this rule (see the comment in
`quality_scale.yaml`); needs an actual read of the rule's intent rather
than a guess.

## Not today — separate coding sessions

- Extract `api.py` into a standalone PyPI package (also closes its test-coverage gap)
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
