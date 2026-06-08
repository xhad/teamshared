"""Identity: secret hashing (unit) + API keys / RBAC (integration)."""

from __future__ import annotations

import uuid

import pytest

from teamshared.config import get_settings
from teamshared.identity.accounts import AccountStore
from teamshared.identity.api_keys import ApiKeyStore
from teamshared.identity.hashing import hash_secret, verify_secret
from teamshared.identity.provisioning import signup_org
from teamshared.identity.rbac import Authorizer, PermissionDenied, Permissions, implies_permission
from teamshared.identity.roles import RoleStore
from teamshared.tenancy.context import TenantDb
from teamshared.tenancy.repository import TenancyRepository


def test_hash_roundtrip() -> None:
    enc = hash_secret("tsk_abc_supersecret")
    assert enc.startswith("scrypt$")
    assert verify_secret("tsk_abc_supersecret", enc)
    assert not verify_secret("wrong", enc)


def test_hash_rejects_garbage() -> None:
    assert not verify_secret("x", "not-a-valid-hash")


def test_implies_work_permissions_from_memory_and_org_admin() -> None:
    member = frozenset({Permissions.MEMORY_READ, Permissions.MEMORY_CREATE})
    assert implies_permission(member, Permissions.WORK_READ)
    assert implies_permission(member, Permissions.WORK_WRITE)

    viewer = frozenset({Permissions.MEMORY_READ})
    assert implies_permission(viewer, Permissions.WORK_READ)
    assert not implies_permission(viewer, Permissions.WORK_WRITE)

    admin = frozenset({Permissions.ORG_ADMIN})
    assert implies_permission(admin, Permissions.WORK_READ)
    assert implies_permission(admin, Permissions.WORK_WRITE)


@pytest.mark.integration
async def test_signup_authenticate_and_rbac() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    keys = ApiKeyStore(db)
    roles = RoleStore(db)
    try:
        result = await signup_org(
            repo=repo,
            api_keys=keys,
            roles=roles,
            accounts=AccountStore(db),
            org_slug=f"org-{uuid.uuid4().hex[:8]}",
            org_name="Acme",
            owner_email="owner@acme.test",
        )
        principal = await keys.authenticate(result.api_key.token)
        assert principal is not None
        assert principal.org_id == result.org_id
        assert principal.type == "user"

        authz = Authorizer(db)
        await authz.require(principal, Permissions.MEMORY_READ)
        await authz.require(principal, Permissions.ORG_ADMIN)

        # Bad token is rejected.
        assert await keys.authenticate("tsk_dead_beef_nope") is None

        # Revocation takes effect.
        await keys.revoke(result.org_id, result.api_key.id)
        assert await keys.authenticate(result.api_key.token) is None
    finally:
        await db.close()


@pytest.mark.integration
async def test_viewer_cannot_write() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    keys = ApiKeyStore(db)
    roles = RoleStore(db)
    try:
        org = await repo.create_organization(f"org-{uuid.uuid4().hex[:8]}", "ViewerCo")
        user = await repo.create_user(org.id, "viewer@co.test")
        await roles.bind_role(
            org_id=org.id, principal_type="user", principal_id=user.id, role_name="viewer"
        )
        key = await keys.mint(
            org_id=org.id, principal_type="user", principal_id=user.id, name="v"
        )
        principal = await keys.authenticate(key.token)
        assert principal is not None
        authz = Authorizer(db)
        await authz.require(principal, Permissions.MEMORY_READ)
        with pytest.raises(PermissionDenied):
            await authz.require(principal, Permissions.MEMORY_CREATE)
    finally:
        await db.close()
