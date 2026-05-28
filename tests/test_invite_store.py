"""InviteStore unit tests."""

from __future__ import annotations

from pathlib import Path

from teamshared.invite import InviteStore


def test_create_and_redeem(tmp_path: Path) -> None:
    store = InviteStore(tmp_path / "invites.json")
    record = store.create(agent="cursor", uses=2)
    peek = store.get(record.code)
    assert peek is not None
    assert peek.uses_left == 2
    redeemed = store.redeem(record.code)
    assert redeemed is not None
    assert redeemed.uses_left == 1
    assert store.get(record.code) is not None
    store.redeem(record.code)
    assert store.get(record.code) is None


def test_list_skips_exhausted(tmp_path: Path) -> None:
    store = InviteStore(tmp_path / "invites.json")
    record = store.create(uses=1)
    assert len(store.list_invites()) == 1
    store.redeem(record.code)
    assert store.list_invites() == []
