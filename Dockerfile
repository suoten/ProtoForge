FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev nodejs npm && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY protoforge/ protoforge/
RUN pip install --no-cache-dir ".[all]"

COPY web/ web/
RUN cd web && npm install && npm run build && cd .. && mkdir -p static && cp -r web/dist/* static/

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/protoforge/ protoforge/
COPY --from=builder /app/static/ static/
COPY alembic.ini .
COPY migrations/ migrations/

RUN mkdir -p data

EXPOSE 8000 5020 4840 1883 5060 5060/udp 47808/udp 102 8080 5000 9600 44818 51340 8193 7878 1701 34964 34980

CMD ["sh", "-c", "alembic upgrade head || echo 'WARNING: Database migration failed, continuing with auto-create tables'; python -m protoforge.cli run"]
