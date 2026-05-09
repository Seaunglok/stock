"""인터랙티브 대시보드 HTML 생성.

백테스트 픽 CSV를 읽어 종목별 차트 + 스코어 브레이크다운을 보여주는
단일 HTML 파일을 생성한다. OHLCV는 종목당 1회 저장해 파일 크기를 절약한다.

Usage:
    python scripts/gen_dashboard.py
    python scripts/gen_dashboard.py --csv docs/backtest_breadth_gate_v2_picks
    python scripts/gen_dashboard.py --mode standard
    python scripts/gen_dashboard.py --out docs/dashboard.html
    python scripts/gen_dashboard.py --recent 30   # 최근 30일만
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores

_OHLCV_CACHE_DIR = PROJECT_ROOT / "docs_cache" / "ohlcv"


# ──────────────────────────────────────────────
# OHLCV 캐시 로딩
# ──────────────────────────────────────────────

def _find_cache(code: str) -> Path | None:
    candidates = list(_OHLCV_CACHE_DIR.glob(f"{code}_*.json"))
    if not candidates:
        return None
    def _start(p: Path) -> str:
        parts = p.stem.split("_")
        return parts[1] if len(parts) >= 3 else "9999"
    return min(candidates, key=_start)


def load_ohlcv(code: str) -> list[dict]:
    path = _find_cache(code)
    if path is None:
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_picks(csv_path: Path) -> list[dict]:
    picks = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            picks.append({
                "date": row["date"],
                "code": row["code"],
                "name": row["name"],
                "score": float(row["score"]),
                "regime": row["regime"],
                "ret_pct": float(row["ret_pct"]),
            })
    return picks


# ──────────────────────────────────────────────
# 스코어 브레이크다운
# ──────────────────────────────────────────────

def _describe_component(key: str, val: float, bd: dict) -> str:
    if key == "volume_surge":
        ratio = bd.get("ratio", 0)
        return f"20일 평균 대비 {ratio:.1f}배" if ratio else f"점수 {val:.0f}"
    if key == "resistance_proximity":
        gap = bd.get("gap_pct", None)
        return f"60일 고점 대비 {gap:+.1f}%" if gap is not None else f"점수 {val:.0f}"
    if key == "candle_shape":
        wick = bd.get("upper_wick_ratio", None)
        bullish = bd.get("is_bullish", None)
        if wick is not None:
            bull_str = "양봉 ✓" if bullish else "음봉"
            return f"위꼬리 {wick:.1%} / {bull_str}"
        return f"점수 {val:.0f}"
    if key == "consolidation":
        dd = bd.get("drawdown_pct", None)
        rec = bd.get("recovery_pct", None)
        if dd is not None and rec is not None:
            return f"낙폭 {dd:+.1f}% → 회복 {rec:+.1f}%"
        return f"점수 {val:.0f}"
    return f"점수 {val:.0f}"


def _entry_exit(date_t: str, history: list[dict]) -> tuple[int | None, int | None]:
    """픽 날 종가(매수가)와 다음 거래일 시가(매도가)를 반환."""
    entry = exit_ = None
    for i, bar in enumerate(history):
        if bar["date"] == date_t:
            entry = int(round(bar["close"]))
            if i + 1 < len(history):
                exit_ = int(round(history[i + 1]["open"]))
            break
    return entry, exit_


def compute_breakdown(code: str, date_t: str, history: list[dict]) -> dict:
    window = [d for d in history if d["date"] <= date_t][-90:]
    if len(window) < 21:
        return {}
    ts = compute_technical_scores(window)
    components = {
        "volume_surge": round(ts.volume_surge, 1),
        "resistance_proximity": round(ts.resistance_proximity, 1),
        "candle_shape": round(ts.candle_shape, 1),
        "consolidation": round(ts.consolidation, 1),
    }
    reasons = {k: _describe_component(k, v, ts.breakdown.get(k, {}))
               for k, v in components.items()}
    return {"components": components, "reasons": reasons}


# ──────────────────────────────────────────────
# 데이터 준비
# ──────────────────────────────────────────────

def build_datasets(
    csv_files: list[Path],
    recent_days: int,
) -> tuple[dict[str, dict], dict[str, list]]:
    """모든 픽 CSV를 읽어 datasets + OHLCV 인덱스를 반환."""
    all_codes: set[str] = set()
    raw: dict[str, list[dict]] = {}  # mode → picks

    for csv_path in csv_files:
        mode_name = csv_path.stem.replace("picks_", "")
        picks = load_picks(csv_path)
        if recent_days > 0:
            cutoff = (datetime.now() - timedelta(days=recent_days)).strftime("%Y-%m-%d")
            picks = [p for p in picks if p["date"] >= cutoff]
        if picks:
            raw[mode_name] = picks
            all_codes.update(p["code"] for p in picks)

    # OHLCV 로딩 (코드당 1회)
    print(f"  [ohlcv] {len(all_codes)}개 종목 캐시 로딩...")
    histories: dict[str, list[dict]] = {}
    for i, code in enumerate(sorted(all_codes)):
        histories[code] = load_ohlcv(code)
        if (i + 1) % 100 == 0:
            print(f"    {i+1}/{len(all_codes)}")
    hits = sum(1 for h in histories.values() if h)
    print(f"  [ohlcv] 캐시 히트 {hits}/{len(all_codes)}")

    # OHLCV 인덱스: code → [[date,o,h,l,c], ...]  (compact)
    ohlcv_index: dict[str, list] = {}
    for code, h in histories.items():
        if h:
            ohlcv_index[code] = [[d["date"], d["open"], d["high"], d["low"], d["close"]] for d in h]

    # datasets 구성
    datasets: dict[str, dict] = {}
    for mode_name, picks in raw.items():
        print(f"  [{mode_name}] 스코어 계산 중 ({len(picks)}건)...")
        enriched = []
        for pk in picks:
            h = histories.get(pk["code"], [])
            bd = compute_breakdown(pk["code"], pk["date"], h) if h else {}
            # 매수가(픽 날 종가) / 매도가(다음날 시가)
            entry_price, exit_price = _entry_exit(pk["date"], h)
            enriched.append({
                "date": pk["date"],
                "code": pk["code"],
                "name": pk["name"],
                "score": round(pk["score"], 1),
                "regime": pk["regime"],
                "ret_pct": round(pk["ret_pct"], 4),
                "entry": entry_price,
                "exit": exit_price,
                "components": bd.get("components", {}),
                "reasons": bd.get("reasons", {}),
            })

        by_date: dict[str, list] = defaultdict(list)
        for pk in enriched:
            by_date[pk["date"]].append(pk)

        dates = sorted(by_date.keys(), reverse=True)
        n = len(picks)
        datasets[mode_name] = {
            "mode": mode_name,
            "total": n,
            "winrate": round(sum(1 for p in picks if p["ret_pct"] > 0) / n * 100, 1) if n else 0,
            "avg_ret": round(sum(p["ret_pct"] for p in picks) / n, 4) if n else 0,
            "dates": dates,
            "by_date": dict(by_date),
        }

    return datasets, ohlcv_index


# ──────────────────────────────────────────────
# HTML 렌더링
# ──────────────────────────────────────────────

def render_html(datasets: dict[str, dict], ohlcv_index: dict[str, list]) -> str:
    json_data = json.dumps(datasets, ensure_ascii=False, separators=(",", ":"))
    ohlcv_json = json.dumps(ohlcv_index, ensure_ascii=False, separators=(",", ":"))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Closing-Bet 픽 대시보드</title>
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
<style>
:root {{
  --bg: #f6f8fa;
  --card: #fff;
  --border: #e1e4e8;
  --primary: #0969da;
  --green: #1a7f37;
  --red: #cf222e;
  --muted: #6e7781;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system,"Segoe UI",sans-serif; font-size: 14px; background: var(--bg); color: #24292f; }}

/* ── 헤더 ── */
.header {{
  background: #24292f; color: #fff;
  padding: 12px 20px;
  display: flex; align-items: center; gap: 14px;
  position: sticky; top: 0; z-index: 100;
  box-shadow: 0 1px 4px rgba(0,0,0,.35);
}}
.header h1 {{ font-size: 15px; font-weight: 700; white-space: nowrap; }}
.header-meta {{ font-size: 12px; color: #8b949e; }}
.mode-tabs {{ display: flex; gap: 4px; margin-left: auto; flex-shrink: 0; }}
.mode-tab {{
  padding: 5px 13px; border-radius: 6px;
  border: 1px solid #555; background: transparent;
  color: #ccc; cursor: pointer; font-size: 12px; transition: all .15s;
}}
.mode-tab.active {{ background: var(--primary); border-color: var(--primary); color: #fff; }}

/* ── 레이아웃 ── */
.layout {{ display: flex; height: calc(100vh - 45px); }}

/* ── 사이드바 ── */
.sidebar {{
  width: 185px; background: var(--card);
  border-right: 1px solid var(--border);
  overflow-y: auto; flex-shrink: 0; display: flex; flex-direction: column;
}}
.sidebar-hd {{
  padding: 10px 14px 8px; font-size: 11px; font-weight: 700;
  color: var(--muted); text-transform: uppercase; letter-spacing: .6px;
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--card); z-index: 1;
}}
.date-item {{
  padding: 9px 12px; cursor: pointer;
  border-left: 3px solid transparent; transition: all .1s;
  display: flex; justify-content: space-between; align-items: center;
}}
.date-item:hover {{ background: var(--bg); }}
.date-item.active {{ border-left-color: var(--primary); background: #ddf0ff; font-weight: 700; }}
.date-str {{ font-size: 12px; }}
.r-badge {{
  font-size: 10px; border-radius: 4px; padding: 1px 5px; font-weight: 700;
}}
.r-strong {{ background: #d1f7dd; color: #1a7f37; }}
.r-neutral {{ background: #fff3c4; color: #9a6700; }}
.r-weak {{ background: #ffdce0; color: var(--red); }}

/* ── 메인 ── */
.main {{ flex: 1; overflow-y: auto; padding: 18px 22px; }}

/* ── 요약 바 ── */
.summary-bar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }}
.stat-card {{
  background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 16px; min-width: 120px;
}}
.stat-card .lbl {{ font-size: 11px; color: var(--muted); margin-bottom: 3px; }}
.stat-card .val {{ font-size: 22px; font-weight: 700; }}
.green {{ color: var(--green); }}
.red {{ color: var(--red); }}

/* ── 날짜 헤딩 ── */
.date-heading {{
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 14px; padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}}
.date-heading h2 {{ font-size: 17px; font-weight: 700; }}
.regime-pill {{
  padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700;
}}
.day-meta {{ font-size: 12px; color: var(--muted); }}

/* ── 픽 그리드 ── */
.picks-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 12px; margin-bottom: 24px;
}}

/* ── 종목 카드 ── */
.pick-card {{
  background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden;
  transition: box-shadow .2s, border-color .2s; cursor: pointer;
}}
.pick-card:hover {{ box-shadow: 0 3px 10px rgba(0,0,0,.07); }}
.pick-card.expanded {{ border-color: var(--primary); box-shadow: 0 0 0 2px #b6d4f9; }}

.card-top {{
  padding: 13px 15px 8px;
  display: flex; justify-content: space-between; align-items: flex-start;
}}
.card-name {{ font-size: 14px; font-weight: 700; margin-bottom: 2px; }}
.card-code {{ font-size: 11px; color: var(--muted); }}
.score-badge {{
  background: #f0f6ff; border: 1px solid #b6d4f9;
  border-radius: 8px; padding: 6px 10px; text-align: center; min-width: 52px;
}}
.score-num {{ font-size: 17px; font-weight: 700; color: var(--primary); line-height: 1; }}
.score-lbl {{ font-size: 10px; color: var(--muted); margin-top: 1px; }}

.card-ret-row {{
  padding: 4px 15px 10px;
  display: flex; align-items: baseline; gap: 8px;
}}
.card-ret {{
  font-size: 22px; font-weight: 700;
}}
.card-ret.pos {{ color: var(--green); }}
.card-ret.neg {{ color: var(--red); }}
.card-ret.zero {{ color: var(--muted); }}
.card-prices {{
  display: flex; gap: 10px; margin-left: auto;
  font-size: 12px; flex-direction: column; align-items: flex-end; line-height: 1.5;
}}
.price-row {{ display: flex; align-items: center; gap: 4px; }}
.price-lbl {{
  font-size: 10px; font-weight: 700; color: var(--muted);
  background: #f0f0f0; border-radius: 3px; padding: 1px 4px;
}}
.price-buy {{ color: #d24; font-weight: 700; }}
.price-sell {{ color: #26d; font-weight: 700; }}

/* ── 스코어 바 ── */
.score-bars {{ padding: 8px 15px 10px; border-top: 1px solid var(--border); }}
.bar-row {{ display: flex; align-items: center; gap: 7px; margin-bottom: 6px; }}
.bar-label {{ font-size: 11px; color: var(--muted); width: 66px; flex-shrink: 0; }}
.bar-track {{ flex: 1; background: #f0f0f0; border-radius: 3px; height: 7px; }}
.bar-fill {{ height: 100%; border-radius: 3px; transition: width .4s; }}
.bar-val {{ font-size: 11px; font-weight: 700; width: 28px; text-align: right; }}

/* ── 확장 패널 ── */
.card-header {{ cursor: pointer; user-select: none; }}
.card-header:hover .card-name {{ color: var(--primary); }}
.expand-panel {{ display: none; border-top: 1px solid var(--border); background: #fafbfc; }}
.pick-card.expanded .expand-panel {{ display: block; }}
.chart-wrap {{ padding: 6px 6px 0; }}
.breakdown-sec {{ padding: 10px 15px 13px; }}
.breakdown-title {{
  font-size: 11px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: .5px; margin-bottom: 7px;
}}
.reason-list {{ list-style: none; font-size: 12px; line-height: 1.8; }}
.reason-list li::before {{ content: "▸ "; color: var(--primary); font-weight: 700; }}
.gate-note {{
  margin-top: 7px; padding: 5px 9px;
  background: #fff3c4; border-radius: 5px; font-size: 12px; color: #9a6700;
}}

::-webkit-scrollbar {{ width: 5px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: #d0d7de; border-radius: 3px; }}

@media (max-width: 650px) {{
  .layout {{ flex-direction: column; height: auto; }}
  .sidebar {{ width: 100%; height: 130px; border-right: none; border-bottom: 1px solid var(--border); }}
  .picks-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>

<div class="header">
  <h1>📈 Closing-Bet 픽 대시보드</h1>
  <span class="header-meta" id="hdr-meta">생성: {now}</span>
  <div class="mode-tabs" id="mode-tabs"></div>
</div>

<div class="layout">
  <nav class="sidebar">
    <div class="sidebar-hd">날짜</div>
    <div id="date-list"></div>
  </nav>
  <main class="main" id="main">
    <div class="summary-bar" id="summary-bar"></div>
    <div id="content"></div>
  </main>
</div>

<script>
const DATASETS = {json_data};
const OHLCV = {ohlcv_json};

const RE = {{strong:"🟢",neutral:"🟡",weak:"🔴"}};
const RL = {{strong:"강세",neutral:"중립",weak:"약세"}};
const RC = {{strong:"r-strong",neutral:"r-neutral",weak:"r-weak"}};
const RS = {{
  strong:"background:#d1f7dd;color:#1a7f37",
  neutral:"background:#fff3c4;color:#9a6700",
  weak:"background:#ffdce0;color:#cf222e"
}};
const CL = {{
  volume_surge:"거래대금",
  resistance_proximity:"저항선",
  candle_shape:"캔들",
  consolidation:"조정회복"
}};
const CC = {{
  volume_surge:"#0969da",
  resistance_proximity:"#8250df",
  candle_shape:"#cf222e",
  consolidation:"#1a7f37"
}};

let mode = Object.keys(DATASETS)[0];
let selDate = null;
const drawn = new Set();

function fmt(v, d=2) {{ return (v>0?"+":"")+v.toFixed(d); }}
function pcls(v) {{ return v>0?"pos":v<0?"neg":"zero"; }}
function cid(p) {{ return "c_"+p.date+"_"+p.code; }}

function renderTabs() {{
  document.getElementById("mode-tabs").innerHTML =
    Object.keys(DATASETS).map(m=>
      `<button class="mode-tab${{m===mode?" active":""}}" onclick="switchMode('${{m}}')">${{m}}</button>`
    ).join("");
}}

function switchMode(m) {{
  mode = m; selDate = null; drawn.clear(); renderAll();
}}

function renderSummary() {{
  const d = DATASETS[mode];
  const wr = d.winrate, av = d.avg_ret;
  document.getElementById("summary-bar").innerHTML = `
    <div class="stat-card"><div class="lbl">전체 픽</div><div class="val">${{d.total}}건</div></div>
    <div class="stat-card"><div class="lbl">승률</div><div class="val ${{wr>=50?"green":"red"}}">${{wr.toFixed(1)}}%</div></div>
    <div class="stat-card"><div class="lbl">평균 수익</div><div class="val ${{av>=0?"green":"red"}}">${{fmt(av)}}%</div></div>
    <div class="stat-card"><div class="lbl">날짜 수</div><div class="val">${{d.dates.length}}일</div></div>
  `;
}}

function renderDateList() {{
  const d = DATASETS[mode];
  document.getElementById("date-list").innerHTML = d.dates.map(dt => {{
    const picks = d.by_date[dt];
    const rg = picks[0]?.regime || "neutral";
    const wins = picks.filter(p=>p.ret_pct>0).length;
    const act = dt===selDate ? " active" : "";
    return `<div class="date-item${{act}}" onclick="selDay('${{dt}}')">
      <span class="date-str">${{dt}}</span>
      <span class="r-badge ${{RC[rg]||"r-neutral"}}">${{RE[rg]}}</span>
    </div>`;
  }}).join("");
}}

function selDay(dt) {{
  selDate = dt;
  document.querySelectorAll(".date-item").forEach(el=>
    el.classList.toggle("active", el.querySelector(".date-str")?.textContent===dt)
  );
  renderContent();
  document.getElementById("main").scrollTop = 0;
}}

function renderContent() {{
  const d = DATASETS[mode];
  if (!selDate && d.dates.length) selDate = d.dates[0];
  if (!selDate) {{ document.getElementById("content").innerHTML=""; return; }}
  const picks = (d.by_date[selDate]||[]).slice().sort((a,b)=>b.score-a.score);
  const rg = picks[0]?.regime||"neutral";
  const wins = picks.filter(p=>p.ret_pct>0).length;
  const avg = picks.reduce((s,p)=>s+p.ret_pct,0)/(picks.length||1);
  document.getElementById("content").innerHTML = `
    <div class="date-heading">
      <h2>${{selDate}}</h2>
      <span class="regime-pill" style="${{RS[rg]||""}}">${{RE[rg]}} ${{RL[rg]}} 레짐</span>
      <span class="day-meta">${{picks.length}}종목 · 승률 ${{picks.length?Math.round(wins/picks.length*100):0}}% · 평균 ${{fmt(avg)}}%</span>
    </div>
    <div class="picks-grid">${{picks.map(p=>cardHtml(p)).join("")}}</div>
  `;
}}

function cardHtml(p) {{
  const id = cid(p);
  const comps = p.components||{{}};
  const reasons = p.reasons||{{}};
  const barKeys = ["volume_surge","resistance_proximity","candle_shape","consolidation"];
  const bars = barKeys.map(k=>{{
    const v = comps[k]??0;
    return `<div class="bar-row">
      <span class="bar-label">${{CL[k]}}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${{v}}%;background:${{CC[k]}}"></div></div>
      <span class="bar-val">${{v.toFixed(0)}}</span>
    </div>`;
  }}).join("");

  const reasonItems = barKeys
    .filter(k=>(comps[k]??0)>0)
    .map(k=>`<li><b>${{CL[k]}}</b> (${{(comps[k]??0).toFixed(0)}}점): ${{reasons[k]||""}}</li>`)
    .join("");

  const hasOhlcv = !!OHLCV[p.code];
  const chartDiv = hasOhlcv
    ? `<div class="chart-wrap"><div id="ch_${{id}}" style="height:330px"></div></div>`
    : `<div style="padding:14px;color:var(--muted);text-align:center;font-size:12px">차트 데이터 없음</div>`;

  const gateNote = (p.regime==="neutral"&&p.score<65)
    ? `<div class="gate-note">ℹ️ 중립 레짐 composite ${{p.score}} (임계 65)</div>` : "";

  return `<div class="pick-card" id="${{id}}">
    <div class="card-header" onclick="toggle('${{id}}','${{p.date}}','${{p.code}}')">
      <div class="card-top">
        <div><div class="card-name">${{p.name||p.code}}</div><div class="card-code">${{p.code}}</div></div>
        <div class="score-badge">
          <div class="score-num">${{p.score.toFixed(0)}}</div>
          <div class="score-lbl">composite</div>
        </div>
      </div>
      <div class="card-ret-row">
        <div class="card-ret ${{pcls(p.ret_pct)}}">${{fmt(p.ret_pct)}}%</div>
        <div class="card-prices">
          <div class="price-row"><span class="price-lbl">매수</span><span class="price-buy">${{p.entry!=null?p.entry.toLocaleString('ko-KR')+'원':'-'}}</span></div>
          <div class="price-row"><span class="price-lbl">매도</span><span class="price-sell">${{p.exit!=null?p.exit.toLocaleString('ko-KR')+'원':'-'}}</span></div>
        </div>
      </div>
      <div class="score-bars">${{bars}}</div>
    </div>
    <div class="expand-panel" onclick="event.stopPropagation()">
      ${{chartDiv}}
      <div class="breakdown-sec">
        <div class="breakdown-title">선정 과정</div>
        <ul class="reason-list">${{reasonItems}}</ul>
        ${{gateNote}}
      </div>
    </div>
  </div>`;
}}

function toggle(id, date, code) {{
  const el = document.getElementById(id);
  if (!el) return;
  const was = el.classList.contains("expanded");
  document.querySelectorAll(".pick-card.expanded").forEach(c=>c.classList.remove("expanded"));
  if (!was) {{
    el.classList.add("expanded");
    if (OHLCV[code] && !drawn.has(id)) drawChart(id, date, code);
  }}
}}

function fmtPrice(v) {{
  return v!=null ? v.toLocaleString('ko-KR')+'원' : '-';
}}

function drawChart(id, pickDate, code) {{
  const divId = "ch_"+id;
  const el = document.getElementById(divId);
  if (!el) return;
  drawn.add(id);

  const allBars = OHLCV[code]; // [[date,o,h,l,c], ...]
  const allDates = allBars.map(b=>b[0]);

  // pickDate 기준 앞 45봉 + 뒤 8봉 (매도 이후도 보이게)
  const idx = allDates.indexOf(pickDate);
  const start = Math.max(0, idx-45);
  const end = Math.min(allBars.length, idx+9);
  const bars = allBars.slice(start, end);
  const dates = bars.map(b=>b[0]);
  const opens = bars.map(b=>b[1]);
  const highs = bars.map(b=>b[2]);
  const lows = bars.map(b=>b[3]);
  const closes = bars.map(b=>b[4]);

  const localIdx = dates.indexOf(pickDate);
  const nextDates = dates.filter(d=>d>pickDate);
  const nextDate = nextDates[0]||null;
  const nextLocalIdx = nextDate ? dates.indexOf(nextDate) : -1;

  // pick 정보
  const d = DATASETS[mode];
  const dayPicks = d.by_date[pickDate]||[];
  const pk = dayPicks.find(p=>p.code===code);
  const retPct = pk ? pk.ret_pct : 0;
  const retColor = retPct>=0 ? "#1a7f37" : "#cf222e";
  const entryPrice = pk?.entry ?? (localIdx>=0 ? closes[localIdx] : null);
  const exitPrice  = pk?.exit  ?? (nextLocalIdx>=0 ? opens[nextLocalIdx] : null);

  // ── 캔들 트레이스 ──
  const traces = [{{
    type:"candlestick", x:dates,
    open:opens, high:highs, low:lows, close:closes,
    increasing:{{line:{{color:"#d24",width:1.5}}, fillcolor:"rgba(221,34,34,0.8)"}},
    decreasing:{{line:{{color:"#26d",width:1.5}}, fillcolor:"rgba(34,68,221,0.8)"}},
    showlegend:false,
    hovertemplate:"<b>%{{x}}</b><br>시가 %{{open:,.0f}}<br>고가 %{{high:,.0f}}<br>저가 %{{low:,.0f}}<br>종가 %{{close:,.0f}}<extra></extra>"
  }}];

  // ── shapes (세로선) & annotations (가격 라벨) ──
  const shapes = [];
  const annotations = [];

  if (localIdx>=0) {{
    // 매수 세로선
    shapes.push({{
      type:"line", xref:"x", yref:"paper",
      x0:pickDate, x1:pickDate, y0:0, y1:1,
      line:{{color:"rgba(26,127,55,0.4)",width:1.5,dash:"dot"}}
    }});
    // 매수 마커
    traces.push({{
      type:"scatter", mode:"markers",
      x:[pickDate], y:[lows[localIdx]*0.982],
      marker:{{symbol:"triangle-up",color:"#1a7f37",size:14,line:{{color:"#fff",width:1}}}},
      showlegend:false, hoverinfo:"skip"
    }});
    // 매수 가격 라벨 (캔들 옆 말풍선)
    if (entryPrice!=null) {{
      annotations.push({{
        xref:"x", yref:"y",
        x:pickDate, y:entryPrice,
        text:`<b>매수</b><br>${{fmtPrice(entryPrice)}}`,
        showarrow:true, arrowhead:2, arrowsize:1, arrowwidth:1.5,
        arrowcolor:"#1a7f37", ax:30, ay:-45,
        font:{{size:11,color:"#1a7f37"}},
        bgcolor:"rgba(255,255,255,0.92)",
        bordercolor:"#1a7f37", borderpad:4, borderwidth:1
      }});
    }}
  }}

  if (nextLocalIdx>=0) {{
    // 매도 세로선
    shapes.push({{
      type:"line", xref:"x", yref:"paper",
      x0:nextDate, x1:nextDate, y0:0, y1:1,
      line:{{color:`rgba(${{retPct>=0?"26,127,55":"207,34,46"}},0.4)`,width:1.5,dash:"dot"}}
    }});
    // 매도 마커
    traces.push({{
      type:"scatter", mode:"markers",
      x:[nextDate], y:[highs[nextLocalIdx]*1.018],
      marker:{{symbol:"triangle-down",color:retColor,size:14,line:{{color:"#fff",width:1}}}},
      showlegend:false, hoverinfo:"skip"
    }});
    // 매도 가격 라벨
    if (exitPrice!=null) {{
      const retStr = (retPct>=0?"+":"")+retPct.toFixed(2)+"%";
      annotations.push({{
        xref:"x", yref:"y",
        x:nextDate, y:exitPrice,
        text:`<b>매도 ${{retStr}}</b><br>${{fmtPrice(exitPrice)}}`,
        showarrow:true, arrowhead:2, arrowsize:1, arrowwidth:1.5,
        arrowcolor:retColor, ax:30, ay:45,
        font:{{size:11,color:retColor}},
        bgcolor:"rgba(255,255,255,0.92)",
        bordercolor:retColor, borderpad:4, borderwidth:1
      }});
    }}
  }}

  Plotly.newPlot(el, traces, {{
    margin:{{l:60,r:15,t:15,b:45}},
    xaxis:{{
      rangeslider:{{visible:false}},
      type:"category",
      tickangle:-45, tickfont:{{size:9}},
      showgrid:true, gridcolor:"#eee"
    }},
    yaxis:{{
      tickfont:{{size:10}}, tickformat:",.0f",
      showgrid:true, gridcolor:"#eee"
    }},
    plot_bgcolor:"#fafbfc", paper_bgcolor:"#fafbfc",
    height:330,
    shapes, annotations,
    dragmode:"zoom",
  }}, {{
    responsive:true,
    scrollZoom:true,
    displayModeBar:true,
    modeBarButtonsToRemove:[
      "autoScale2d","lasso2d","select2d",
      "hoverClosestCartesian","hoverCompareCartesian","toggleSpikelines"
    ],
    displaylogo:false,
    toImageButtonOptions:{{format:"png",height:500,width:900}}
  }});

  // 더블클릭으로 리셋 (category 축에서 resetScale 직접 연결)
  el.on("plotly_doubleclick", () => Plotly.relayout(el, {{"xaxis.autorange":true,"yaxis.autorange":true}}));
}}

function renderAll() {{
  renderTabs();
  renderSummary();
  renderDateList();
  const d = DATASETS[mode];
  if (!selDate && d.dates.length) selDate = d.dates[0];
  renderContent();
  // 사이드바 active 항목 스크롤
  requestAnimationFrame(()=>{{
    document.querySelector(".date-item.active")?.scrollIntoView({{block:"nearest"}});
  }});
}}

renderAll();
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path,
                   default=PROJECT_ROOT / "docs" / "backtest_breadth_gate_v2_picks",
                   help="picks CSV 디렉터리 또는 단일 CSV 파일")
    p.add_argument("--mode", default="all",
                   help="포함할 모드 (standard|inverted|all)")
    p.add_argument("--recent", type=int, default=0,
                   help="최근 N일 픽만 포함 (0=전체)")
    p.add_argument("--out", type=Path,
                   default=PROJECT_ROOT / "docs" / "dashboard.html")
    args = p.parse_args()

    if args.csv.is_dir():
        csv_files = sorted(args.csv.glob("picks_*.csv"))
    else:
        csv_files = [args.csv]

    if args.mode != "all":
        csv_files = [f for f in csv_files if args.mode in f.stem]

    if not csv_files:
        print(f"CSV 파일을 찾을 수 없습니다: {args.csv}")
        sys.exit(1)

    print(f"[처리] {len(csv_files)}개 CSV: {[f.name for f in csv_files]}")
    datasets, ohlcv_index = build_datasets(csv_files, args.recent)

    if not datasets:
        print("데이터가 없습니다.")
        sys.exit(1)

    print(f"\n[렌더링] HTML 생성 중...")
    html = render_html(datasets, ohlcv_index)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    size_kb = args.out.stat().st_size / 1024
    print(f"[저장] {args.out} ({size_kb:.0f} KB)")
    for m, d in datasets.items():
        print(f"  {m}: {d['total']}건 / 승률 {d['winrate']:.1f}% / 평균 {d['avg_ret']:+.4f}%")


if __name__ == "__main__":
    main()
