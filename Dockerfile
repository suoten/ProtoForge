FROM node:20-slim AS frontend-builder
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY protoforge/ protoforge/

COPY --from=frontend-builder /app/web/dist /app/static

RUN pip install --no-cache-dir -e ".[all]"

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000 5020 4840 1883 5060/udp 47808/udp 102

CMD ["python", "-m", "uvicorn", "protoforge.main:app", "--host", "0.0.0.0", "--port", "8000"]
