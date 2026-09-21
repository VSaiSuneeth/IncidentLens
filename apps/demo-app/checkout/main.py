# from fastapi import FastAPI
# import urllib.request
# import json

# app = FastAPI(title="IncidentLens Checkout Service")


# PAYMENT_URL = "http://127.0.0.1:8001/payment"
# INVENTORY_URL = "http://127.0.0.1:8002/inventory"


# def call_service(url: str):
#     with urllib.request.urlopen(url, timeout=2) as response:
#         return json.loads(response.read().decode())


# @app.get("/checkout")
# def checkout():
#     payment_result = call_service(PAYMENT_URL)
#     inventory_result = call_service(INVENTORY_URL)

#     return {
#         "service": "checkout",
#         "status": "success",
#         "payment": payment_result,
#         "inventory": inventory_result
#     }


# @app.get("/health")
# def health():
#     return {
#         "service": "checkout",
#         "status": "healthy"
#     }

from fastapi import FastAPI
import httpx
import logging

from common.logging_config import configure_logging
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor


resource = Resource.create({
    "service.name": "checkout",
    "service.namespace": "demo-app",
})

provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(
    endpoint="http://otel-collector.observability.svc.cluster.local:4317",
    insecure=True,
)

provider.add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

trace.set_tracer_provider(provider)

app = FastAPI(title="IncidentLens Checkout Service")

FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()
logger = configure_logging("checkout")


PAYMENT_URL = "http://payment:8001/payment"
INVENTORY_URL = "http://inventory:8002/inventory"


@app.get("/checkout")
async def checkout():
    logger.info("checkout_started")

    async with httpx.AsyncClient(timeout=2.0) as client:
        payment_response = await client.get(PAYMENT_URL)
        logger.info("payment_completed")

        inventory_response = await client.get(INVENTORY_URL)
        logger.info("inventory_completed")

    logger.info("checkout_completed")

    return {
        "service": "checkout",
        "status": "success",
        "payment": payment_response.json(),
        "inventory": inventory_response.json(),
    }


@app.get("/health")
def health():
    return {
        "service": "checkout",
        "status": "healthy"
    }