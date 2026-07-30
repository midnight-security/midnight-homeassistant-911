"""Tests for diagnostics.py - PIN and API key redaction."""
import json
from unittest.mock import AsyncMock, patch

from homeassistant.components.diagnostics import REDACTED
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.midnight_alerts import diagnostics, pin
from custom_components.midnight_alerts.const import (
    CONF_API_KEY,
    CONF_CODE,
    CONF_MODES,
    CONF_NAME,
    DOMAIN,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_USER,
)

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"


async def _entry_with_user(hass) -> tuple[MockConfigEntry, str]:
    hashed = await pin.async_hash_code(hass, "4242")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "super-secret-key"},
        subentries_data=[
            {
                "subentry_id": "area1",
                "subentry_type": SUBENTRY_TYPE_AREA,
                "title": "Home",
                "unique_id": None,
                "data": {
                    CONF_NAME: "Home",
                    CONF_MODES: {
                        "armed_away": {
                            "enabled": True,
                            "exit_time": 60,
                            "entry_time": 30,
                            "trigger_time": 120,
                        }
                    },
                },
            },
            {
                "subentry_id": "user1",
                "subentry_type": SUBENTRY_TYPE_USER,
                "title": "Alice",
                "unique_id": None,
                "data": {
                    CONF_NAME: "Alice",
                    CONF_CODE: hashed,
                    "can_arm": True,
                    "can_disarm": True,
                    "is_override_code": False,
                    "enabled": True,
                    "area_limit": [],
                },
            },
        ],
    )
    entry.add_to_hass(hass)
    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hashed


async def test_diagnostics_redacts_api_key_and_pin(hass):
    entry, hashed = await _entry_with_user(hass)

    result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    assert result["entry_data"][CONF_API_KEY] == REDACTED
    dumped = json.dumps(result)
    assert "super-secret-key" not in dumped
    assert hashed not in dumped

    (user_subentry,) = [
        s for s in result["subentries"] if s["subentry_type"] == SUBENTRY_TYPE_USER
    ]
    assert user_subentry["data"][CONF_CODE] == REDACTED
    # non-secret fields must still come through, or diagnostics is useless
    assert user_subentry["data"][CONF_NAME] == "Alice"


async def test_diagnostics_includes_area_and_sensor_info(hass):
    entry, _ = await _entry_with_user(hass)

    result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    (area_subentry,) = [
        s for s in result["subentries"] if s["subentry_type"] == SUBENTRY_TYPE_AREA
    ]
    assert area_subentry["data"][CONF_NAME] == "Home"
    assert area_subentry["data"][CONF_MODES]["armed_away"]["exit_time"] == 60
    assert result["sensors"] == []  # none attached in this fixture


async def test_diagnostics_over_http(hass, hass_client):
    """End-to-end via the real diagnostics HTTP endpoint, not just the function."""
    entry, hashed = await _entry_with_user(hass)

    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert data["entry_data"][CONF_API_KEY] == REDACTED
    dumped = json.dumps(data)
    assert hashed not in dumped
    assert "super-secret-key" not in dumped
