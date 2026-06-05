"""Production config guardrails."""

from __future__ import annotations

import pytest

from teamshared.config import Settings
from teamshared.config_validate import ConfigValidationError, validate_settings


def test_validate_skips_development() -> None:
    s = Settings(_env_file=None, auth_disabled=True)
    validate_settings(s)


def test_validate_production_requires_secrets() -> None:
    s = Settings(
        _env_file=None,
        deployment_env="production",
        auth_disabled=True,
        self_service_tokens=True,
        dashboard_public_content=True,
    )
    with pytest.raises(ConfigValidationError) as exc:
        validate_settings(s)
    msg = str(exc.value)
    assert "AUTH_DISABLED" in msg
    assert "SESSION_SECRET" in msg
    assert "JOB_SIGNING_SECRET" in msg
    assert "PG_APP_USER" in msg
    assert "MINT_SECRET" in msg
    assert "CONNECTOR_ENCRYPTION_KEY" in msg
    assert "DASHBOARD_PUBLIC_CONTENT" in msg


def test_validate_production_passes_minimal_safe_config() -> None:
    s = Settings(
        _env_file=None,
        deployment_env="production",
        auth_disabled=False,
        session_secret="test-session-secret",
        job_signing_secret="test-job-signing-secret",
        pg_app_user="teamshared_app",
        pg_app_password="secret",
        mint_secret="mint-secret",
        connector_encryption_key="a" * 64,
        self_service_tokens=True,
        dashboard_public_content=False,
    )
    validate_settings(s)
