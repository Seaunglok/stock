# `src` 코드 인덱스

키움 **종가매매(closing-bet) 자동매매** 시스템의 소스 루트. 구 A2A 멀티에이전트 플랫폼
(`lg_agents`/`claude_agents` 실행기 · `a2a_agents` · `a2a_integration`)은 2026-06 제거됐다.
현재는 **FastMCP 서버 묶음** + 그걸 호출하는 **standalone 종가매매 데몬**(`scripts/direct_closing_bet.py`)
구조다.

## 하위 인덱스

- [mcp_servers](mcp_servers/code_index.md) — FastMCP 서버 생태계 (도메인 도구)
- [mcp_servers/kiwoom_mcp/domains](mcp_servers/kiwoom_mcp/domains/code_index.md) — 키움 5개 도메인

## 디렉터리 트리

```bash
src/
├── __init__.py
├── code_index.md                     # 이 문서
│
├── claude_agents/                    # 구 멀티에이전트 패키지 — MCP 클라이언트만 잔존
│   └── base/
│       ├── mcp_client.py             # ★ MCPManager — 종가매매 데몬이 MCP 서버 호출에 사용하는 유일 모듈
│       └── __init__.py
│
└── mcp_servers/                      # FastMCP 서버 (각각 독립 실행: python -m src.mcp_servers.<X>)
    ├── base/base_mcp_server.py       # BaseMCPServer / StandardResponse — 전 서버의 기반 클래스
    ├── common/                       # 서버 공통: auth(키움), clients(BaseHTTPClient), concerns(cache/metrics/rate_limit), middleware(cors/logging/error)
    ├── utils/                        # env_validator, formatters, market_time, serialization, validators 등
    │
    ├── kiwoom_mcp/                    # 키움증권 도메인 서버
    │   ├── common/
    │   │   ├── client/kiwoom_restapi_client.py   # ★ 키움 REST 통합 클라이언트 (OAuth 토큰·공유캐시·8005 자동복구)
    │   │   ├── domain_base.py                     # KiwoomDomainServer
    │   │   └── constants/{api_types,endpoints,api_loader}.py + api_registry/kiwoom_api_registry.yaml
    │   └── domains/
    │       ├── trading_domain.py     # :8030 주문/계좌 (place_buy/sell_order, get_order_executions, get_account_evaluation 등)
    │       ├── market_domain.py      # :8031 시세/차트
    │       ├── info_domain.py        # :8032 종목정보/ETF/테마
    │       ├── investor_domain.py    # :8033 외국인/기관 동향
    │       └── portfolio_domain.py   # :8034 보유/평가/리스크
    │
    ├── closing_bet_mcp/              # :8060 종가매매 채점·청산 (순수 함수 — 데몬이 직접 임포트)
    │   ├── scorer.py                  # 기술 점수(volume/resistance/candle/consolidation/institutional) + DART 공시 catalyst
    │   ├── catalyst.py                # 뉴스 트렌드 키워드 매칭(match_trends) — 동적 테마 주입 가능
    │   ├── exit_rules.py              # evaluate_hold_exit(ATR 트레일)/evaluate_exit/classify_regime/market_filter
    │   └── server.py                  # FastMCP 도구 노출 (대시보드/UI용)
    │
    ├── financial_analysis_mcp/       # :8040 재무 분석
    ├── stock_analysis_mcp/           # :8042 기술적 분석
    ├── naver_news_mcp/               # :8050 뉴스 (search_news_articles)
    ├── tavily_search_mcp/            # :3020 웹 검색
    └── macroeconomic_analysis_mcp/   # :8041 매크로 지표
```

## 포트 매핑

| 서버 | 포트 | 역할 |
|------|------|------|
| trading-domain | 8030 | 주문/계좌 |
| kiwoom-market | 8031 | 시세/차트 |
| kiwoom-info | 8032 | 종목 정보 |
| investor-domain | 8033 | 투자자 동향 |
| portfolio-domain | 8034 | 포트폴리오/리스크 (reconcile 보유분 조회) |
| financial-analysis | 8040 | 재무 분석 |
| macroeconomic-analysis | 8041 | 매크로 지표 |
| stock-analysis | 8042 | 기술적 분석 |
| naver-news | 8050 | 뉴스 |
| tavily-search | 3020 | 웹 검색 |
| closing-bet | 8060 | 종가매매 채점/청산 규칙 (직접 임포트도 가능) |

## 실행/운영

- MCP 서버 기동: `python run_mcp_local.py start` (헬스: `python check_status.py`)
- 종가매매 데몬: `python scripts/direct_closing_bet.py --daemon` (전략·운영 상세는 [docs/closing_bet_strategy.md](../docs/closing_bet_strategy.md), 프로젝트 지침은 `.claude/CLAUDE.md`)
- 회귀 테스트: `python -m pytest tests/ -q`

> 종가매매 데몬은 MCP 서버만 떠 있으면 동작한다(A2A/Claude SDK 불필요). closing_bet_mcp 의
> 채점/청산은 순수 함수라 데몬이 서버 없이 직접 임포트하고, 주문/시세/보유분만 MCP로 호출한다.
