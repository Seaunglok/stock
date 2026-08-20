"""분봉 수집·분석 — 진입 **시각**(09:30 vs 11:00) 검증용 데이터 축적.

배경: 일봉 백테스트는 '익일 시가' 진입만 모델링할 수 있어, 2026-08 채택한 11:00 진입이
09:30 대비 유리한지 검증할 방법이 없다(장중 시각 가격이 일봉에 없음). 키움 ka10080
5분봉은 **약 12영업일치(900봉)** 를 주므로, 매일 수집해 쌓으면 시각별 체결가 비교가 가능해진다.

수집 대상: 보유 종목 + 당일 screen 후보(= 실제 진입 판단이 일어난 종목).
저장: data/trend_follow/minute/<YYYY-MM-DD>/<code>.json  (일자별 분리 = 멱등·증분)

사용:
  python scripts/collect_minute_bars.py --auto              # 보유+후보 자동 수집(장 마감 후)
  python scripts/collect_minute_bars.py --codes 005930,000660
  python scripts/collect_minute_bars.py --coverage          # 실제 거래일 대비 누락 점검
  python scripts/collect_minute_bars.py --volatility        # 시간대별 실현변동성(방향 무관)
  python scripts/collect_minute_bars.py --analyze           # 시각별 진입가(종가 대비 — 교란 주의)

분석 지표 선택:
  --volatility  방향 무관(레인지·σ·경로효율). 레짐 편향 없음 → 시각 비교에 이걸 쓴다.
  --analyze     '그날 종가 대비' 상대가. 지수 방향에 좌우돼 한쪽 레짐 표본에선 결론이 뒤집힌다.
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

from trend_config import DATA_DIR, MARKET_URL, logger, setup_daemon_runtime  # noqa: E402

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
    print("\n  ⚠️ 이 지표만으로 진입 시각을 바꾸지 말 것 — 세 가지로 교란된다:")
    print("     ① '그날 종가 대비'라 지수 방향에 좌우된다. 표본 구간이 한쪽 레짐이면 결론이 뒤집힌다.")
    print("     ② 수집 대상이 보유종목+후보 전체라 '실제 진입했을 날'이 아니다.")
    print("     ③ 하루 안의 상대가격일 뿐, 거래 결과(진입~청산)가 아니다.")
    print("     → 변동성·슬리피지 비교는 `--volatility`(방향 무관)를, 최종 판단은 거래 결과를 쓸 것.")


# ─── 분석: 시간대별 실현변동성 (방향 무관) ───────────────────────────────────
# ts 는 **봉 시작 시각**(0900 봉 = 09:00~09:05). 구간은 [시작, 끝) 반열림.
_BUCKETS = (
    ("09:00~09:30", "0900", "0930"),   # 시초 갭·동시호가 물량 소화
    ("09:30~10:00", "0930", "1000"),   # 구 진입시각
    ("10:00~11:00", "1000", "1100"),
    ("11:00~12:00", "1100", "1200"),   # 현 진입시각
    ("12:00~13:00", "1200", "1300"),
    ("13:00~14:00", "1300", "1400"),
    ("14:00~15:00", "1400", "1500"),
    ("15:00~15:20", "1500", "1520"),   # 마감 동시호가 직전
)


def _bucket_stats(rows: list[dict]) -> tuple[float, float, float, float] | None:
    """한 구간의 (레인지%, 5분수익률σ%, 경로효율, 평균봉레인지%). 봉 3개 미만이면 None.

    **전부 방향 무관 지표**다. `analyze()` 의 '종가 대비' 지표는 그날 지수 방향에 좌우돼
    하락장 표본에서는 해석이 뒤집힌다 — 진입 시각 선택의 근거로 쓸 수 없다.
    여기 지표는 오르든 내리든 '얼마나 흔들리는가'만 재므로 레짐 편향이 없다.
    """
    if len(rows) < 3:
        return None
    o = rows[0]["open"]
    if o <= 0:
        return None
    rng = (max(r["high"] for r in rows) - min(r["low"] for r in rows)) / o * 100
    closes = [r["close"] for r in rows if r["close"] > 0]
    if len(closes) < 3:
        return None
    rets = [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(1, len(closes))]
    mu = sum(rets) / len(rets)
    sigma = (sum((x - mu) ** 2 for x in rets) / len(rets)) ** 0.5
    path = sum(abs(x) for x in rets)
    # 경로효율 = |순변동| / |총이동거리|. 1=직진, 0에 가까울수록 왕복(휩소).
    eff = abs(closes[-1] - closes[0]) / closes[0] * 100 / path if path > 0 else 0.0
    bar_rng = sum((r["high"] - r["low"]) / r["open"] * 100 for r in rows if r["open"] > 0) / len(rows)
    return rng, sigma, eff, bar_rng


def analyze_volatility() -> None:
    """시간대별 실현변동성 — '09~10시가 가장 변동성 크다'는 11:00 진입 채택 근거를 직접 검증."""
    if not MINUTE_DIR.exists():
        print("수집된 분봉이 없습니다. 먼저 --auto 로 수집하세요."); return
    days = sorted(d for d in MINUTE_DIR.iterdir() if d.is_dir())
    agg: dict[str, list[tuple]] = defaultdict(list)
    n_files = 0
    for d in days:
        for f in sorted(d.glob("*.json")):
            try:
                rows = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if len(rows) < 30:
                continue
            n_files += 1
            for label, lo, hi in _BUCKETS:
                seg = [r for r in rows if lo <= r["ts"][8:12] < hi]
                s = _bucket_stats(seg)
                if s:
                    agg[label].append(s)
    if not agg:
        print("분석 가능한 표본 없음"); return
    span = f"{days[0].name}~{days[-1].name}" if days else "-"
    print(f"\n{'='*84}")
    print(f"시간대별 실현변동성 — 방향 무관 지표 (표본 {n_files} 종목-일 · {span})")
    print("=" * 84)
    print(f"  {'구간':14} {'구간레인지':>10} {'5분σ':>8} {'경로효율':>9} {'봉당레인지':>11} {'표본':>6}")
    print("  " + "-" * 66)
    rows_out = []
    for label, _, _ in _BUCKETS:
        v = agg.get(label) or []
        if not v:
            continue
        n = len(v)
        m = tuple(sum(x[i] for x in v) / n for i in range(4))
        rows_out.append((label, *m, n))
        print(f"  {label:14} {m[0]:>9.2f}% {m[1]:>7.3f}% {m[2]:>9.3f} {m[3]:>10.3f}% {n:>6}")
    print("  " + "-" * 66)
    print("  구간레인지=구간 고저폭 / 5분σ=5분수익률 표준편차 / 경로효율=|순변동|÷총이동(1=직진,낮을수록 휩소)")
    print("  봉당레인지=5분봉 평균 고저폭(≈ 시장가 체결 시 순간 슬리피지 노출)")
    if rows_out:
        wv = max(rows_out, key=lambda r: r[2])
        wc = min(rows_out, key=lambda r: r[3])
        ws = max(rows_out, key=lambda r: r[4])
        print(f"\n  → 변동성 최대: {wv[0]} (5분σ {wv[2]:.3f}%)")
        print(f"  → 휩소 최대  : {wc[0]} (경로효율 {wc[3]:.3f})")
        print(f"  → 슬리피지 최대: {ws[0]} (봉당레인지 {ws[4]:.3f}%)")
    print("\n  ※ 방향 무관 지표라 하락장 표본에서도 해석이 뒤집히지 않는다.")
    print("  ※ 다만 '진입 시각'의 최종 판단은 거래 결과(진입~청산)로 해야 한다 — 진입 재개 후 검증.")


def check_coverage(ref_code: str = "005930") -> None:
    """수집 커버리지 점검 — **실제 거래일**(일봉) 대비 누락일.

    휴장일을 요일로 판정하면 안 된다: 2026-07-17(제헌절)·08-17(광복절 대체휴일)은 평일이지만
    휴장이라 분봉이 없는 게 정상이다. 공휴일 목록을 코드에 박으면 매년 썩으므로, 유동성 있는
    종목의 **일봉이 존재하는 날 = 거래일**을 기준으로 삼는다(달력 관리 불필요).

    ka10080 은 ~12영업일치만 주므로, 그 창을 벗어난 누락은 영구 유실이다.
    """
    from src.mcp_servers.trend_mcp.market_data import get_ohlcv
    if not MINUTE_DIR.exists():
        print("수집된 분봉이 없습니다."); return
    have = sorted(d.name for d in MINUTE_DIR.iterdir() if d.is_dir())
    if not have:
        print("수집된 분봉이 없습니다."); return
    bars = get_ohlcv(ref_code, 200) or []
    if not bars:
        print(f"기준 종목({ref_code}) 일봉 조회 실패 — 커버리지 판정 불가"); return
    trading = sorted(b["date"] for b in bars if have[0] <= b["date"] <= have[-1])
    missing = [d for d in trading if d not in set(have)]
    recoverable = set(sorted(t for t in trading)[-12:])   # ka10080 조회 가능 창(~12영업일)
    print(f"\n수집 {len(have)}일 · 거래일 {len(trading)}일 ({have[0]}~{have[-1]}, 기준 {ref_code})")
    if not missing:
        print("  ✅ 누락 없음")
    else:
        print(f"  ⚠️ 누락 {len(missing)}일:")
        for d in missing:
            tag = "복구 가능(--auto 로 소급)" if d in recoverable else "영구 유실(조회창 초과)"
            print(f"     {d}  {tag}")
    thin = [(d.name, n) for d in MINUTE_DIR.iterdir() if d.is_dir()
            and (n := len(list(d.glob('*.json')))) < 3]
    if thin:
        print(f"  ⚠️ 종목수 3개 미만인 날 {len(thin)}일: " + ", ".join(f"{d}({n}종)" for d, n in sorted(thin)))
    print("\n  ※ save_by_date 가 900봉 응답을 일자별로 쪼개 저장하므로, 데몬이 12영업일 안에")
    print("     한 번이라도 돌면 그 사이 누락은 자동 소급된다. 그 창을 넘겨야 영구 유실이다.")


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--auto", action="store_true", help="보유+후보 종목 자동 수집")
    g.add_argument("--codes", help="쉼표구분 종목코드 직접 지정")
    g.add_argument("--analyze", action="store_true", help="쌓인 데이터로 시각별 진입가 비교")
    g.add_argument("--volatility", action="store_true",
                   help="시간대별 실현변동성(방향 무관) — 11:00 진입 채택 근거 검증")
    g.add_argument("--coverage", action="store_true",
                   help="수집 커버리지 점검 — 실제 거래일(일봉 기준) 대비 누락일 확인")
    p.add_argument("--interval", type=int, default=INTERVAL, help="분봉 간격(기본 5)")
    p.add_argument("--times", default="09:30,10:00,11:00,13:00,14:00",
                   help="분석할 시각(쉼표구분)")
    a = p.parse_args()

    if a.analyze:
        analyze([t.strip() for t in a.times.split(",") if t.strip()])
        return
    if a.volatility:
        analyze_volatility()
        return
    if a.coverage:
        check_coverage()
        return
    codes = _targets() if a.auto else [c.strip() for c in a.codes.split(",") if c.strip()]
    asyncio.run(collect(codes, a.interval))


if __name__ == "__main__":
    setup_daemon_runtime()   # 파일로깅·소켓 타임아웃 (스크립트 진입점에서만)
    main()
