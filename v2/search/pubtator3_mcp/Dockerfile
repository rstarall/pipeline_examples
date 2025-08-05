FROM python:3.11-slim

LABEL org.opencontainers.image.title="PubTator3 FastMCP Server"
LABEL org.opencontainers.image.description="FastMCP server for academic paper search via PubTator3 API"
LABEL org.opencontainers.image.version="1.0.0"

# Set working directory
WORKDIR /app

# Configure apt mirror if provided
ARG APT_MIRROR=""
RUN if [ -n "$APT_MIRROR" ]; then \
        echo "deb $APT_MIRROR/debian/ bookworm main" > /etc/apt/sources.list && \
        echo "deb $APT_MIRROR/debian/ bookworm-updates main" >> /etc/apt/sources.list && \
        echo "deb $APT_MIRROR/debian-security bookworm-security main" >> /etc/apt/sources.list; \
    fi

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Configure pip mirror if provided
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""

# Install Python dependencies
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i $PIP_INDEX_URL $([ -n "$PIP_TRUSTED_HOST" ] && echo "--trusted-host $PIP_TRUSTED_HOST") -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# Copy source code
COPY src/ ./src/

# Create non-root user
RUN useradd --create-home --shell /bin/bash mcp
RUN chown -R mcp:mcp /app
USER mcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8991/api/health || exit 1

# Expose port
EXPOSE 8991

# Set environment variables
ENV PORT=8991
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "src/mcp_server.py"]