FROM python:3.12-slim

# uv via pip is fine for the container build
RUN pip install --no-cache-dir uv

WORKDIR /workspace

# Copy workspace metadata + sources for the api and shared package
COPY pyproject.toml uv.lock* ./
COPY packages/shared ./packages/shared
COPY apps/api ./apps/api

RUN uv sync --package meaninggrid-api --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "--package", "meaninggrid-api", "uvicorn", "meaninggrid_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
