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


resource = Resource.create({
    "service.name": "payment",
    "service.namespace": "demo-app",
})

provider = TracerProvider(resource=resource)

otlp_exporter = OTLPSpanExporter(
    endpoint="http://otel-collector.observability.svc.cluster.local:4317",
    insecure=True,
)

provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

app = FastAPI(title="IncidentLens Payment Service")

FastAPIInstrumentor.instrument_app(app)
Instrumentator().instrument(app).expose(app)

logger = configure_logging("payment")

PAYMENT_DELAY_MS = float(os.getenv("PAYMENT_DELAY_MS", "0"))


@app.get("/payment")
async def payment():
    if PAYMENT_DELAY_MS > 0:
        logger.info(
            "payment_delay_injected",
            extra={"delay_ms": PAYMENT_DELAY_MS},
        )
        await asyncio.sleep(PAYMENT_DELAY_MS / 1000.0)

    logger.info("payment_processed")

    return {
        "service": "payment",
        "status": "success",
    }


@app.get("/health")
def health():
    return {
        "service": "payment",
        "status": "healthy",
    }