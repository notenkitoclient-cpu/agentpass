FROM python:3.13-slim
WORKDIR /app

# Install dependencies first for layer-cache efficiency
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir uvicorn

# Copy examples after dependencies are cached
COPY examples/ examples/

ENV PYTHONPATH=/app/src
