"""Production deployment guardrails.

When :attr:`Settings.deployment_env` is ``production``, :func:`validate_settings`
runs before the HTTP server starts and raises :class:`ConfigValidationError` on
unsafe combinations (auth disabled, missing RLS app role, missing secrets, etc.).
"""

from __future__ import annotations

from teamshared.config import Settings


class ConfigValidationError(Exception):
    """Raised when production settings fail validation."""


def validate_settings(settings: Settings) -> None:
    """Validate settings for the active deployment environment.

    No-op for ``development``. For ``production``, accumulates human-readable
    errors and raises :class:`ConfigValidationError` if any are found.
    """
    if settings.deployment_env != "production":
        return

    errors: list[str] = []

    if settings.auth_disabled:
        errors.append("TEAMSHARED_AUTH_DISABLED must be false in production")

    if not settings.session_secret:
        errors.append(
            "TEAMSHARED_SESSION_SECRET is required in production (console sign-in)"
        )

    if not settings.pg_app_user:
        errors.append(
            "TEAMSHARED_PG_APP_USER is required in production so Postgres RLS "
            "is enforced (superuser/admin DSN bypasses RLS)"
        )

    if settings.self_service_tokens and not settings.mint_secret:
        errors.append(
            "TEAMSHARED_MINT_SECRET is required when TEAMSHARED_SELF_SERVICE_TOKENS "
            "is enabled"
        )

    if not settings.connector_encryption_key:
        errors.append(
            "TEAMSHARED_CONNECTOR_ENCRYPTION_KEY is required in production "
            "(connector OAuth tokens must not use the dev-derived key)"
        )

    if settings.dashboard_public_content:
        errors.append(
            "TEAMSHARED_DASHBOARD_PUBLIC_CONTENT must be false in production "
            "(public /memory must not expose memory snippets)"
        )

    if errors:
        bullet = "\n  - "
        raise ConfigValidationError(
            "Production configuration is unsafe:" + bullet + bullet.join(errors)
        )
