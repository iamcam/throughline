# src/telemetry/setup.py
import logging
from src.config import Settings

logger = logging.getLogger(__name__)


def setup_telemetry(settings: Settings) -> None:
  if not settings.tracing_enabled:
    logger.debug("Tracing disabled — skipping telemetry setup")
    return

  from opentelemetry import trace
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.resources import Resource
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
  from openinference.instrumentation.openai import OpenAIInstrumentor

  resource = Resource(attributes={
    "openinference.project.name": settings.otel_project_name,
  })

  headers = {}
  if settings.otel_api_key:
    headers["Authorization"] = f"Bearer {settings.otel_api_key}"

  exporter = OTLPSpanExporter(
    endpoint=settings.otel_endpoint,
    headers=headers,
  )

  provider = TracerProvider(resource=resource)
  provider.add_span_processor(SimpleSpanProcessor(exporter))
  trace.set_tracer_provider(provider)

  OpenAIInstrumentor().instrument()

  logger.info(f"Tracing enabled — exporting to {settings.otel_endpoint} project={settings.otel_project_name}")