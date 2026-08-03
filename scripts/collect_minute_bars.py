"""분봉 수집·분석 — 진입 **시각**(09:30 vs 11:00) 검증용 데이터 축적.

배경: 일봉 백테스트는 '익일 시가' 진입만 모델링할 수 있어, 2026-08 채택한 11:00 진입이
09:30 대비 유리한지 검증할 방법이 없다(장중 시각 가격이 일봉에 없음). 키움 ka10080
5분봉은 **약 12영업일치(900봉)** 를 주므로, 매일 수집해 쌓으면 시각별 체결가 비교가 가능해진다.

수집 대상: 보유 종목 + 당일 screen 후보(= 실제 진입 판단이 일어난 종목).
저장: data/trend_follow/minute/<YYYY-MM-DD>/<code>.json  (일자별 분리 = 멱등·증분)

사용:
  python scripts/collect_minute_bars.py --auto              # 보유+후보 자동 수집(장 마감 후)
  python scripts/collect_minute_bars.py --codes 005930,000660
  python scripts/collect_minute_bars.py --analyze           # 쌓인 데이터로 시각별 비교
  python scripts/collect_minute_bars.py --analyze --times 09:30,10:00,11:00,13:00
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from trend_config import DATA_DIR, MARKET_URL, logger  # noqa: E402

MINUTE_DIR = DATA_DIR / "minute"
INTERVAL = 5           # 5분봉 — 09:30/11:00 등 정각 시각을 정확히 집어낼 수 있는 최소 해상도
_FIELDS = ("open_pric", "high_pric", "low_pric", "cur_prc", "trde_qty")


def _num(v) -> float:
    """키움 분봉 값 — 부호(+/-)·콤마 제거 후 절대값(하락봉은 '-' 접두)."""
    try:
        return abs(float(str(v).replace(",", "")))
    except Exception:
        return 0.0


async def fetch_minutes(code: str, interval: int = INTERVAL) -> list[dict]:
    """ka10080 5분봉 조회 → [{ts, open, high, low, close, volume}] (오래된순).

    분봉 응답은 ~170KB 라 MCP 기본 자름(30KB)에 걸려 JSON 이 깨진다 → 이 호출 동안만
    MCP_TOOL_RESULT_MAX_CHARS 를 해제하고 원복(데몬에 import 돼도 다른 호출에 영향 없도록 격리).
    """
    from src.claude_agents.base.mcp_client import MCPManager
    _KEY = "MCP_TOOL_RESULT_MAX_CHARS"
    _old = os.environ.get(_KEY)
    os.environ[_KEY] = "0"
    try:
        async with MCPManager({"kiwoom-market-mcp": MARKET_URL}) as mcp:
            if not mcp.tools:
                logger.warning("[MINUTE] market-domain 연결 실패")
                return []
            raw = await mcp.call_tool("get_minute_chart",
                                      {"stock_code": code, "interval": interval, "count": 900})
            p = json.loads(raw) if isinstance(raw, str) else raw
            rows = (p.get("data", {}) or {}).get("stk_min_pole_chart_qry", [])
    except Exception as e:
        logger.warning("[MINUTE] %s 조회 실패: %s", code, str(e)[:120])
        return []
    finally:
        if _old is None:
            os.environ.pop(_KEY, None)
        else:
            os.environ[_KEY] = _old
    out = []
    for r in rows:
        tm = str(r.get("cntr_tm", ""))
        if len(tm) < 12:
            continue
        out.append({"ts": tm, "open": _num(r.get("open_pric")), "high": _num(r.get("high_pric")),
                    "low": _num(r.get("low_pric")), "close": _num(r.get("cur_prc")),
                    "volume": _num(r.get("trde_qty"))})
    out.sort(key=lambda x: x["ts"])
    return out


def save_by_date(code: str, bars: list[dict]) -> tuple[int, int]:
    """일자별로 쪼개 저장. 이미 있는 파일은 건너뜀(멱등). → (신규 저장일수, 스킵일수)."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for b in bars:
        by_day[f"{b['ts'][:4]}-{b['ts'][4:6]}-{b['ts'][6:8]}"].append(b)
    new = skip = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for day, rows in by_day.items():
        d = MINUTE_DIR / day
        f = d / f"{code}.json"
        # 오늘자는 장중 재수집으로 갱신될 수 있으므로 덮어쓴다(과거일은 확정 → 스킵).
        if f.exists() and day != today:
            skip += 1
            continue
        d.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        new += 1
    return new, skip


def _targets() -> list[str]:
    """보유 종목 + 당일 screen 후보 (실제 진입 판단 대상)."""
    codes: set[str] = set()
    st_file = DATA_DIR / "state.json"
    if st_file.exists():
        try:
            st = json.loads(st_file.read_text(encoding="utf-8"))
            codes |= {p["symbol"] for p in st.get("positions", [])}
            codes |= {c["symbol"] for c in st.get("candidates", [])}
            codes |= {c["symbol"] for c in st.get("pending_entries", [])}
        except Exception as e:
            logger.warning("[MINUTE] state 파싱 실패: %s", e)
    return sorted(codes)


async def collect(codes: list[str], interval: int = INTERVAL) -> None:
    if not codes:
        logger.info("[MINUTE] 수집 대상 없음")
        return
    logger.info("[MINUTE] %d종목 %d분봉 수집 시작", len(codes), interval)
    tot_new = tot_skip = 0
    for i, code in enumerate(codes, 1):
        bars = await fetch_minutes(code, interval)
        if not bars:
            continue
        n, s = save_by_date(code, bars)
        tot_new += n; tot_skip += s
        logger.info("[MINUTE] %s %d봉 → 신규 %d일 · 기존 %d일 (%d/%d)", code, len(bars), n, s, i, len(codes))
        await asyncio.sleep(0.3)          # 키움 rate limit 여유
    logger.info("[MINUTE] 완료 — 신규 %d일치 저장 · %d일치 스킵 · 경로 %s", tot_new, tot_skip, MINUTE_DIR)


# ─── 분석: 시각별 체결가 비교 ────────────────────────────────────────────────
def _bar_at(rows: list[dict], hhmm: str) -> dict | None:
    """해당 시각(HHMM) 이상인 첫 봉 — 5분봉이면 09:30 요청 시 09:30봉."""
    t = hhmm.replace(":", "")
    for b in rows:
        if b["ts"][8:12] >= t:
            return b
    return None


def analyze(times: list[str]) -> None:
    """저장된 분봉으로 시각별 진입가를 비교 — 그날 시가·종가 대비 얼마나 유리했나.

    지표: 각 시각 체결가(해당 5분봉 시가)를 그날 **종가** 대비 %로 환산.
          음수(-)일수록 종가보다 싸게 산 것 = 유리한 진입.
    """
    if not MINUTE_DIR.exists():
        print("수집된 분봉이 없습니다. 먼저 --auto 로 수집하세요."); return
    days = sorted(d for d in MINUTE_DIR.iterdir() if d.is_dir())
    agg: dict[str, list[float]] = defaultdict(list)
    n_samples = 0
    print(f"\n{'날짜':<12} {'종목':<8} " + " ".join(f"{t:>9}" for t in times) + f" {'종가':>9}")
    print("-" * (22 + 10 * len(times) + 10))
    for d in days:
        for f in sorted(d.glob("*.json")):
            try:
                rows = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if len(rows) < 10:
                continue
            close = rows[-1]["close"]
            if close <= 0:
                continue
            cells, ok = [], True
            for t in times:
                b = _bar_at(rows, t)
                if not b or b["open"] <= 0:
                    ok = False; cells.append("      —"); continue
                rel = (b["open"] - close) / close * 100
                agg[t].append(rel)
                cells.append(f"{rel:>+8.2f}%")
            if ok:
                n_samples += 1
            print(f"{d.name:<12} {f.stem:<8} " + " ".join(cells) + f" {close:>9,.0f}")
    if not agg:
        print("\n비교 가능한 표본 없음"); return
    print("\n" + "=" * 60)
    print(f"시각별 평균 (종가 대비, 음수=싸게 삼 / 표본 {n_samples}일·종목)")
    print("=" * 60)
    best = None
    for t in times:
        v = agg.get(t) or []
        if not v:
            continue
        avg = sum(v) / len(v)
        med = sorted(v)[len(v) // 2]
        print(f"  {t}  평균 {avg:>+7.2f}%  중앙 {med:>+7.2f}%  n={len(v)}")
        if best is None or avg < best[1]:
            best = (t, avg)
    if best:
        print(f"\n→ 평균적으로 가장 싸게 산 시각: **{best[0]}** ({best[1]:+.2f}%)")
    print("  ※ 표본이 수십 건 이상 쌓여야 의미 있음. 진입 종목은 상승 후보라 종가 대비 음수가 유리.")


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--auto", action="store_true", help="보유+후보 종목 자동 수집")
    g.add_argument("--codes", help="쉼표구분 종목코드 직접 지정")
    g.add_argument("--analyze", action="store_true", help="쌓인 데이터로 시각별 진입가 비교")
    p.add_argument("--interval", type=int, default=INTERVAL, help="분봉 간격(기본 5)")
    p.add_argument("--times", default="09:30,10:00,11:00,13:00,14:00",
                   help="분석할 시각(쉼표구분)")
    a = p.parse_args()

    if a.analyze:
        analyze([t.strip() for t in a.times.split(",") if t.strip()])
        return
    codes = _targets() if a.auto else [c.strip() for c in a.codes.split(",") if c.strip()]
    asyncio.run(collect(codes, a.interval))


if __name__ == "__main__":
    main()
