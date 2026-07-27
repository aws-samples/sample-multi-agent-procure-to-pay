# syntax=docker/dockerfile:1.7
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Base image hosted on Amazon ECR Public (Docker Hub mirror) — required for
# public sample content per AWS guidance, since internal ECR is not reachable
# by external customers. See https://gallery.ecr.aws/docker/library/python.
#
# Pinned by digest for reproducibility. To refresh:
#   finch pull public.ecr.aws/docker/library/python:3.13-slim-bookworm
#   finch image inspect public.ecr.aws/docker/library/python:3.13-slim-bookworm \
#     --format '{{json .RepoDigests}}'
#
# Build for ARM64 with buildx (target platform for AWS Graviton / AgentCore):
#   docker buildx build --platform linux/arm64 -t aria-p2p-agent:latest .
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:e4fa1f978c539608a10cdf74700ac32a3f719dfc6e8b6b6001da82deb36302a2

# Create a non-root user to run the application (CKV_DOCKER_3).
RUN groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --home-dir /app --shell /sbin/nologin app

WORKDIR /app

# Install uv for fast, reproducible Python dependency installation.
RUN pip install --no-cache-dir uv==0.5.4

# Copy dependency file first for layer caching.
COPY requirements.txt .

# Install dependencies into the system site-packages so the non-root user can
# import them. Application code itself is owned by the non-root user.
# nosemgrep -- missing-pip-no-cache-dir: sample Dockerfile; image size is not a concern here
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application code with non-root ownership.
COPY --chown=app:app agentcore_app.py .
COPY --chown=app:app workflow/ workflow/
COPY --chown=app:app config.py .
COPY --chown=app:app config/ config/
COPY --chown=app:app agents/ agents/
COPY --chown=app:app adapters/ adapters/
COPY --chown=app:app services/ services/
COPY --chown=app:app utils/ utils/

# Drop privileges (CKV_DOCKER_3).
USER app

# AgentCore Runtime port.
EXPOSE 8080

# Liveness probe (CKV_DOCKER_2). The AgentCore Runtime exposes /ping by
# convention; falls back to a simple TCP-style python check.
# nosemgrep -- prefer-json-notation: readable form preferred for a sample Dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/ping', timeout=3); sys.exit(0)" \
      || exit 1

# Run the AgentCore app.
CMD ["python", "agentcore_app.py"]
