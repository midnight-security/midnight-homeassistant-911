"""Tests for pin.py's PIN hashing and verification."""

from unittest.mock import patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts import pin
from custom_components.midnight_alerts.const import DOMAIN, SUBENTRY_TYPE_USER


def _user_subentry(
    subentry_id: str,
    *,
    code: str,
    name: str = "Alice",
    can_arm: bool = True,
    can_disarm: bool = True,
    is_override_code: bool = False,
    area_limit: list[str] | None = None,
    enabled: bool = True,
) -> dict:
    return {
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_USER,
        "title": name,
        "unique_id": None,
        "data": {
            "name": name,
            "code": code,
            "can_arm": can_arm,
            "can_disarm": can_disarm,
            "is_override_code": is_override_code,
            "area_limit": area_limit or [],
            "enabled": enabled,
        },
    }


async def test_hash_round_trip(hass):
    hashed = await pin.async_hash_code(hass, "1234")
    assert hashed
    assert hashed != "1234"
    assert pin._check_code_sync("1234", hashed) is True
    assert pin._check_code_sync("9999", hashed) is False


async def test_empty_code_hashes_to_empty(hass):
    assert await pin.async_hash_code(hass, "") == ""


async def test_empty_stored_hash_always_authenticates():
    assert pin._check_code_sync("anything", "") is True
    assert pin._check_code_sync("", "") is True


async def test_empty_code_against_a_real_hash_fails(hass):
    hashed = await pin.async_hash_code(hass, "1234")
    assert pin._check_code_sync("", hashed) is False


def test_malformed_hash_is_treated_as_no_match():
    """A corrupt/non-base64 stored hash must fail closed, not raise."""
    assert pin._check_code_sync("1234", "not-valid-base64!!!") is False


async def test_validate_code_no_users_configured_skips_through(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, subentries_data=[])
    entry.add_to_hass(hass)
    result = await pin.async_validate_code(
        hass, entry, code=None, area_subentry_id="area1", action="arm"
    )
    assert result is None


async def test_validate_code_correct_pin_matches(hass):
    hashed = await pin.async_hash_code(hass, "4242")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[_user_subentry("user1", code=hashed, name="Alice")],
    )
    entry.add_to_hass(hass)

    match = await pin.async_validate_code(
        hass, entry, code="4242", area_subentry_id="area1", action="arm"
    )
    assert match.changed_by == "Alice"
    assert match.is_override_code is False


async def test_validate_code_wrong_pin_raises(hass):
    hashed = await pin.async_hash_code(hass, "4242")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[_user_subentry("user1", code=hashed)],
    )
    entry.add_to_hass(hass)

    with pytest.raises(ServiceValidationError):
        await pin.async_validate_code(
            hass, entry, code="0000", area_subentry_id="area1", action="arm"
        )


async def test_validate_code_respects_can_arm(hass):
    hashed = await pin.async_hash_code(hass, "4242")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[_user_subentry("user1", code=hashed, can_arm=False)],
    )
    entry.add_to_hass(hass)

    with pytest.raises(ServiceValidationError):
        await pin.async_validate_code(
            hass, entry, code="4242", area_subentry_id="area1", action="arm"
        )
    # but disarm should still work for the same user
    match = await pin.async_validate_code(
        hass, entry, code="4242", area_subentry_id="area1", action="disarm"
    )
    assert match.changed_by == "Alice"


async def test_validate_code_respects_area_limit(hass):
    hashed = await pin.async_hash_code(hass, "4242")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[_user_subentry("user1", code=hashed, area_limit=["area2"])],
    )
    entry.add_to_hass(hass)

    with pytest.raises(ServiceValidationError):
        await pin.async_validate_code(
            hass, entry, code="4242", area_subentry_id="area1", action="arm"
        )
    match = await pin.async_validate_code(
        hass, entry, code="4242", area_subentry_id="area2", action="arm"
    )
    assert match.changed_by == "Alice"


async def test_validate_code_disabled_user_degrades_to_no_code_required(hass):
    """A fully disabled user is treated as not existing - not a lockout."""
    hashed = await pin.async_hash_code(hass, "4242")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[_user_subentry("user1", code=hashed, enabled=False)],
    )
    entry.add_to_hass(hass)

    result = await pin.async_validate_code(
        hass, entry, code=None, area_subentry_id="area1", action="arm"
    )
    assert result is None


async def test_bcrypt_never_runs_on_the_event_loop(hass):
    """Regression guard: hashing and validation must go through the executor."""
    with patch.object(
        hass, "async_add_executor_job", wraps=hass.async_add_executor_job
    ) as mock_executor:
        await pin.async_hash_code(hass, "1234")
        assert mock_executor.called

    hashed = await pin.async_hash_code(hass, "1234")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[_user_subentry("user1", code=hashed)],
    )
    entry.add_to_hass(hass)
    with patch.object(
        hass, "async_add_executor_job", wraps=hass.async_add_executor_job
    ) as mock_executor:
        await pin.async_validate_code(
            hass, entry, code="1234", area_subentry_id="area1", action="arm"
        )
        assert mock_executor.called
