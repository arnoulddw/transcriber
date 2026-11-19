# ./Dockerfile
# Defines the Docker image build process

# ---------------------------------------------------------------------------
# Stage 1: build the Tailwind CSS bundle.
# Node.js is only needed at build time, so it stays in this stage and never
# ships in the final image.
# ---------------------------------------------------------------------------
FROM node:22-trixie-slim AS css-builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY tailwind.config.js postcss.config.js ./
COPY app/templates ./app/templates
COPY app/static ./app/static
RUN npm run build:css:prod

# ---------------------------------------------------------------------------
# Stage 2: static FFmpeg build.
# Debian's ffmpeg package drags in ~100 shared libraries (codecs, X11, krb5,
# libxml2, ...) that carry many unfixed CVEs. A static build of current FFmpeg
# gives us just the two binaries the app calls: ffmpeg and ffprobe.
# ---------------------------------------------------------------------------
FROM mwader/static-ffmpeg:8.1.1 AS ffmpeg

# ---------------------------------------------------------------------------
# Stage 3: runtime image.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-trixie

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=UTC
ARG BUILD_TIMESTAMP
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Install system dependencies and pull in any pending security updates:
# - tini: Minimal init system
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends tini && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ffmpeg/ffprobe: duration inspection and streaming audio segmentation
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/

# The app does not need setuptools/wheel at runtime; removing them (and the
# bundled ensurepip wheels) drops their vendored, vulnerable dependencies.
# pip is upgraded to the latest release.
RUN pip install --no-cache-dir --upgrade pip && \
    (pip uninstall -y setuptools wheel || true) && \
    rm -rf /usr/local/lib/python3.11/ensurepip/_bundled

# Create a non-root user and group for security
# Set home directory to /app
RUN groupadd -r appuser && useradd --no-log-init -r -g appuser -d /app -s /sbin/nologin -c "App User" appuser

# Create necessary directories and set base ownership
# These directories are for runtime data and logs, which might be mounted as volumes.
RUN mkdir -p /app/uploads /app/database /app/logs /app/runtime && \
    chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser
WORKDIR /app

# Copy Python requirements file and install Python dependencies
COPY --chown=appuser:appuser ./requirements.txt ./
# Install Python packages for the appuser. This will install to /app/.local
RUN pip install --no-cache-dir --user -r requirements.txt
# Prepend the user's local bin directory to PATH
ENV PATH="/app/.local/bin:${PATH}"

# Copy the application source code (see .dockerignore for what is excluded)
COPY --chown=appuser:appuser . .

# Bring in the compiled Tailwind CSS from the build stage
COPY --from=css-builder --chown=appuser:appuser /build/app/static/css/tailwind_output.css ./app/static/css/tailwind_output.css

# Ensure entrypoint script is executable
RUN chmod +x /app/docker-entrypoint.sh

# Compile translation files
RUN /app/.local/bin/pybabel compile -d app/translations

# Persist the image build time for the footer/version banner.
RUN if [ -n "${BUILD_TIMESTAMP}" ]; then \
        printf '%s\n' "${BUILD_TIMESTAMP}" > /app/build_timestamp; \
    else \
        date -u '+%Y-%m-%d %H:%M:%S UTC' > /app/build_timestamp; \
    fi

# Set default Flask app for CLI commands
ENV FLASK_APP=app

# Expose the port the application will run on
EXPOSE 5004

# Use Tini as the entrypoint
ENTRYPOINT ["/usr/bin/tini", "--"]

# Define the default command to run the bootstrap script, which will launch Gunicorn
CMD ["/app/docker-entrypoint.sh"]
