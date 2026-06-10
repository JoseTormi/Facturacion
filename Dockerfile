FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install .

EXPOSE 8000

CMD uvicorn invoice_automation.api:app --host 0.0.0.0 --port ${PORT:-8000}
