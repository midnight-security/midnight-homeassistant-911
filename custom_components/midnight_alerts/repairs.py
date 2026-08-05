"""Repair flow for Midnight Alerts.

Currently only backs the `location_mismatch` issue - offers a menu instead
of a single "Fix" action, since there isn't one right answer: the user
either needs to update the account tied to their API key (swap keys via
reauth) or has already fixed the address/location on one side and just
needs Midnight to notice.
"""
from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


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
        entry = self.hass.config_entries.async_get_entry(self.data["entry_id"])
        if entry is not None:
            entry.async_start_reauth(self.hass)
        return self.async_abort(reason="reauth_started")

    async def async_step_recheck(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Reload the entry to recheck - leave the issue alone either way."""
        await self.hass.config_entries.async_reload(self.data["entry_id"])

        issue_registry = ir.async_get(self.hass)
        if issue_registry.async_get_issue(DOMAIN, self.issue_id) is not None:
            return self.async_abort(reason="still_mismatched")
        return self.async_abort(reason="resolved")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Return the repair flow for a given issue id - only one exists today."""
    return LocationMismatchRepairFlow()
