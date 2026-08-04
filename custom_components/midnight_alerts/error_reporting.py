"""Isolated Sentry crash reporting for Midnight Alerts.

This uses an isolated sentry_sdk Client bound to its own Scope (not the
global sentry_sdk.init()), so this integration's error reporting never
conflicts with a user's own Home Assistant Core "sentry" integration, if
they have one configured separately.

Reporting is fully manual and opt-in - no sentry-sdk auto-instrumentation
is enabled - so nothing is ever captured unless report_exception() is
called explicitly, and only the exception plus a short operation label are
sent, never request payloads, headers, or entity state. sentry_sdk itself
is only imported on first use, so installs that never enable reporting
never pay any import/init cost.

Captured exceptions are tagged with the integration's own running version
(manifest.json's `version` field, passed in as `release`) so Sentry can
correlate errors to specific releases. The matching Sentry Release + Deploy
records themselves are created in CI - see the "Record Sentry release and
deploy" step in .github/workflows/release.yml, which fires right after
semantic-release publishes a new version, using that exact same version
string.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentry_sdk import Scope

_LOGGER = logging.getLogger(__name__)

_DSN = "https://0508610bb935072bf7a6224ca080fb98@o4510154409902080.ingest.us.sentry.io/4511781103337472"

_SCRUB_KEYS = {"address", "lat", "lng", "authorization", "api_key"}

_scope: Scope | None = None


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """Strip anything that could contain PII or credentials, defense in depth."""
    request = event.get("request")
    if isinstance(request, dict) and isinstance(request.get("headers"), dict):
        request["headers"] = {
            key: value
            for key, value in request["headers"].items()
            if key.lower() not in _SCRUB_KEYS
        }
    for section in ("extra", "contexts"):
        data = event.get(section)
        if isinstance(data, dict):
            for key in list(data):
                if key.lower() in _SCRUB_KEYS:
                    data.pop(key)
    return event


def _get_scope(release: str | None) -> Scope:
    """Lazily create the isolated client/scope on first use.

    The client is a process-wide singleton, so `release` only has an effect
    on the call that actually triggers construction - in practice that's
    fine, since the running integration's version can't change without a
    Home Assistant restart anyway.
    """
    global _scope
    if _scope is None:
        import sentry_sdk

        client = sentry_sdk.Client(
            dsn=_DSN,
            release=release,
            send_default_pii=False,
            default_integrations=False,
            before_send=_before_send,
        )
        _scope = sentry_sdk.Scope()
        _scope.set_client(client)
    return _scope


def report_exception(
    err: Exception, *, operation: str, enabled: bool, release: str | None = None
) -> None:
    """Report an exception to Midnight's Sentry project, if enabled.

    Never raises - a reporting failure must never break the integration.
    """
    if not enabled:
        return
    try:
        scope = _get_scope(release)
        scope.set_tag("operation", operation)
        scope.capture_exception(err)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Failed to report exception to Sentry", exc_info=True)
