FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /workspace

COPY pyproject.toml uv.lock* ./
COPY packages/shared ./packages/shared
COPY apps/worker ./apps/worker

RUN uv sync --package meaninggrid-worker --frozen --no-dev

CMD ["uv", "run", "--package", "meaninggrid-worker", "python", "-m", "meaninggrid_worker.main"]
