FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --target=/install -r requirements.txt packaging

FROM gcr.io/distroless/python3-debian12:nonroot

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/install

COPY --from=builder /install /install
COPY checkout ./checkout
COPY payment ./payment
COPY inventory ./inventory
COPY common ./common

EXPOSE 8000

ENTRYPOINT ["python3", "-m", "uvicorn"]