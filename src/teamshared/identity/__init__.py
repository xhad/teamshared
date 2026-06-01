"""First-class identities and RBAC.

Principals (users, agents, and the API keys that act on their behalf) are
modelled explicitly with org-scoped, least-privilege permissions. The
:class:`~teamshared.identity.rbac.Authorizer` resolves a principal's effective
permissions from role bindings, capped by any scopes the API key declares, and
exposes ``require`` for the before/after permission checks the retrieval and
write paths perform.
"""

from teamshared.identity.api_keys import ApiKeyStore, MintedKey
from teamshared.identity.principal import Principal, PrincipalType
from teamshared.identity.rbac import Authorizer, PermissionDenied, Permissions

__all__ = [
    "ApiKeyStore",
    "Authorizer",
    "MintedKey",
    "PermissionDenied",
    "Permissions",
    "Principal",
    "PrincipalType",
]
