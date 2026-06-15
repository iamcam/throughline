# src/telemetry/tracer.py
from opentelemetry import trace

tracer = trace.get_tracer("podcast-engine")