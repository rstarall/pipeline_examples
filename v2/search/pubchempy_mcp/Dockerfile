FROM python:3.11-slim

# 添加镜像选择变量，默认使用官方镜像
ARG USE_CN_MIRRORS=false

# Set working directory
WORKDIR /app

# 根据变量选择性地配置 apt 源和安装系统依赖
RUN if [ "$USE_CN_MIRRORS" = "true" ]; then \
        # 使用中国镜像源
        sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
        sed -i 's/security.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources; \
    fi && \
    apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# 根据变量选择性地配置 pip 源并安装 Python 依赖
RUN if [ "$USE_CN_MIRRORS" = "true" ]; then \
        # 使用中国 pip 镜像源
        pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
        pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn; \
    fi && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash mcpuser && \
    chown -R mcpuser:mcpuser /app
USER mcpuser

# Set environment variables
ENV PYTHONPATH=/app
ENV LOG_LEVEL=info

# Run the MCP server
CMD ["python", "-m", "src.mcp_server"] 