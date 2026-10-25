# ---- Stage 1: Build ----
# Installs all dependencies (including C/Rust extensions) into a virtualenv.
FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS builder

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


# ---- Stage 2: Runtime (distroless) ----
# Only the installed packages and app code are copied — no compiler, no apt cache,
# no pip, no shell. The distroless image ships with Python 3.13.
FROM gcr.io/distroless/python3-debian13:nonroot@sha256:64e54c4b1200da244d80181d98e86fc01d73c8101f107d5baf472152d8e119a2

# Copy only the site-packages from the builder venv; distroless provides its
# own Python 3.13 binary so we do not need /venv/bin.
COPY --from=builder /venv/lib /venv/lib

COPY --chown=65532:65532 ./app /app
COPY --chown=65532:65532 entrypoint.py /entrypoint.py

WORKDIR /app

ARG GIT_SHA=dev
ENV GIT_HASH=${GIT_SHA}
ARG BUILD_TIMESTAMP=unknown
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=main:create_app()
# Point distroless Python at the packages installed in the builder stage.
ENV PYTHONPATH=/venv/lib/python3.13/site-packages

EXPOSE 8080

# distroless has no shell, so entrypoint.py replaces entrypoint.sh.
ENTRYPOINT ["/usr/bin/python3", "/entrypoint.py"]
