"""종가매매 대시보드 — Starlette + 단일 HTML.

사용법:
    python scripts/dashboard.py                    # http://localhost:8090
    python scripts/dashboard.py --port 9000        # 포트 변경
    python scripts/dashboard.py --host 0.0.0.0     # 외부 접근 허용

데이터 소스:
    data/closing_bet/YYYY-MM-DD/{selection,buy,sell,events.jsonl}.json
    %TEMP%/mcp_logs/direct_closing_bet.log
    %TEMP%/closing_bet_state_direct.json
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

_ROOT = Path(__file__).parent.parent
DATA_DIR = _ROOT / "data" / "closing_bet"
HTML_FILE = Path(__file__).parent / "dashboard.html"

_TEMP = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
LOG_DIR = _ROOT / "logs" / "closing_bet"
LOG_FILE = LOG_DIR / "closing_bet.log"  # 활성 로그 (자정에 회전)
STATE_FILE = _TEMP / "closing_bet_state_direct.json"


def _resolve_log_path(date: str | None) -> Path:
    """date=None 또는 today → 활성 로그, 그 외 → 회전된 파일 (closing_bet.log.YYYY-MM-DD)."""
    if not date:
        return LOG_FILE
    from datetime import datetime as _dt
    if date == _dt.now().strftime("%Y-%m-%d"):
        return LOG_FILE
    return LOG_DIR / f"closing_bet.log.{date}"


def _list_log_dates() -> list[str]:
    """사용 가능한 로그 날짜 목록 (오늘 + 회전된 백업)."""
    from datetime import datetime as _dt
    dates: list[str] = []
    if LOG_FILE.exists():
        dates.append(_dt.now().strftime("%Y-%m-%d"))
    if LOG_DIR.exists():
        for p in LOG_DIR.glob("closing_bet.log.*"):
            suffix = p.name.removeprefix("closing_bet.log.")
            if len(suffix) == 10 and suffix[4] == "-":
                dates.append(suffix)
    return sorted(set(dates), reverse=True)


def _safe_read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_days() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(
        (d.name for d in DATA_DIR.iterdir() if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"),
        reverse=True,
    )


# ─── API handlers ─────────────────────────────────────────────────────────

async def index(_request):
    if not HTML_FILE.exists():
        return PlainTextResponse(f"dashboard.html missing: {HTML_FILE}", status_code=500)
    return HTMLResponse(HTML_FILE.read_text(encoding="utf-8"))


async def api_days(_request):
    return JSONResponse({"days": _list_days()})


async def api_day(request):
    date = request.path_params["date"]
    day_dir = DATA_DIR / date
    if not day_dir.exists():
        return JSONResponse({"error": f"no data for {date}"}, status_code=404)

    selection = _safe_read_json(day_dir / "selection.json")
    buy       = _safe_read_json(day_dir / "buy.json")
    sell      = _safe_read_json(day_dir / "sell.json")

    events: list[dict] = []
    ev_path = day_dir / "events.jsonl"
    if ev_path.exists():
        for line in ev_path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except Exception:
                pass

    return JSONResponse({
        "date":      date,
        "selection": selection,
        "buy":       buy,
        "sell":      sell,
        "events":    events,
    })


async def api_summary(_request):
    """누적 통계 — 점수 구간별 승률, 일별 P&L, 섹터 분포."""
    days = _list_days()
    trades: list[dict] = []
    daily_pnl: dict[str, dict] = {}
    sector_count: dict[str, int] = defaultdict(int)

    for date in days:
        day_dir = DATA_DIR / date
        sell = _safe_read_json(day_dir / "sell.json")
        if not sell:
            continue

        # 매수일에서 score / sector 보강
        entry_date = sell.get("entry_date")
        score_map: dict[str, float] = {}
        sector_map: dict[str, str] = {}
        if entry_date:
            sel = _safe_read_json(DATA_DIR / entry_date / "selection.json")
            if sel:
                for c in sel.get("candidates", []):
                    score_map[c["symbol"]] = c.get("composite", 0.0)
                    sector_map[c["symbol"]] = c.get("sector", "기타")
            buy = _safe_read_json(DATA_DIR / entry_date / "buy.json")
            if buy:
                for o in buy.get("orders", []):
                    sector_map.setdefault(o["symbol"], o.get("sector", "기타"))

        wins, losses, total_pnl = 0, 0, 0.0
        for r in sell.get("results", []):
            if r.get("action") == "HOLD":
                continue
            sym = r.get("symbol", "")
            comp = r.get("composite") or score_map.get(sym, 0.0)
            sec = r.get("sector") or sector_map.get(sym, "기타")
            pnl = float(r.get("pnl_pct") or 0.0)
            trades.append({
                "date": date, "symbol": sym, "name": r.get("company_name", ""),
                "composite": comp, "sector": sec, "pnl_pct": pnl,
                "action": r.get("action", ""), "win": pnl > 0,
            })
            sector_count[sec] += 1
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            total_pnl += pnl

        if wins + losses > 0:
            daily_pnl[date] = {
                "trades": wins + losses, "wins": wins, "losses": losses,
                "win_rate": round(wins / (wins + losses) * 100, 1),
                "total_pnl_pct": round(total_pnl, 2),
            }

    # 점수 구간별 통계
    brackets = [(80, 200), (70, 80), (60, 70), (50, 60), (0, 50)]
    bracket_stats = []
    for lo, hi in brackets:
        sub = [t for t in trades if lo <= t["composite"] < hi]
        if not sub:
            continue
        w = sum(1 for t in sub if t["win"])
        bracket_stats.append({
            "label":     f"{lo}~{hi}" if hi < 200 else f"{lo}+",
            "count":     len(sub),
            "win_rate":  round(w / len(sub) * 100, 1),
            "avg_pnl":   round(sum(t["pnl_pct"] for t in sub) / len(sub), 2),
        })

    total_trades = len(trades)
    total_wins = sum(1 for t in trades if t["win"])
    return JSONResponse({
        "totals": {
            "trades":      total_trades,
            "wins":        total_wins,
            "losses":      total_trades - total_wins,
            "win_rate":    round(total_wins / total_trades * 100, 1) if total_trades else 0.0,
            "avg_pnl":     round(sum(t["pnl_pct"] for t in trades) / total_trades, 2) if total_trades else 0.0,
            "total_pnl":   round(sum(t["pnl_pct"] for t in trades), 2),
            "trading_days": len(daily_pnl),
        },
        "bracket_stats": bracket_stats,
        "daily_pnl":     daily_pnl,
        "sector_count":  dict(sector_count),
        "trades":        trades[-200:],
    })


async def api_log(request):
    """실시간 로그 tail. ?date=YYYY-MM-DD 로 회전된 백업 파일 조회 가능."""
    n = int(request.query_params.get("n", "200"))
    date = request.query_params.get("date")
    path = _resolve_log_path(date)
    available = _list_log_dates()
    if not path.exists():
        return JSONResponse({
            "lines": [], "path": str(path), "exists": False,
            "available_dates": available,
        })
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return JSONResponse({
            "lines":           lines[-n:],
            "total":           len(lines),
            "path":            str(path),
            "exists":          True,
            "date":            date or "today",
            "available_dates": available,
        })
    except Exception as e:
        return JSONResponse({"error": str(e), "path": str(path)}, status_code=500)


async def api_state(_request):
    if not STATE_FILE.exists():
        return JSONResponse({"exists": False, "path": str(STATE_FILE)})
    state = _safe_read_json(STATE_FILE) or {}
    return JSONResponse({"exists": True, "path": str(STATE_FILE), "state": state})


async def api_health(_request):
    return JSONResponse({
        "status":    "ok",
        "data_dir":  str(DATA_DIR),
        "log_file":  str(LOG_FILE),
        "days":      len(_list_days()),
    })


# ─── App factory ──────────────────────────────────────────────────────────

routes = [
    Route("/",                   index),
    Route("/api/health",         api_health),
    Route("/api/days",           api_days),
    Route("/api/day/{date}",     api_day),
    Route("/api/summary",        api_summary),
    Route("/api/log",            api_log),
    Route("/api/state",          api_state),
]

app = Starlette(debug=False, routes=routes)


def main() -> None:
    parser = argparse.ArgumentParser(description="종가매매 대시보드")
    parser.add_argument("--host", default="127.0.0.1", help="bind 호스트 (기본: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8090, help="bind 포트 (기본: 8090)")
    args = parser.parse_args()

    print(f"\n  대시보드: http://{args.host}:{args.port}")
    print(f"  데이터:   {DATA_DIR}")
    print(f"  로그:     {LOG_FILE}\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
