"""모델 장부(paper) — 채택 구성이 무엇을 사고 팔았어야 하는지 매일 계산한다.

역할 (2026-08-28 라이브 재개로 변경)
------------------------------------
당초엔 '재개 전 사전 게이트'였다. 지금은 라이브가 돌고 있으므로 역할이 바뀌었다:
**라이브 실체결과 대조하는 기준선**이다.

백테스트는 항상 모델가 체결을 가정한다. 그 가정이 깨지는 곳(슬리피지·부분체결·거래정지·
유동성)은 실계좌에 넣어봐야 드러난다. 같은 규칙의 모델 장부를 매일 만들어 두면,
라이브가 실제로 낸 체결과 나란히 놓고 **그 괴리를 숫자로** 볼 수 있다.

**브로커를 전혀 호출하지 않는다.** 키움 MCP 를 쓰지 않으므로 주문이 나갈 경로 자체가 없다.
시세는 백테스트와 같은 소스(FDR 일봉)를 쓴다.

**증분 상태를 두지 않는다.** 매일 `paper_start ~ 오늘` 구간을 **검증 하니스로 통째로 재실행**해
현재 장부를 만든다. 이유:
  · 상태 파일 손상·유실이 조용한 오류가 되는 경로를 없앤다(08-17 state.json 사고와 같은 종류).
  · 결과가 결정적이라 언제 돌려도 같은 답이 나온다 — 재현 가능성이 곧 신뢰다.
  · 무엇보다 **검증에 쓴 코드와 같은 코드**다. 모의운용이 백테스트와 다른 로직으로 돌면
    그 결과는 아무것도 검증하지 못한다(이 프로젝트가 반복해 온 실패).

한계 — 검증하는 것과 못 하는 것
-------------------------------
검증한다: 규칙이 실제 시장에서 어떤 종목을 언제 사고 파는가, 그 빈도와 손익 분포.
검증 못 한다: 체결 슬리피지, 부분체결, 호가 공백. 진입은 익일 시가 가정이라 라이브의
11:00 진입과 시각이 다르다. **모의운용이 좋다고 실계좌가 같다는 뜻이 아니다.**

사용법
------
    python scripts/trend_paper.py                 # 현재 장부 + 누적 성과
    python scripts/trend_paper.py --detail        # 거래 내역까지
    python scripts/trend_paper.py --start 2026-08-28
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import backtest_trend_portfolio as P  # noqa: E402
from backtest_walkforward import Costs  # noqa: E402
from src.mcp_servers.trend_mcp import costs as C  # noqa: E402
from src.mcp_servers.trend_mcp.signals import TrendConfig  # noqa: E402

PAPER_START = "2026-08-28"          # 모델 장부 개시일(= 라이브 재개일)
DATA_START = "2015-01-01"           # 워밍업 포함 로드 구간
LOG_FILE = _ROOT / "data" / "trend_follow" / "paper_log.jsonl"


def _live_cfg() -> tuple[TrendConfig, dict]:
    """**라이브 설정을 그대로 읽는다.** 모의운용이 다른 값으로 돌면 검증이 아니다."""
    from trend_config import (BREADTH_MIN_PCT, CFG as LIVE, EXIT_MA, EXITS, HARD_STOP_PCT,
                              MAX_HOLD_DAYS, MAX_POS, POSITION_PCT, RANK_MODE, REGIME_MA,
                              SIZING_MODE)
    # `pct_equity` 와 `notional` 은 **같은 규칙의 다른 이름**이다(2026-08-28 동의어 확정).
    # 여기서 이름 하나만 받으면 라이브 설정을 그대로 읽는다는 이 함수의 전제가 깨진다 —
    # 실제로 라이브를 pct_equity 로 바꾼 직후 이 스크립트가 통째로 거부됐다.
    if SIZING_MODE not in ("notional", "pct_equity"):
        raise SystemExit(f"모델 장부는 예탁 비례 사이징 전제 — 현재 {SIZING_MODE}. "
                         "검증 구성과 다르면 결과를 신뢰할 수 없다.")
    cfg = TrendConfig(mode="largecap")
    cfg.ma_slow = EXIT_MA
    cfg.pullback_pct, cfg.pullback_min_pct = LIVE.pullback_pct, LIVE.pullback_min_pct
    cfg.atr_k, cfg.stop_pct = LIVE.atr_k, LIVE.stop_pct
    cfg.rr, cfg.partial_pct = LIVE.rr, LIVE.partial_pct
    cfg.max_hold = MAX_HOLD_DAYS
    return cfg, {
        "exits": tuple(EXITS), "max_pos": MAX_POS, "position_pct": POSITION_PCT,
        "hard_stop": HARD_STOP_PCT, "rank_mode": RANK_MODE,
        "regime_ma": REGIME_MA, "breadth_min": BREADTH_MIN_PCT, "exit_ma": EXIT_MA,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=PAPER_START)
    ap.add_argument("--detail", action="store_true", help="거래 내역 출력")
    ap.add_argument("--no-log", action="store_true", help="paper_log.jsonl 기록 생략")
    args = ap.parse_args()

    cfg, k = _live_cfg()
    costs = Costs(C.TAX_BPS, C.FEE_BPS, C.SLIPPAGE_BPS)
    dates, bars, _cl, _od = P._load(DATA_START, datetime.now().strftime("%Y-%m-%d"), 100)
    win = [d for d in dates if d >= args.start]
    if not win:
        print(f"구간에 영업일이 없다({args.start} 이후). 개시 전이거나 데이터 미갱신.")
        return 0

    P._SIG_MEMO.clear()
    res = P.simulate(DATA_START, dates[-1], 100, cfg, costs,
                     P.Sizing(mode="notional", position_pct=k["position_pct"]),
                     k["max_pos"], 0, "partial" in k["exits"], P._sector_map(),
                     hard_stop_pct=k["hard_stop"], rank_mode=k["rank_mode"],
                     regime_ma=k["regime_ma"], breadth_min=k["breadth_min"],
                     exits=k["exits"], sim_from=args.start, sim_to=dates[-1])
    m = P.pmetrics(res, res.n_days)

    exposure = k["max_pos"] * k["position_pct"]
    print("=" * 88)
    print(f"모델 장부 (paper) — {args.start} ~ {dates[-1]}  ({res.n_days} 영업일)")
    print("=" * 88)
    print(f"  구성  청산 {','.join(k['exits'])}(MA{k['exit_ma']}·{cfg.max_hold}일) · "
          f"하드손절 {k['hard_stop']:g}% · 슬롯 {k['max_pos']}×{k['position_pct']:g}% "
          f"(노출 {exposure:.0f}%) · 랭킹 {k['rank_mode']} · 레짐 MA{k['regime_ma']}")
    print("-" * 88)
    if not m.get("n"):
        print("  아직 자산곡선 없음")
        return 0
    print(f"  누적 {m['total']:+.2f}%   MDD {m['mdd']:.2f}%   진입 {m['entries']}건   "
          f"청산 {len(res.closed)}건   평균동시보유 {m['avg_conc']:.1f}")
    if res.closed:
        wins = [x for x in res.closed if x > 0]
        print(f"  청산 승률 {len(wins) / len(res.closed) * 100:.1f}%   "
              f"평균 {sum(res.closed) / len(res.closed):+.2f}%")
    if res.entry_dates:
        print(f"  최근 진입일 {res.entry_dates[-1]}  (총 {len(res.entry_dates)}건)")
    else:
        print("  진입 0건 — 레짐/breadth 게이트가 막고 있거나 후보 없음")
    if args.detail and res.closed:
        print("\n  청산 손익(%):  " + " ".join(f"{x:+.1f}" for x in res.closed[:40]))

    print("-" * 88)
    print("  ※ 브로커 미호출 — 주문 경로 없음. 시세는 백테스트와 동일 소스(FDR 일봉).")
    print("  ※ 진입은 익일 시가 가정 — 라이브 11:00 진입과 시각이 다르다.")
    print("  ※ 슬리피지·부분체결·호가공백은 여기서 검증되지 않는다 —")
    print("     그게 라이브 실체결과 이 장부를 대조하는 이유다.")

    if not args.no_log:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now().isoformat(timespec="seconds"),
               "asof": dates[-1], "start": args.start, "days": res.n_days,
               "total_pct": round(m["total"], 4), "mdd_pct": round(m["mdd"], 4),
               "entries": m["entries"], "closed": len(res.closed),
               "exits": list(k["exits"]), "max_pos": k["max_pos"],
               "position_pct": k["position_pct"]}
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  기록: {LOG_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
