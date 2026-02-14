FROM python:3.12-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY cobot/ ./cobot/

# Install cobot with all extras
RUN pip install --no-cache-dir -e ".[all]"

# Create non-root user
RUN useradd -m -u 1000 cobot
USER cobot

# Default config location
ENV COBOT_CONFIG=/config/cobot.yml
ENV COBOT_WORKSPACE=/workspace

ENTRYPOINT ["cobot"]
CMD ["run"]
