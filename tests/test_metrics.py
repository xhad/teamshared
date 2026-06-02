"""Metrics registry exposition format."""

from __future__ import annotations

from teamshared.metrics import Metrics


def test_counter_and_render() -> None:
    m = Metrics()
    m.permission_denied.inc(permission="memory:create")
    m.permission_denied.inc(permission="memory:create")
    out = m.render()
    assert "teamshared_permission_denied_total" in out
    assert 'permission="memory:create"' in out
    assert "# TYPE teamshared_permission_denied_total counter" in out


def test_histogram_render_has_buckets() -> None:
    m = Metrics()
    m.retrieval_latency.observe(0.03)
    m.retrieval_latency.observe(1.2)
    out = m.render()
    assert "teamshared_retrieval_latency_seconds_bucket" in out
    assert 'le="+Inf"' in out
    assert "teamshared_retrieval_latency_seconds_count" in out


def test_gauge_set() -> None:
    m = Metrics()
    m.queue_depth.set(7, stream="distill")
    out = m.render()
    assert 'teamshared_queue_depth{stream="distill"} 7' in out


def test_cross_tenant_violation_starts_zero() -> None:
    m = Metrics()
    out = m.render()
    assert "teamshared_cross_tenant_violation_total 0" in out


def test_security_counters_render() -> None:
    m = Metrics()
    m.auth_rejected.inc(reason="invalid_token")
    m.otp_failed.inc()
    m.consent_denied_capture.inc(capability="tool_calls")
    m.ingestion_quarantined.inc(status="quarantined", reason="prompt_injection_suspected")
    out = m.render()
    assert "teamshared_auth_rejected_total" in out
    assert "teamshared_otp_failed_total" in out
    assert "teamshared_consent_denied_capture_total" in out
    assert "teamshared_ingestion_quarantined_total" in out
    m.rate_limited.inc()
    m.legacy_token_used.inc()
    out = m.render()
    assert "teamshared_rate_limited_total" in out
    assert "teamshared_legacy_token_used_total" in out
