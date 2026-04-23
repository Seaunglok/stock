# `src/mcp_servers/financial_analysis_mcp` 코드 인덱스

금융 분석 도구를 제공하는 MCP 서버 모듈입니다.

## Breadcrumb

- 상위로: [mcp_servers](../code_index.md)
- 최상위: [src](../../code_index.md)

## 하위 디렉토리 코드 인덱스

- (하위 디렉토리 없음)

## 디렉토리 트리

```text
financial_analysis_mcp/
├── __init__.py
├── financial_client.py
└── server.py
```

## 각 파일 요약

- `__init__.py`: financial_analysis_mcp 패키지 초기화
- `financial_client.py`: 금융 데이터 API 클라이언트 - FinanceDataReader, 한국은행 API 통합
- `server.py`: FastMCP 서버 구현 - 재무 분석, 포트폴리오 최적화, 리스크 분석 도구 제공 (포트 8040)