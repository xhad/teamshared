"""PlanPublisher: S3-compatible bucket mirroring with a mocked boto3 client.

The boto3 S3 client is injected via ``client_factory`` so tests never touch the
network or require the boto3 package at import time.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from teamshared.storage.bucket import PlanPublisher, build_plan_publisher


def _make_mock_client():
    client = MagicMock()
    client.put_object = MagicMock()
    paginator = MagicMock()
    page = {"Contents": [{"Key": "tok/v1.html"}, {"Key": "tok/index.html"}]}
    paginator.paginate.return_value = [page]
    client.get_paginator.return_value = paginator
    client.delete_objects = MagicMock()
    return client


def _publisher_with_mock_client():
    client = _make_mock_client()
    publisher = PlanPublisher(
        endpoint="https://s3.example.test",
        bucket="plans",
        access_key="ak",
        secret_key="sk",
        region="us-east-1",
        public_base_url="https://plans.example.test",
        client_factory=lambda *a, **kw: client,
    )
    return publisher, client


def test_publish_html_puts_version_and_index() -> None:
    publisher, client = _publisher_with_mock_client()
    asyncio.run(publisher.publish_html("tok", 3, "<h1>hi</h1>"))

    calls = client.put_object.call_args_list
    assert len(calls) == 2
    keys = [c.kwargs["Key"] for c in calls]
    assert "tok/v3.html" in keys
    assert "tok/index.html" in keys
    # Both bodies are the utf-8 encoded html.
    for c in calls:
        assert c.kwargs["Body"] == b"<h1>hi</h1>"
        assert c.kwargs["ContentType"] == "text/html; charset=utf-8"


def test_unpublish_deletes_prefix() -> None:
    publisher, client = _publisher_with_mock_client()
    asyncio.run(publisher.unpublish("tok"))

    client.get_paginator.assert_called_once_with("list_objects_v2")
    paginator = client.get_paginator.return_value
    paginator.paginate.assert_called_once_with(Bucket="plans", Prefix="tok/")
    client.delete_objects.assert_called_once()
    delete_payload = client.delete_objects.call_args.kwargs["Delete"]
    assert delete_payload["Objects"] == [
        {"Key": "tok/v1.html"}, {"Key": "tok/index.html"}
    ]


def test_public_url_uses_base_and_version() -> None:
    publisher, _ = _publisher_with_mock_client()
    assert publisher.public_url("tok") == "https://plans.example.test/tok/index.html"
    assert publisher.public_url("tok", 2) == "https://plans.example.test/tok/v2.html"


def test_public_url_none_without_base() -> None:
    client = _make_mock_client()
    publisher = PlanPublisher(
        endpoint="https://s3.example.test",
        bucket="plans",
        access_key="ak",
        secret_key="sk",
        client_factory=lambda *a, **kw: client,
    )
    assert publisher.public_url("tok") is None
    assert publisher.public_url("tok", 2) is None


def test_build_plan_publisher_none_when_unconfigured() -> None:
    settings = MagicMock()
    settings.object_storage_endpoint = None
    settings.object_storage_bucket = "b"
    settings.object_storage_access_key = "k"
    settings.object_storage_secret_key = "s"
    settings.object_storage_region = None
    settings.object_storage_public_base_url = None
    assert build_plan_publisher(settings) is None


def test_build_plan_publisher_builds_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_mock_client()
    monkeypatch.setattr(
        "teamshared.storage.bucket._client_factory",
        lambda *a, **kw: client,
    )
    settings = MagicMock()
    settings.object_storage_endpoint = "https://s3.example.test"
    settings.object_storage_bucket = "plans"
    settings.object_storage_access_key = "ak"
    settings.object_storage_secret_key = "sk"
    settings.object_storage_region = "us-east-1"
    settings.object_storage_public_base_url = "https://plans.example.test"
    publisher = build_plan_publisher(settings)
    assert publisher is not None
    assert publisher.public_base_url == "https://plans.example.test"


def test_build_plan_publisher_partial_config_returns_none() -> None:
    settings = MagicMock()
    settings.object_storage_endpoint = "https://s3.example.test"
    settings.object_storage_bucket = None  # missing bucket
    settings.object_storage_access_key = "ak"
    settings.object_storage_secret_key = "sk"
    settings.object_storage_region = None
    settings.object_storage_public_base_url = None
    assert build_plan_publisher(settings) is None
