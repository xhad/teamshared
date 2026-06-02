"""Org signup: create an org with an owner principal and a first API key.

This is the only flow that crosses the tenancy/identity boundary at bootstrap.
It runs the privileged org creation, then everything else inside the new org's
RLS context.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from teamshared.identity.accounts import AccountStore
from teamshared.identity.api_keys import ApiKeyStore, MintedKey
from teamshared.identity.roles import RoleStore
from teamshared.tenancy.repository import TenancyRepository


@dataclass(frozen=True)
class SignupResult:
    org_id: UUID
    owner_user_id: UUID
    api_key: MintedKey


async def signup_org(
    *,
    repo: TenancyRepository,
    api_keys: ApiKeyStore,
    roles: RoleStore,
    accounts: AccountStore,
    org_slug: str,
    org_name: str,
    owner_email: str,
    owner_name: str | None = None,
) -> SignupResult:
    owner_email = owner_email.strip().lower()
    account_id = await accounts.upsert(owner_email, owner_name)
    org = await repo.create_organization(org_slug, org_name)
    owner = await repo.create_user(org.id, owner_email, owner_name, account_id=account_id)
    await repo.add_membership(org.id, owner.id, role="org_owner")
    await roles.bind_role(
        org_id=org.id,
        principal_type="user",
        principal_id=owner.id,
        role_name="org_owner",
    )
    key = await api_keys.mint(
        org_id=org.id,
        principal_type="user",
        principal_id=owner.id,
        name="owner-bootstrap",
        created_by=owner.id,
    )
    return SignupResult(org_id=org.id, owner_user_id=owner.id, api_key=key)
