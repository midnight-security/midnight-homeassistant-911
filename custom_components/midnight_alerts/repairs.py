"""Repair flow for Midnight Alerts.

Backs two issues:
- `location_mismatch` - offers a menu instead of a single "Fix" action,
  since there isn't one right answer: the user either needs to update the
  account tied to their API key (swap keys via reauth) or has already
  fixed the address/location on one side and just needs Midnight to
  notice.
- `no_api_key` - one action: start a reauth flow to add one.

Both send the user to add/change their key via `entry.async_start_reauth`,
never a reconfigure flow started from here - HA's frontend automatically
surfaces an in-progress reauth flow as a "Reauthenticate" prompt on the
integration card, but has no equivalent surfacing for a reconfigure flow
started from outside the integrations page (confirmed by hand: the repair
dialog just closes with no visible next step, leaving the entry flow
sitting unreachable). Reusing reauth's already-working surfacing, even for
an entry that never had a key at all, gets the user to the same
API-key-only form either way.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE
from homeassistant.components.repairs import RepairsFlow

from . import NO_API_KEY_ISSUE_ID
from .const import DOMAIN


def _async_start_reauth_and_get_reason(hass: HomeAssistant, entry_id: str) -> str:
    """Start reauth for entry_id, unless one's already in progress.

    entry.async_start_reauth silently no-ops if a reauth *or* reconfigure
    flow is already active for the entry (config_entries.py's own guard,
    to avoid stacking duplicate flows) - without checking first, callers
    would report "opening the form" even when nothing actually happened.
    Caught this by hand: an earlier, since-fixed version of this repair
    started a reconfigure flow that nothing ever surfaced or completed, and
    it sat active long enough to silently block a later reauth attempt.
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return "reauth_started"
    if any(entry.async_get_active_flows(hass, {SOURCE_REAUTH, SOURCE_RECONFIGURE})):
        return "already_in_progress"
    entry.async_start_reauth(hass)
    return "reauth_started"


class LocationMismatchRepairFlow(RepairsFlow):
    """Update the API key, or reload the entry to recheck the location.

    The flow manager deletes the issue itself whenever a step finishes via
    `async_create_entry` rather than `async_abort` - regardless of whether
    the thing that was actually wrong got fixed. Neither step below resolves
    anything by itself (reauth only *starts* a key swap; reloading only
    *rechecks* the address), so both abort instead and let the real fix
    (`__init__.py`'s own async_delete_issue once location_match stops being
    False) clear the issue when it's actually true.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Let the user choose how they want to resolve the mismatch."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["update_key", "recheck"],
        )

    async def async_step_update_key(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Start the same reauth flow used when the key itself is rejected."""
        reason = _async_start_reauth_and_get_reason(self.hass, self.data["entry_id"])
        return self.async_abort(reason=reason)

    async def async_step_recheck(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Reload the entry to recheck - leave the issue alone either way."""
        await self.hass.config_entries.async_reload(self.data["entry_id"])

        issue_registry = ir.async_get(self.hass)
        if issue_registry.async_get_issue(DOMAIN, self.issue_id) is not None:
            return self.async_abort(reason="still_mismatched")
        return self.async_abort(reason="resolved")


class NoApiKeyRepairFlow(RepairsFlow):
    """Confirm, then start a reauth flow to add the missing API key.

    Only ever offers the one real action - unlike location_mismatch, there
    isn't a second reasonable resolution to choose between. Aborts (rather
    than async_create_entry) for the same reason as above: starting reauth
    doesn't add the key by itself, so the issue must survive until
    __init__.py's own async_delete_issue actually clears it.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Delegate to async_step_confirm.

        The flow manager passes this issue's `data` (e.g. {"issue_id":
        ...}) as user_input on this very first call, not None - checking
        `user_input is not None` here would treat that as an immediate
        submission. async_step_confirm starts clean instead, same as HA
        core's own ConfirmRepairFlow.
        """
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Confirm, then start the same reauth flow used for a rejected key."""
        if user_input is not None:
            reason = _async_start_reauth_and_get_reason(
                self.hass, self.data["entry_id"]
            )
            return self.async_abort(reason=reason)
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Return the repair flow for a given issue id."""
    if issue_id == NO_API_KEY_ISSUE_ID:
        return NoApiKeyRepairFlow()
    return LocationMismatchRepairFlow()
