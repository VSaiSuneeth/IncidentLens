# from fastapi import FastAPI

# app = FastAPI(title="IncidentLens Payment Service")


# @app.get("/payment")
# def payment():
#     return {
#         "service": "payment",
#         "status": "success"
#     }


# @app.get("/health")
# def health():
#     return {
#         "service": "payment",
#         "status": "healthy"
#     }

import logging

from common.logging_config import configure_logging
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Define resource attributes for OpenTelemetry
resource = Resource.create({
    "service.name": "payment",
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
app = FastAPI(title="IncidentLens Payment Service")

# Automatically instrument incoming/outgoing HTTP routing dependencies
FastAPIInstrumentor.instrument_app(app)
logger = configure_logging("payment")


@app.get("/payment")
def payment():
    logger.info("payment_processed")

    return {
        "service": "payment",
        "status": "success"
    }


@app.get("/health")
def health():
    return {
        "service": "payment",
        "status": "healthy"
    }
