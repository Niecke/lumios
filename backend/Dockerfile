# ---- Stage 1: Build ----
# Installs all dependencies (including C/Rust extensions) into a virtualenv.
FROM python:3.14.9-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS builder

WORKDIR /build

# Build tools required for argon2-cffi and cryptography (C/Rust extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17@sha256:e4644cb5bd56fdc2c5ea3ee0525d9d21eed1603bccd6a21f887a938be7e85be1 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock .python-version .
RUN uv sync --no-install-project --frozen


# ---- Stage 2: Runtime (python-slim, non-root) ----
# Same interpreter as the builder, so the C extensions in the venv match. The
# distroless image is frozen on the Python of Debian 13 (3.13) and cannot run them.
FROM python:3.14.9-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8

# The chart runs /usr/bin/python3 (migrate job, cleanup cronjob); python-slim
# installs the interpreter in /usr/local/bin. pip is not needed at runtime.
RUN ln -s /usr/local/bin/python3 /usr/bin/python3 \
    && ln -s /usr/local/bin/python3 /usr/bin/python \
    && python -m pip uninstall --yes --root-user-action=ignore pip \
    && groupadd --gid 65532 nonroot \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin nonroot

COPY --from=builder /venv /venv

COPY --chown=65532:65532 ./app /app
COPY --chown=65532:65532 entrypoint.py /entrypoint.py

WORKDIR /app

ARG GIT_SHA=dev
ENV GIT_HASH=${GIT_SHA}
ARG BUILD_TIMESTAMP=unknown
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV FLASK_APP=main:create_app()
ENV PATH="/venv/bin:$PATH"
# The minor version must follow .python-version.
ENV PYTHONPATH=/venv/lib/python3.14/site-packages

USER 65532:65532

EXPOSE 8080

ENTRYPOINT ["/usr/bin/python3", "/entrypoint.py"]
