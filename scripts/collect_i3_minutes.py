"""I3·리그 분봉 수집 — 키움 1분봉을 매일 날짜별 파일로 쌓는다 (2026-10-22, 개선 백로그 P1-③).

왜: 진짜 분 단위 단타(시가 범위 돌파 등)는 분봉 이력이 있어야 잰다. 키움 ka10080 은 최근 ~900봉(1분봉 약 2.3일)만
준다 — **매일 모으지 않으면 영구 유실**(외인 수급 수집과 같은 이유, 08-25~09-29 수집 중단 사고 참고).

- i3_decide.cmd 가 판단·리그 뒤 실행(평일 15:5x — 그날 장이 끝난 뒤). 실패해도 판단 결과코드에 영향 없음.
- 저장: data/minute/{종목}/{YYYY-MM-DD}.json = [{t:"HHMM", o,h,l,c,v}] (시각 오름차순). 같은 날 다시 받으면
  더 많은 봉을 가진 쪽으로 합친다(봉이 줄어드는 덮어쓰기 금지).
- 장 마감 전(15:31 이전) 오늘 봉은 미완성이라 저장하지 않는다. 완성일 봉 수가 이상하게 적으면 경고만 남긴다.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, time as dtime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CODES = ("069500", "488770", "229200",     # KODEX200 · KODEX 머니마켓액티브 · KODEX 코스닥150
         # 공격형 트랙(10-28 운용자 결정 — 양방향·단타): 레버리지 · 200선물인버스2X · 인버스 · 코스닥150 레버리지·선물인버스
         "122630", "252670", "114800", "233740", "251340")
OUT_DIR = _ROOT / "data" / "minute"
SESSION_END = dtime(15, 31)
MIN_FULL_BARS = 300                         # 정규장 1분봉은 약 381개 — 이보다 크게 적으면 경고(휴장·반일장 제외)


def _num(v) -> float:
    try:
        return abs(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0.0


def parse_rows(rows: list[dict]) -> dict[str, list[dict]]:
    """ka10080 응답 행 → {날짜: [봉…]} (시각 오름차순). cntr_tm = YYYYMMDDHHMMSS."""
    by: dict[str, dict[str, dict]] = defaultdict(dict)
    for x in rows:
        t = str(x.get("cntr_tm", ""))
        if len(t) < 12:
            continue
        day = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
        c = _num(x.get("cur_prc"))
        if c <= 0:
            continue
        by[day][t[8:12]] = {"t": t[8:12], "o": _num(x.get("open_pric")) or c, "h": _num(x.get("high_pric")) or c,
                            "l": _num(x.get("low_pric")) or c, "c": c, "v": _num(x.get("trde_qty"))}
    return {d: [bars[k] for k in sorted(bars)] for d, bars in by.items()}


def merge_save(code: str, day: str, bars: list[dict], out_dir: Path = OUT_DIR) -> tuple[int, int]:
    """기존 파일과 시각 기준으로 합쳐 저장 → (기존 봉 수, 저장 후 봉 수). 줄어드는 덮어쓰기는 없다."""
    path = out_dir / code / f"{day}.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    merged = {b["t"]: b for b in old}
    for b in bars:
        merged.setdefault(b["t"], b)
    rows = [merged[k] for k in sorted(merged)]
    if len(rows) > len(old):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    return len(old), max(len(rows), len(old))


async def collect(now: datetime) -> dict:
    from src.mcp_servers.kiwoom_mcp.common.constants.api_types import KiwoomAPIID
    from src.mcp_servers.kiwoom_mcp.domains.market_domain import create_market_domain_server
    srv = create_market_domain_server()                # MCP 응답 30KB 잘림을 피해 서버 코드를 프로세스 안에서 쓴다
    today = now.strftime("%Y-%m-%d")
    report = {}
    for code in CODES:
        r = await srv.call_api_with_response(api_id=KiwoomAPIID.STOCK_MINUTE_CHART, query=f"{code} 1분",
                                             params={"stk_cd": code, "tic_scope": "1", "upd_stkpc_tp": "1"})
        days = parse_rows((r.get("data") or {}).get("stk_min_pole_chart_qry") or [])
        saved = {}
        for day, bars in days.items():
            if day == today and now.time() < SESSION_END:
                continue                               # 장중 — 미완성
            before, after = merge_save(code, day, bars)
            saved[day] = after
        short = [d for d, n in saved.items() if n < MIN_FULL_BARS and d != min(saved, default="")]
        report[code] = {"days": saved, "short_days": short}
    return report


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    rep = asyncio.run(collect(datetime.now()))
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
