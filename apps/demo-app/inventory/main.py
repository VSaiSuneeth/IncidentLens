import asyncio
import os

from common.logging_config import configure_logging
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Define resource attributes specifically for the inventory service
resource = Resource.create({
    "service.name": "inventory",
    "service.namespace": "demo-app",
})

# Configure the OpenTelemetry Tracer Provider
provider = TracerProvider(resource=resource)

# Configure the OTLP exporter to point to the Kubernetes OpenTelemetry Collector via gRPC
otlp_exporter = OTLPSpanExporter(
    endpoint="http://otel-collector.observability.svc.cluster.local:4317",
    insecure=True,
)

# Use BatchSpanProcessor for optimal production performance
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

# Initialize FastAPI Application
app = FastAPI(title="IncidentLens Inventory Service")

# Automatically instrument incoming/outgoing HTTP routing dependencies
FastAPIInstrumentor.instrument_app(app)
Instrumentator().instrument(app).expose(app)
logger = configure_logging("inventory")

INVENTORY_DELAY_MS = float(os.getenv("INVENTORY_DELAY_MS", "0"))


@app.get("/inventory")
async def inventory():
    logger.info("inventory_checked")
    if INVENTORY_DELAY_MS > 0:
        await asyncio.sleep(INVENTORY_DELAY_MS / 1000.0)

    return {
        "service": "inventory",
        "status": "available"
    }


@app.get("/health")
def health():
    return {
        "service": "inventory",
        "status": "healthy"
    }
