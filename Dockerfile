FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY protoforge/ protoforge/
RUN pip install --no-cache-dir ".[all]"

COPY alembic.ini .
COPY migrations/ migrations/

RUN mkdir -p static data

EXPOSE 8000 5020 4840 1883 5060 5060/udp 47808/udp 102 8080 5000 9600 44818 51340 8193 7878 1701 34964 34980

CMD ["python", "-m", "protoforge.cli", "run"]
