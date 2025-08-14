FROM python:3.11-slim

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
    gcc \
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

# Copy application code
COPY src/ ./src/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash mcpuser && \
    chown -R mcpuser:mcpuser /app
USER mcpuser

# Set environment variables
ENV PYTHONPATH=/app

# Expose port for HTTP transport (optional)
EXPOSE 8989

# Run the FastMCP server
CMD ["python", "src/mcp_server.py"] 