FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY checkout ./checkout
COPY payment ./payment
COPY inventory ./inventory
COPY common ./common

RUN useradd --create-home --shell /usr/sbin/nologin appuser

USER appuser

EXPOSE 8000

CMD ["uvicorn", "checkout.main:app", "--host", "0.0.0.0", "--port", "8000"]