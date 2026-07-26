"""Install and auto-configure the bundled Alarmo integration.

Alarmo ships nested inside this integration's own package (see vendor/alarmo)
so that a single HACS install delivers both. Home Assistant only discovers
custom integrations that live directly under custom_components/, so on setup
we copy the bundled copy out to a real custom_components/alarmo the first
time (and whenever the bundled version changes), then auto-create its config
entry once Home Assistant can see it.
"""
import json
import logging
import shutil
from pathlib import Path

from homeassistant.components import persistent_notification
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_custom_components

_LOGGER = logging.getLogger(__name__)

ALARMO_DOMAIN = "alarmo"
_MARKER_NAME = ".midnight_alerts_bundled"
_RESTART_NOTIFICATION_ID = "midnight_alerts_alarmo_restart"
_BUNDLED_ALARMO = Path(__file__).parent / "vendor" / "alarmo" / "custom_components" / "alarmo"
_ALARMO_ENTRY_TITLE = "Midnight 911 – Alarm Panel"


def _read_version(manifest_path: Path) -> str | None:
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text()).get("version")


def _sync_files(hass: HomeAssistant) -> bool:
    """Copy the bundled Alarmo integration into custom_components/ if needed.

    Returns True if files were written (a restart is then needed for Home
    Assistant to discover them).
    """
    target = Path(hass.config.path("custom_components", ALARMO_DOMAIN))
    bundled_version = _read_version(_BUNDLED_ALARMO / "manifest.json")

    if target.exists() and not (target / _MARKER_NAME).exists():
        _LOGGER.warning(
            "Found an existing %s integration not installed by Midnight 911; "
            "leaving it untouched",
            ALARMO_DOMAIN,
        )
        return False

    if _read_version(target / "manifest.json") == bundled_version:
        return False

    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(_BUNDLED_ALARMO, target)
    (target / _MARKER_NAME).write_text(bundled_version or "")
    return True


async def async_ensure_alarmo(hass: HomeAssistant) -> None:
    """Ensure the bundled Alarmo integration is installed and configured."""
    changed = await hass.async_add_executor_job(_sync_files, hass)

    if changed:
        persistent_notification.async_create(
            hass,
            "Midnight 911 has installed (or updated) its bundled Alarmo alarm "
            "panel. Restart Home Assistant to finish setting it up.",
            title="Midnight 911: restart required",
            notification_id=_RESTART_NOTIFICATION_ID,
        )
        return

    existing_entries = hass.config_entries.async_entries(ALARMO_DOMAIN)
    if existing_entries:
        _async_rename_entry(hass, existing_entries[0])
        return

    custom_components = await async_get_custom_components(hass)
    if ALARMO_DOMAIN not in custom_components:
        _LOGGER.debug("%s not yet discoverable; restart still pending", ALARMO_DOMAIN)
        return

    try:
        result = await hass.config_entries.flow.async_init(
            ALARMO_DOMAIN, context={"source": SOURCE_USER}
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Failed to auto-configure the bundled Alarmo integration")
        return

    if result.get("type") == "create_entry":
        persistent_notification.async_dismiss(hass, _RESTART_NOTIFICATION_ID)
        entry = result.get("result")
        if entry is not None:
            _async_rename_entry(hass, entry)


def _async_rename_entry(hass: HomeAssistant, entry) -> None:
    """Retitle the Alarmo entry so it visually pairs with Midnight 911."""
    if entry.title != _ALARMO_ENTRY_TITLE:
        hass.config_entries.async_update_entry(entry, title=_ALARMO_ENTRY_TITLE)
