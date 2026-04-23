# Stage 1: Build the frontend assets
FROM node:18-alpine AS frontend-builder
WORKDIR /app

# Copy package files and configuration needed for npm ci
COPY a2a-inspector/frontend/package*.json ./
COPY a2a-inspector/frontend/tsconfig.json ./
COPY a2a-inspector/frontend/src ./src

# Install dependencies (this will run prepare script which needs tsconfig.json and src/)
RUN npm ci

# Copy remaining files
COPY a2a-inspector/frontend/ ./

# Rebuild native dependencies like esbuild for the container's architecture (Alpine)
# in case host node_modules were copied over.
RUN npm rebuild esbuild

RUN npm run build

# Stage 2: Build the final application with the backend
# pyproject.toml이 requires-python >= 3.12를 요구하므로 3.12 사용
FROM python:3.12-slim
WORKDIR /app

# cffi/cryptography 빌드에 필요한 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv
COPY a2a-inspector/pyproject.toml a2a-inspector/uv.lock ./
# Python 3.12를 명시적으로 지정하여 uv가 다른 버전을 찾지 않도록 함
RUN uv sync --no-cache --python 3.12
RUN uv pip install validators
COPY a2a-inspector/backend/ ./backend/
RUN mkdir -p /app/frontend
COPY --from=frontend-builder /app/public /app/frontend/public


WORKDIR /app/backend

# Expose the port the backend server runs on
EXPOSE 8080

# The command to run the server. Because our WORKDIR is now /app/backend,
# we can simply refer to 'app:app' from the current directory.git 
CMD ["uv", "run", "--", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]