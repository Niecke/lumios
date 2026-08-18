# ---- Stage 1: Build ----
# Installs all dependencies (including C/Rust extensions) into a virtualenv.
FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a AS builder

WORKDIR /build

# Build tools required for argon2-cffi and cryptography (C/Rust extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock .python-version .
RUN uv sync --no-install-project --frozen


# ---- Stage 2: Runtime (distroless) ----
# Only the installed packages and app code are copied — no compiler, no apt cache,
# no pip, no shell. The distroless image ships with Python 3.13.
FROM gcr.io/distroless/python3-debian13:nonroot@sha256:eff0a6050f5ea9e8154c3d137d468901864803ce3c7f4657d419e64f3f1f8b40

# Copy only the site-packages from the builder venv; distroless provides its
# own Python 3.13 binary so we do not need /venv/bin.
COPY --from=builder /venv/lib /venv/lib

COPY --chown=65532:65532 ./app /app
COPY --chown=65532:65532 entrypoint.py /entrypoint.py

WORKDIR /app

ARG GIT_SHA=dev
ENV GIT_HASH=${GIT_SHA}
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=main:create_app()
# Point distroless Python at the packages installed in the builder stage.
ENV PYTHONPATH=/venv/lib/python3.13/site-packages

EXPOSE 8080

# distroless has no shell, so entrypoint.py replaces entrypoint.sh.
ENTRYPOINT ["/usr/bin/python3", "/entrypoint.py"]
