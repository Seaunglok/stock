# closing_bet 가중치 재산정 결과 (rolling universe)

- 실행 시각: 2026-05-05 21:10:33
- 기간: 2025-06-01 ~ 2026-04-30
- 마스터 풀 100종목 → 매일 거래대금 상위 50 (window 5일)
- 회귀 샘플 6700건
- 백테스트 비교 조건: 임계값 50.0 / top_n 5

## 1. OLS 회귀 결과 (ret% ~ 4 sub-components)

- R² = 0.0131
- 절편 = +1.4392

| sub-component | 회귀계수 | 부호 |
|---------------|----------|------|
| volume_surge | +0.01210 | + |
| resistance_proximity | -0.00737 | - |
| candle_shape | -0.00255 | - |
| consolidation | -0.00638 | - |
| catalyst | -0.00454 | - |

> 음수 계수는 "점수가 높을수록 수익이 낮다" — 현재 합산식의 노이즈/역신호.

## 2. 신규 가중치 제안 (음수 클리핑 → 합=1 정규화)

| sub-component | 기존 | 신규 | 변화 |
|---------------|------|------|------|
| volume_surge | 0.250 | 1.000 | +0.750 |
| resistance_proximity | 0.200 | 0.000 | -0.200 |
| candle_shape | 0.150 | 0.000 | -0.150 |
| consolidation | 0.200 | 0.000 | -0.200 |
| catalyst | 0.000 | 0.000 | +0.000 |

## 3. 백테스트 비교

| 가중치 | 픽 수 | 승률 | 평균수익 |
|--------|-------|------|----------|
| 기존 | 455 | 52.3% | +0.73% |
| 신규 | 310 | 57.1% | +1.19% |

## 4. 적용 방법

`src/mcp_servers/closing_bet_mcp/scorer.py` `TechnicalScores.composite()`:
```python
def composite(self) -> float:
    return (
          self.volume_surge * 1.000
        + self.resistance_proximity * 0.000
        + self.candle_shape * 0.000
        + self.consolidation * 0.000
        + self.catalyst * 0.000
        + self.institutional * 0.0  # 백테스트 데이터 없음, 운영시 별도 가중
    )
```

> institutional은 백테스트에 없어 회귀에서 빠졌다. 운영(실시간) 단계에서는
> 외인/기관 데이터가 들어오므로 별도 가중(예: 0.15)을 추가하거나, 4개 컴포넌트
> 합산 후 institutional 가산점 형태로 분리하는 것을 권한다.