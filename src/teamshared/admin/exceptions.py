"""Admin data-portability and erasure errors."""

from __future__ import annotations

from uuid import UUID


class ExportTooLarge(Exception):
    """Org export exceeds configured ``export_max_items``."""

    def __init__(self, count: int, limit: int) -> None:
        self.count = count
        self.limit = limit
        super().__init__(f"export has {count} items; limit is {limit}")


class UserNotInOrg(Exception):
    """Target user is not an active member of the org."""

    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        super().__init__(f"user {user_id} is not a member of this org")


class SelfErasureBlocked(Exception):
    """Actor cannot purge their own memory via admin erasure."""

    def __init__(self) -> None:
        super().__init__("cannot purge your own user memory; use account deletion flow")


class ErasureNotConfirmed(Exception):
    """Destructive erasure requires explicit confirmation."""

    def __init__(self) -> None:
        super().__init__(
            "confirmation required: set confirm=true in JSON body or "
            "X-Confirm-Erasure: 1 header"
        )
