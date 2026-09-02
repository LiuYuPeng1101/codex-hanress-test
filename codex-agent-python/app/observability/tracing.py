from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(service_name: str, otlp_endpoint: str | None) -> None:
    """按需配置 OpenTelemetry Trace。

    未配置 OTLP Endpoint 时不安装 exporter，本地开发仍可正常运行；配置后可把 Trace
    发送到 Langfuse、Phoenix、Grafana Tempo 等支持 OTLP 的后端。
    """

    if not otlp_endpoint:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)


def get_tracer():
    """返回 Agent Service 使用的 Tracer。"""

    return trace.get_tracer("codex-agent-python")
