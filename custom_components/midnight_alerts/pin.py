"""PIN hashing and verification for Midnight Alarm users.

Kept free of entity-platform imports so it's unit-testable standalone.

Codes are hashed as base64(bcrypt(code)) - the exact format Alarmo itself
uses - so a PIN carried over via "Import from Alarmo" keeps working
immediately with zero conversion. Alarmo's own storage never contains a
recoverable plaintext PIN (bcrypt is one-way), so matching its hash format
is the only way an import can carry forward a *working* code at all.

The base AlarmControlPanelEntity provides no code-correctness checking for
any action (arm or disarm) - this module is the entirety of that logic.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, NamedTuple

import bcrypt

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .const import (
    CONF_AREA_LIMIT,
    CONF_CAN_ARM,
    CONF_CAN_DISARM,
    CONF_CODE,
    CONF_ENABLED,
    CONF_IS_OVERRIDE_CODE,
    CONF_NAME,
    DOMAIN,
    SUBENTRY_TYPE_USER,
)

_BCRYPT_ROUNDS = 10
_MAX_WORKERS = 4


class CodeMatch(NamedTuple):
    """Result of a successful PIN check."""

    changed_by: str
    is_override_code: bool


async def async_hash_code(hass: HomeAssistant, code: str) -> str:
    """Hash a PIN the same way Alarmo does: base64(bcrypt(code))."""
    if not code:
        return ""
    return await hass.async_add_executor_job(_hash_code_sync, code)


def _hash_code_sync(code: str) -> str:
    hashed = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return base64.b64encode(hashed).decode()


def _check_code_sync(code: str, hashed: str) -> bool:
    """Empty stored hash = no PIN required for that user, always authenticates."""
    if not hashed:
        return True
    if not code:
        return False
    try:
        return bcrypt.checkpw(code.encode("utf-8"), base64.b64decode(hashed))
    except (ValueError, TypeError):
        return False


def _enabled_users(entry: ConfigEntry) -> list[ConfigSubentry]:
    """Every enabled user, regardless of per-action/area permissions.

    A disabled user is treated as not existing at all - if every user ends
    up disabled, no code is required anywhere (degrades gracefully rather
    than locking the system out). This is deliberately separate from
    `_eligible_users`: a user who *is* enabled but isn't permitted for this
    specific action/area should still cause a wrong/missing code to be
    rejected, not silently skipped.
    """
    return [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_USER
        and subentry.data.get(CONF_ENABLED, True)
    ]


def _eligible_users(
    entry: ConfigEntry,
    *,
    area_subentry_id: str | None,
    action: Literal["arm", "disarm"],
) -> list[ConfigSubentry]:
    """Enabled users additionally permitted for this specific action/area.

    `area_subentry_id=None` is the master (all-areas) action: only a user
    with no area_limit at all - i.e. already permitted everywhere - is
    eligible. A user restricted to specific areas is deliberately never
    eligible for master, regardless of which areas are on their list.
    """
    can_field = CONF_CAN_ARM if action == "arm" else CONF_CAN_DISARM
    return [
        subentry
        for subentry in _enabled_users(entry)
        if subentry.data.get(can_field, True)
        and (
            not subentry.data.get(CONF_AREA_LIMIT)
            or (
                area_subentry_id is not None
                and area_subentry_id in subentry.data[CONF_AREA_LIMIT]
            )
        )
    ]


def _find_match_sync(
    code: str, candidates: list[ConfigSubentry]
) -> ConfigSubentry | None:
    """Bounded concurrent bcrypt fan-out, short-circuiting on first match.

    Bounds worst-case latency to ~1 bcrypt call regardless of user count,
    rather than a sequential scan that visibly degrades as users are added -
    both cost the same one executor hop either way.
    """
    with ThreadPoolExecutor(max_workers=min(len(candidates), _MAX_WORKERS)) as pool:
        for user, matched in zip(
            candidates,
            pool.map(
                lambda u: _check_code_sync(code, u.data.get(CONF_CODE, "")),
                candidates,
            ),
        ):
            if matched:
                return user
    return None


def any_users_configured(entry: ConfigEntry) -> bool:
    """Whether any enabled user exists at all, anywhere on this entry.

    Drives `code_arm_required`: with zero enabled users a code is not
    demanded at all (Phase 1 simplification - no separate global
    code-required toggle yet). This intentionally ignores per-action/area
    permissions - those only matter once a code is actually being checked.
    """
    return bool(_enabled_users(entry))


async def async_validate_code(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    code: str | None,
    area_subentry_id: str | None,
    action: Literal["arm", "disarm"],
) -> CodeMatch | None:
    """Resolve `code` to a permitted user for this area, or raise.

    `area_subentry_id=None` validates for the master (all-areas) entity
    instead of one specific area - see `_eligible_users`.

    Returns None only when no enabled users exist at all (no PIN required).
    If any enabled user exists but none of them are eligible for this
    specific action/area, or the code doesn't match one that is, this
    raises rather than silently skipping through - the user *is*
    configured, just not permitted here. Never runs bcrypt on the event
    loop.
    """
    if not _enabled_users(entry):
        return None

    candidates = _eligible_users(entry, area_subentry_id=area_subentry_id, action=action)
    matched = (
        await hass.async_add_executor_job(_find_match_sync, code or "", candidates)
        if candidates
        else None
    )
    if matched is None:
        raise ServiceValidationError(
            "Invalid or unauthorized code",
            translation_domain=DOMAIN,
            translation_key="invalid_code",
        )
    return CodeMatch(
        changed_by=matched.data.get(CONF_NAME, matched.title),
        is_override_code=bool(matched.data.get(CONF_IS_OVERRIDE_CODE)),
    )
