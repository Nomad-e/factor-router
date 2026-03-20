FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Instala o uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependências — layer cacheada enquanto pyproject.toml e uv.lock não mudarem
COPY pyproject.toml ./
COPY uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Código fonte — muda frequentemente, vai para o fim
COPY src/ ./src/
COPY run.py ./

EXPOSE 8003

CMD ["uv", "run", "run.py"]