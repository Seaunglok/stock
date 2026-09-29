"""외국인 수급(ka10008) 일별 수집 — 외인 청산 룰을 나중에 재검증할 데이터를 끊기지 않게 쌓는다.

왜 따로 도는가 (2026-09-29)
---------------------------
08-28 외인 청산을 끄면서(USE_FOREIGN_EXIT=false) 수집도 같이 멈췄다. 데몬의 `_foreign_net_5d`
호출이 그 스위치에 묶여 있었고, 디스크 캐시는 백테스트가 돌 때만 부수적으로 쌓였다
(마지막 스냅샷 08-25). 리팩터링 때 "이력이 계속 쌓이는 중이라 코드를 보존한다"고 적었지만
사실이 아니었다. ka10008 은 최근 ~50 완성일만 돌려주므로, 그보다 오래 비우면 중간 날짜가
**영구히** 사라진다. 이 스크립트가 매일 스냅샷을 떠서 이어 붙인다.

**주문·청산에 관여하지 않는다.** investor-domain(:8033) 조회만 한다. 데몬도 이 모듈을 부르지 않는다.

저장
----
  docs_cache/foreign_ka10008/{code}_{YYYYMMDD}.json  원본 스냅샷. backtest_trend._load_foreign_map 과
                                                     **같은 경로·형식**이라 백테스트가 그대로 읽는다.
  data/trend_follow/foreign_flow/{code}.json         완성일 누적 이력 {dt: row} — 스냅샷을 합친 것.
                                                     매번 스냅샷 전체에서 다시 만든다(증분 상태 없음).
빈 응답은 저장하지 않는다. 8050(IP 미등록) 같은 장애일에 `[]` 가 캐시되면 그날 재시도가 막힌다.

사용법
------
    python scripts/collect_foreign_flow.py              # 오늘 스냅샷 수집 + 이력 병합 + 연속성 보고
    python scripts/collect_foreign_flow.py --merge-only # 수집 없이 기존 스냅샷만 병합·점검
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.claude_agents.base.mcp_client import MCPManager  # noqa: E402

SNAP_DIR = _ROOT / "docs_cache" / "foreign_ka10008"      # backtest_trend.FOREIGN_CACHE 와 같은 곳
HIST_DIR = _ROOT / "data" / "trend_follow" / "foreign_flow"
STATE_FILE = _ROOT / "data" / "trend_follow" / "state.json"   # 보유 종목 조회용(읽기만)
INVESTOR_URL = "http://localhost:8033/mcp/"
TOOL = "get_foreign_trading_trend"
MIN_OK_RATIO = 0.9       # 성공률이 이보다 낮으면 실패 종료 — 예약작업 결과로 드러나게
CALL_GAP_SEC = 0.25      # 키움 rate limit 여유(백테스트 로더와 동일)
STALE_WARN_DAYS = 20     # 마지막 스냅샷이 이보다 오래되면 경고(ka10008 창 ≈ 50 완성일)


# ── 순수 함수 ───────────────────────────────────────────────────────────────
def snap_path(code: str, day: str) -> Path:
    return SNAP_DIR / f"{code}_{day}.json"


def parse_rows(payload) -> list[dict]:
    """MCP 응답 → ka10008 행 리스트. backtest_trend._load_foreign_map 과 같은 추출."""
    p = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(p, dict):
        return []
    rows = (p.get("data", {}) or {}).get("stk_frgnr", []) or []
    return [r for r in rows if isinstance(r, dict)]


def merge_rows(hist: dict, rows: list[dict], snap_day: str) -> int:
    """스냅샷 행을 누적 이력에 병합 — **완성일만**, 나중 스냅샷이 이긴다. 반환: 반영한 행 수.

    스냅샷 당일(dt == snap_day) 값은 잠정치라 뺀다(백테스트 로더와 같은 규칙).
    같은 날짜가 여러 스냅샷에 있으면 나중에 뜬 쪽이 정정값이므로 덮어쓴다 —
    호출자가 스냅샷을 날짜 오름차순으로 넣어야 한다.
    """
    n = 0
    for r in rows:
        dt = str(r.get("dt", ""))
        if len(dt) != 8 or not dt.isdigit() or dt >= snap_day:
            continue
        hist[dt] = r
        n += 1
    return n


def _nonempty(f: Path) -> bool:
    try:
        v = json.loads(f.read_text(encoding="utf-8"))
        return isinstance(v, list) and len(v) > 0
    except Exception:
        return False


def snapshots_by_code() -> dict[str, list[tuple[str, Path]]]:
    """{code: [(YYYYMMDD, 파일), ...]} — 날짜 오름차순."""
    out: dict[str, list[tuple[str, Path]]] = {}
    if not SNAP_DIR.exists():
        return out
    for f in SNAP_DIR.glob("*_*.json"):
        code, _, day = f.stem.rpartition("_")
        if code and len(day) == 8 and day.isdigit():
            out.setdefault(code, []).append((day, f))
    for v in out.values():
        v.sort()
    return out


def rebuild_history(snaps: list[tuple[str, Path]]) -> dict:
    """스냅샷 전체를 날짜순으로 병합 — 항상 처음부터 다시 만든다(증분 상태 손상 경로 없음)."""
    hist: dict = {}
    for day, f in snaps:
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(rows, list) and rows:
            merge_rows(hist, rows, day)
    return dict(sorted(hist.items()))


def market_calendar(hists: dict[str, dict]) -> list[str]:
    """거래일 달력 — **과반 종목**에 있는 날.

    한 종목에만 있는 날짜(이상치)가 달력을 만들면 나머지 전 종목이 공백으로 보이고,
    거래정지 종목 하나의 빈 날을 달력 공백으로 오인해서도 안 된다.
    """
    c = Counter(d for h in hists.values() for d in h)
    need = max(1, len(hists) // 2 + 1) if len(hists) > 1 else 1
    return sorted(d for d, n in c.items() if n >= need)


def missing_days(hist_dates: set[str], calendar: list[str]) -> list[str]:
    """보유 구간(최초~최신) 안에서 달력에 있는데 이력에 없는 날."""
    if not hist_dates:
        return []
    lo, hi = min(hist_dates), max(hist_dates)
    return [d for d in calendar if lo <= d <= hi and d not in hist_dates]


# ── 수집 대상 ───────────────────────────────────────────────────────────────
def _universe_codes() -> set[str]:
    """데몬 스크린과 같은 유니버스(trend_config 값 그대로)."""
    from trend_config import MIN_VALUE_KRW, TOP_N, UNIVERSE_MODE, WATCHLIST
    from src.mcp_servers.trend_mcp.market_data import get_universe
    return {c for c, _n in get_universe(UNIVERSE_MODE, TOP_N, WATCHLIST, MIN_VALUE_KRW)}


def target_codes() -> list[str]:
    """현재 유니버스 ∪ 이미 수집해 온 종목 ∪ 보유 종목.

    이미 수집해 온 종목을 계속 받는 이유: 시총 순위가 바뀌어 유니버스에서 빠져도 그 종목의
    과거 구간은 시점별 유니버스(PIT) 재검증에 필요하다. 한 번 빠지면 이력이 끊긴다.
    """
    codes = set(snapshots_by_code())
    try:
        codes |= _universe_codes()
    except Exception as e:
        print(f"  ⚠️ 유니버스 조회 실패 — 기존 수집 종목만 진행: {str(e)[:100]}")
    try:
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        codes |= {p["symbol"] for p in st.get("positions", [])}
    except Exception:
        pass
    return sorted(codes)


# ── 수집 ────────────────────────────────────────────────────────────────────
async def fetch(codes: list[str], day: str) -> tuple[list[str], list[str]]:
    """오늘 스냅샷 수집 → (성공 코드, 실패 코드). **빈 응답은 저장하지 않는다.**

    같은 날 이미 받은 종목은 다시 부르지 않는다(재실행 안전 · rate limit).
    """
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ok: list[str] = []
    fail: list[str] = []
    async with MCPManager({"investor-domain": INVESTOR_URL}) as mcp:
        if not mcp.tools:
            print("  ❌ investor-domain(:8033) 연결 실패")
            return ok, list(codes)
        for code in codes:
            f = snap_path(code, day)
            if f.exists() and _nonempty(f):
                ok.append(code)
                continue
            try:
                rows = parse_rows(await mcp.call_tool(TOOL, {"stock_code": code}))
            except Exception as e:
                rows = []
                print(f"  {code} 조회 실패: {str(e)[:80]}")
            if rows:
                f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
                ok.append(code)
            else:
                f.unlink(missing_ok=True)      # 앞선 실패가 남긴 빈 캐시도 지운다 — 재시도가 막히지 않게
                fail.append(code)
            await asyncio.sleep(CALL_GAP_SEC)
    return ok, fail


# ── 실행 ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merge-only", action="store_true", help="수집 없이 기존 스냅샷만 병합·점검")
    args = ap.parse_args()

    now = datetime.now()
    day = now.strftime("%Y%m%d")
    print(f"==== 외인 수급 수집 {now:%Y-%m-%d %H:%M}")
    rc = 0
    if not args.merge_only:
        codes = target_codes()
        ok, fail = asyncio.run(fetch(codes, day))
        ratio = len(ok) / len(codes) if codes else 0.0
        print(f"  스냅샷 {len(ok)}/{len(codes)}종목 ({ratio:.0%})"
              + (f" · 실패 {fail[:10]}{' …' if len(fail) > 10 else ''}" if fail else ""))
        if ratio < MIN_OK_RATIO:
            print(f"  ❌ 성공률 {ratio:.0%} < {MIN_OK_RATIO:.0%} — 키움 API(8050 IP·토큰)·8033 서버 확인 필요")
            rc = 1

    snaps = snapshots_by_code()
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    hists: dict[str, dict] = {}
    for code, s in snaps.items():
        h = rebuild_history(s)
        if h:
            hists[code] = h
            (HIST_DIR / f"{code}.json").write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")

    cal = market_calendar(hists)
    holed = {c: g for c, g in ((c, missing_days(set(h), cal)) for c, h in hists.items()) if g}
    oldest = min((min(h) for h in hists.values()), default="-")
    newest = max((max(h) for h in hists.values()), default="-")
    print(f"  누적 이력 {len(hists)}종목 · 완성일 {oldest}~{newest} · 달력 {len(cal)}일")
    if holed:
        worst_code, worst = max(holed.items(), key=lambda kv: len(kv[1]))
        print(f"  ⚠️ 공백 있는 종목 {len(holed)}개 — 최다 {worst_code} {len(worst)}일 {worst[:5]}")
    else:
        print("  연속성: 공백 없음")

    last = max((s[-1][0] for s in snaps.values()), default=None)
    if last:
        age = (now - datetime.strptime(last, "%Y%m%d")).days
        if age > STALE_WARN_DAYS:
            print(f"  ⚠️ 마지막 스냅샷 {last} ({age}일 전) — ka10008 창(약 50 완성일)을 넘기면 중간 날짜가 영구 유실")
    return rc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
