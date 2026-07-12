FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev curl ca-certificates gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY README.md .
COPY protoforge/ protoforge/
# FIXED: 分开安装可选依赖和核心包，避免降级安装掩盖依赖错误
RUN pip install --no-cache-dir ".[opcua,mqtt,bacnet,s7,postgres,grpc]"

# FIXED: 优化 npm 依赖缓存 — 先复制 package.json 安装依赖，再复制源码构建
COPY web/package.json web/package-lock.json* web/
RUN cd web && npm ci || npm install

COPY web/ web/
RUN cd web && npm run build && cd .. && mkdir -p static && cp -r web/dist/* static/

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libffi8 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/protoforge/ protoforge/
COPY --from=builder /app/static/ static/
COPY alembic.ini .
COPY migrations/ migrations/

RUN mkdir -p data && \
    useradd -m -u 1000 protoforge && \
    chown -R protoforge:protoforge /app

USER protoforge

EXPOSE 8000 5020 4840 1883 5060 5060/udp 47808/udp 102 8080 5000 9600 44818 51340 8193 7878 1701 34964 34980
# GB28181 RTP 媒体流端口范围 (6000-6999/udp)，如需外部播放视频流请映射此范围
EXPOSE 6000-6999/udp

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -f http://localhost:8000/health || exit 1

# FIXED: 迁移失败时终止启动，避免静默忽略导致数据不一致
CMD ["sh", "-c", "alembic upgrade head && python -m protoforge.cli demo"]
