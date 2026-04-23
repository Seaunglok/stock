# A2A Expert Agents를 위한 공통 Dockerfile
FROM python:3.12-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# uv 설치 (공식 설치 스크립트 사용)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Python 의존성 파일 복사
# Note: build context가 프로젝트 루트(../../)이므로 상대 경로 사용
COPY pyproject.toml uv.lock ./

# uv sync로 의존성 설치 (lock 파일 기반 재현 가능한 설치)
RUN uv sync --frozen --no-dev

# 소스코드 복사
COPY src ./src

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV AGENT_TYPE=""
ENV AGENT_HOST="0.0.0.0"
ENV AGENT_PORT="8000"

# 실행 사용자 생성 (보안)
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

# 기본 포트 노출
EXPOSE 8000

# uv로 생성된 가상환경의 Python 사용
CMD ["sh", "-c", "uv run python -m src.a2a_agents.${AGENT_TYPE:-supervisor}.__main__"]
