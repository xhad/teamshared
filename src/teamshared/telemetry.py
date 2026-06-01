"""Optional OpenTelemetry hooks.

Activated when ``opentelemetry-*`` is installed (``pip install '.[otel]'``)
*and* ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set. Imports are lazy so the base
install stays small.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from teamshared.logging import get_logger

if TYPE_CHECKING:
    from starlette.applications import Starlette

log = get_logger(__name__)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    """Start an OTel span if a tracer is configured; otherwise a no-op.

    Used to trace retrieval and background queue jobs end-to-end. Carrying
    ``org_id``/``trace_id`` attributes lets traces be correlated per tenant.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        yield
        return
    tracer = trace.get_tracer("teamshared")
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield


def setup_tracing(service_name: str = "teamshared") -> bool:
    """Wire up OTLP tracing if the env asks for it. Returns True if active.

    Configuration is by env vars (the OTel-standard ones):

    - ``OTEL_EXPORTER_OTLP_ENDPOINT``  -- e.g. ``http://localhost:4318``
    - ``OTEL_EXPORTER_OTLP_HEADERS``   -- e.g. ``"authorization=Bearer ..."``
    - ``OTEL_SERVICE_NAME``            -- overrides ``service_name`` arg

    Returns ``False`` silently if the OTel libs aren't installed or no
    endpoint is configured -- we don't want telemetry to be a hard dep.
    """
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.info("otel_libs_not_installed")
        return False

    name = os.environ.get("OTEL_SERVICE_NAME", service_name)
    provider = TracerProvider(resource=Resource.create({"service.name": name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    log.info("otel_tracing_enabled", service=name)
    return True


def instrument_asgi(app: Starlette) -> None:
    """Wrap an ASGI app with OTel HTTP middleware if available."""
    try:
        from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
    except ImportError:
        return
    app.add_middleware(OpenTelemetryMiddleware)
    log.info("otel_asgi_instrumented")
