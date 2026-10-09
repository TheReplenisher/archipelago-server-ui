# One image, three services (web, worker, server); see DESIGN.md §2.
# Archipelago is run from source at a pinned tag, without its desktop GUI.

ARG AP_VERSION=0.6.8
ARG PYTHON_VERSION=3.12

# ---- frontend: platform-independent static files, so build once on the build host
FROM --platform=$BUILDPLATFORM node:24-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- python build stage: compilers and git are here, not in the final image
FROM python:${PYTHON_VERSION}-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

# web service
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/opt/apsui/venv uv sync --locked --no-dev --no-install-project
COPY backend/ ./
RUN UV_PROJECT_ENVIRONMENT=/opt/apsui/venv uv sync --locked --no-dev --no-editable

# Archipelago
ARG AP_VERSION
ADD --keep-git-dir=false https://github.com/ArchipelagoMW/Archipelago.git#${AP_VERSION} /opt/archipelago
COPY docker/install-archipelago.sh /usr/local/bin/
RUN uv venv /opt/archipelago-venv --python /usr/local/bin/python3 \
 && install-archipelago.sh /opt/archipelago /opt/archipelago-venv/bin/python \
 && /opt/archipelago-venv/bin/python -m compileall -q /opt/archipelago

# ---- runtime
FROM python:${PYTHON_VERSION}-slim-trixie
ARG AP_VERSION
LABEL org.opencontainers.image.title="Archipelago Server UI" \
      org.opencontainers.image.source="https://github.com/TheReplenisher/archipelago-server-ui" \
      org.opencontainers.image.licenses="MIT"

RUN groupadd --system --gid 10001 apsui \
 && useradd --system --uid 10001 --gid apsui --home-dir /data --no-create-home apsui \
 && install -d -o apsui -g apsui /data

COPY --from=build /opt/apsui/venv /opt/apsui/venv
COPY --from=build /opt/archipelago-venv /opt/archipelago-venv
COPY --from=build /opt/archipelago /opt/archipelago
COPY --from=frontend /src/frontend/dist /opt/apsui/static

ENV PATH=/opt/apsui/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APSUI_DATA_DIR=/data \
    APSUI_STATIC_DIR=/opt/apsui/static \
    ARCHIPELAGO_VERSION=${AP_VERSION} \
    SKIP_REQUIREMENTS_UPDATE=1

USER apsui
WORKDIR /data
EXPOSE 8000 38281 38282
CMD ["apsui-web"]
