"""추세추종 대시보드 — Starlette + 단일 HTML (인라인). 종가매매(:8090)와 별개.

사용: python scripts/trend_dashboard.py            # http://localhost:8091
데이터: data/trend_follow/{state.json, journal.jsonl, YYYY-MM-DD/events.jsonl}
탭: ① 보유 포지션 ② 거래 내역(승률·손익비·net) ③ 매매일지(근거+심리/실수/개선, 편집)
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

_ROOT = Path(__file__).parent.parent
DATA_DIR = _ROOT / "data" / "trend_follow"
STATE_FILE = DATA_DIR / "state.json"
JOURNAL_FILE = DATA_DIR / "journal.json"   # config.py 와 동일 파일명


def _read_journal() -> list[dict]:
    if not JOURNAL_FILE.exists():
        return []
    out = []
    for line in JOURNAL_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _trades() -> list[dict]:
    """journal.jsonl → 거래(id)별 통합 뷰 (진입+부분+청산+메모)."""
    by_id: dict[str, dict] = defaultdict(lambda: {"partials": [], "notes": []})
    for r in _read_journal():
        jid = r.get("id")
        if not jid:
            continue
        t = r["type"]
        rec = by_id[jid]
        rec["id"] = jid
        if t == "entry":
            rec.update({k: r.get(k) for k in ("symbol", "name", "mode", "qty", "entry_price",
                                              "stop", "target", "score", "rationale", "premarket", "ts")})
        elif t == "partial":
            rec["partials"].append({"qty": r.get("qty"), "price": r.get("price"), "pnl_pct": r.get("pnl_pct")})
        elif t == "exit":
            rec.update({"exit_price": r.get("exit_price"), "pnl_pct": r.get("pnl_pct"),
                        "net_pct": r.get("net_pct"), "pnl_amount": r.get("pnl_amount"),
                        "rr_realized": r.get("rr_realized"), "reason": r.get("reason"),
                        "hold_days": r.get("hold_days"), "closed": True})
        elif t == "note":
            rec["notes"].append({k: r.get(k, "") for k in ("psych", "mistake", "improve", "ts")})
    rows = list(by_id.values())
    rows.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return rows


async def api_state(request):
    st = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    return JSONResponse({"positions": st.get("positions", []), "candidates": st.get("candidates", []),
                         "updated": st.get("last_updated", "")})


async def api_trades(request):
    rows = _trades()
    closed = [r for r in rows if r.get("closed")]
    wins = [r for r in closed if (r.get("net_pct") or 0) > 0]
    losses = [r for r in closed if (r.get("net_pct") or 0) <= 0]
    avg_w = sum(r["net_pct"] for r in wins) / len(wins) if wins else 0
    avg_l = sum(abs(r["net_pct"]) for r in losses) / len(losses) if losses else 0
    summary = {
        "total": len(closed), "wins": len(wins), "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "avg_net": round(sum(r["net_pct"] for r in closed) / len(closed), 2) if closed else 0,
        "payoff": round(avg_w / avg_l, 2) if avg_l else None,
        "total_net": round(sum(r.get("net_pct") or 0 for r in closed), 2),
    }
    return JSONResponse({"trades": rows, "summary": summary})


async def api_note(request):
    body = await request.json()
    jid = body.get("id")
    if not jid:
        return JSONResponse({"ok": False, "error": "id 필요"}, status_code=400)
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "type": "note", "id": jid,
           "psych": body.get("psych", ""), "mistake": body.get("mistake", ""), "improve": body.get("improve", "")}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return JSONResponse({"ok": True})


_HTML = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>추세추종 대시보드</title><script src=https://cdn.tailwindcss.com></script></head>
<body class="bg-slate-900 text-slate-100 p-4">
<h1 class="text-xl font-bold mb-1">📈 대형주 추세추종 <span id=upd class="text-xs text-slate-400"></span></h1>
<div class="flex gap-2 my-3">
 <button onclick="tab('pos')" class="tb px-3 py-1 rounded bg-slate-700">보유 포지션</button>
 <button onclick="tab('trd')" class="tb px-3 py-1 rounded bg-slate-700">거래 내역</button>
 <button onclick="tab('jrn')" class="tb px-3 py-1 rounded bg-slate-700">매매일지</button>
</div>
<div id=sum class="text-sm mb-3 text-slate-300"></div>
<div id=pos class="pane"></div>
<div id=trd class="pane hidden"></div>
<div id=jrn class="pane hidden"></div>
<script>
const f=n=>n==null?'-':Number(n).toLocaleString();
function tab(t){document.querySelectorAll('.pane').forEach(p=>p.classList.add('hidden'));document.getElementById(t).classList.remove('hidden');}
async function load(){
 const s=await (await fetch('/api/state')).json();
 document.getElementById('upd').textContent='업데이트 '+(s.updated||'').slice(0,16);
 document.getElementById('pos').innerHTML = s.positions.length? s.positions.map(p=>
  `<div class="bg-slate-800 rounded p-3 mb-2"><b>${p.name}(${p.symbol})</b> <span class=text-xs>${p.mode}</span><br>
   ${p.qty}주 @${f(p.entry_price)} · 손절 ${f(p.stop_price)} · 목표 ${f(p.target)} ${p.partial_done?'· <span class=text-emerald-400>부분익절</span>':''}</div>`).join('')
  : '<div class=text-slate-400>보유 포지션 없음</div>';
 const t=await (await fetch('/api/trades')).json(); const sm=t.summary;
 document.getElementById('sum').innerHTML=`청산 ${sm.total}건 · 승률 ${sm.win_rate}% · 손익비(payoff) ${sm.payoff??'-'} · net평균 ${sm.avg_net}% · 누적 ${sm.total_net}%`;
 document.getElementById('trd').innerHTML='<table class="w-full text-sm"><tr class=text-slate-400><th class=text-left>종목</th><th>진입</th><th>청산</th><th>net%</th><th>손익비</th><th>보유</th><th class=text-left>사유</th></tr>'+
  t.trades.filter(r=>r.closed).map(r=>`<tr class="border-t border-slate-700"><td>${r.name||r.symbol}</td><td class=text-right>${f(r.entry_price)}</td><td class=text-right>${f(r.exit_price)}</td><td class="text-right ${(r.net_pct||0)>0?'text-emerald-400':'text-rose-400'}">${r.net_pct}</td><td class=text-right>${r.rr_realized??'-'}</td><td class=text-right>${r.hold_days??'-'}d</td><td>${r.reason||''}</td></tr>`).join('')+'</table>';
 document.getElementById('jrn').innerHTML=t.trades.map(r=>{
  const last=r.notes&&r.notes.length?r.notes[r.notes.length-1]:{};
  return `<div class="bg-slate-800 rounded p-3 mb-2"><b>${r.name||r.symbol}(${r.symbol})</b> <span class=text-xs>${r.mode||''} · id ${r.id}</span>
   ${r.closed?`<span class="${(r.net_pct||0)>0?'text-emerald-400':'text-rose-400'}"> net ${r.net_pct}% (손익비 ${r.rr_realized??'-'})</span>`:'<span class=text-amber-400> 보유중</span>'}<br>
   <span class=text-xs>진입 ${f(r.entry_price)} 손절 ${f(r.stop)} 목표 ${f(r.target)} · 근거: ${r.rationale?Object.keys(r.rationale).filter(k=>r.rationale[k]).join(','):''}</span>
   ${r.premarket?`<br><span class="text-xs text-sky-400">프리장 예상 ${f(r.premarket.exp_price)} (${r.premarket.gap_pct>0?'+':''}${r.premarket.gap_pct}%)</span>`:''}
   <div class="grid grid-cols-3 gap-1 mt-2">
    <input id="ps_${r.id}" placeholder="심리상태" value="${last.psych||''}" class="bg-slate-700 text-xs p-1 rounded">
    <input id="mk_${r.id}" placeholder="실수분석" value="${last.mistake||''}" class="bg-slate-700 text-xs p-1 rounded">
    <input id="im_${r.id}" placeholder="개선점" value="${last.improve||''}" class="bg-slate-700 text-xs p-1 rounded">
   </div><button onclick="note('${r.id}')" class="mt-1 text-xs px-2 py-0.5 bg-indigo-600 rounded">일지 저장</button></div>`}).join('')||'<div class=text-slate-400>거래 기록 없음</div>';
}
async function note(id){await fetch('/api/note',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({id,psych:document.getElementById('ps_'+id).value,mistake:document.getElementById('mk_'+id).value,improve:document.getElementById('im_'+id).value})});load();}
load();setInterval(load,30000);tab('pos');
</script></body></html>"""


async def index(request):
    return HTMLResponse(_HTML)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/state", api_state),
    Route("/api/trades", api_trades),
    Route("/api/note", api_note, methods=["POST"]),
])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8091)
    args = ap.parse_args()
    print(f"추세추종 대시보드 → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
