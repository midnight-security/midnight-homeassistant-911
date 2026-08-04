"""Test Sentry crash reporting."""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.midnight_alerts import error_reporting


@pytest.fixture(autouse=True)
def reset_scope():
    """Reset the cached isolated scope between tests."""
    error_reporting._scope = None
    yield
    error_reporting._scope = None


def test_disabled_never_touches_sentry_sdk():
    """When disabled, report_exception must not build a client at all."""
    with patch.object(error_reporting, "_get_scope") as mock_get_scope:
        error_reporting.report_exception(
            ValueError("boom"), operation="validate", enabled=False
        )
    mock_get_scope.assert_not_called()


def test_enabled_reports_via_isolated_scope():
    """When enabled, the exception is tagged and captured on the isolated scope."""
    mock_scope = MagicMock()
    err = ValueError("boom")

    with patch.object(error_reporting, "_get_scope", return_value=mock_scope):
        error_reporting.report_exception(err, operation="validate", enabled=True)

    mock_scope.set_tag.assert_called_once_with("operation", "validate")
    mock_scope.capture_exception.assert_called_once_with(err)


def test_reporting_failure_is_swallowed():
    """A broken Sentry client must never break the integration."""
    with patch.object(error_reporting, "_get_scope", side_effect=RuntimeError("no network")):
        error_reporting.report_exception(ValueError("boom"), operation="validate", enabled=True)


def test_get_scope_builds_client_with_safe_options():
    """The isolated client must disable PII/auto-instrumentation and use the scrub hook."""
    with patch("sentry_sdk.Client") as mock_client_cls, patch("sentry_sdk.Scope") as mock_scope_cls:
        mock_scope_instance = MagicMock()
        mock_scope_cls.return_value = mock_scope_instance

        error_reporting._get_scope("1.2.3")

    _, kwargs = mock_client_cls.call_args
    assert kwargs["dsn"] == error_reporting._DSN
    assert kwargs["release"] == "1.2.3"
    assert kwargs["send_default_pii"] is False
    assert kwargs["default_integrations"] is False
    assert kwargs["before_send"] is error_reporting._before_send
    mock_scope_instance.set_client.assert_called_once_with(mock_client_cls.return_value)


def test_get_scope_is_cached():
    """The client/scope should only be built once, not on every call."""
    with patch("sentry_sdk.Client") as mock_client_cls, patch("sentry_sdk.Scope"):
        error_reporting._get_scope("1.2.3")
        error_reporting._get_scope("1.2.3")

    mock_client_cls.assert_called_once()


def test_report_exception_passes_release_through():
    """The release version flows from report_exception into scope construction."""
    mock_scope = MagicMock()
    with patch.object(error_reporting, "_get_scope", return_value=mock_scope) as mock_get_scope:
        error_reporting.report_exception(
            ValueError("boom"), operation="validate", enabled=True, release="1.2.3"
        )

    mock_get_scope.assert_called_once_with("1.2.3")


@pytest.mark.parametrize(
    ("event", "expected_headers"),
    [
        (
            {"request": {"headers": {"Authorization": "Bearer secret", "Accept": "json"}}},
            {"Accept": "json"},
        ),
        (
            {"request": {"headers": {"api_key": "secret", "Content-Type": "json"}}},
            {"Content-Type": "json"},
        ),
    ],
)
def test_before_send_strips_sensitive_headers(event, expected_headers):
    """Authorization/API key headers must never reach Sentry, defense in depth."""
    result = error_reporting._before_send(event, {})
    assert result["request"]["headers"] == expected_headers


def test_before_send_strips_sensitive_extra_and_contexts():
    """Address/GPS data must never reach Sentry even if accidentally attached."""
    event = {
        "extra": {"address": "3 Park Ave", "lat": 40.7128, "lng": -74.006, "safe": "ok"},
        "contexts": {"api_key": "secret", "safe": "ok"},
    }
    result = error_reporting._before_send(event, {})
    assert result["extra"] == {"safe": "ok"}
    assert result["contexts"] == {"safe": "ok"}


def test_before_send_handles_missing_sections():
    """A minimal event with no request/extra/contexts must pass through untouched."""
    event = {"message": "boom"}
    assert error_reporting._before_send(event, {}) == event
