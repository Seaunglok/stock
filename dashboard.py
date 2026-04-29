"""웹 대시보드 - 서비스 상태 + 에이전트 활동(검색 중인 종목/쿼리) + Supervisor 채팅
사용법:
  python dashboard.py            # http://localhost:9000
  python dashboard.py --port 9001
"""
import os
import re
import sys
import json
import uuid
import queue
import asyncio
import argparse
import threading
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).parent))

_TEMP = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
LOG_DIR = _TEMP / "mcp_logs"

SERVICES = [
    ("Supervisor",       8000, "agent",  "http://localhost:8000/.well-known/agent.json"),
    ("DataCollector",    8001, "agent",  "http://localhost:8001/.well-known/agent.json"),
    ("Analysis",         8002, "agent",  "http://localhost:8002/.well-known/agent.json"),
    ("Trading",          8003, "agent",  "http://localhost:8003/.well-known/agent.json"),
    ("kiwoom-trading",   8030, "mcp",    "http://localhost:8030/mcp/"),
    ("kiwoom-market",    8031, "mcp",    "http://localhost:8031/mcp/"),
    ("kiwoom-info",      8032, "mcp",    "http://localhost:8032/mcp/"),
    ("kiwoom-investor",  8033, "mcp",    "http://localhost:8033/mcp/"),
    ("kiwoom-portfolio", 8034, "mcp",    "http://localhost:8034/mcp/"),
    ("financial",        8040, "mcp",    "http://localhost:8040/mcp"),
    ("macro",            8041, "mcp",    "http://localhost:8041/mcp"),
    ("stock-analysis",   8042, "mcp",    "http://localhost:8042/mcp"),
    ("naver-news",       8050, "mcp",    "http://localhost:8050/mcp"),
    ("tavily-search",    3020, "mcp",    "http://localhost:3020/mcp"),
    ("closing-bet",      8060, "mcp",    "http://localhost:8060/mcp"),
]

AGENT_LOGS = {
    "supervisor":     LOG_DIR / "agent_supervisor.log",
    "data_collector": LOG_DIR / "agent_data_collector.log",
    "analysis":       LOG_DIR / "agent_analysis.log",
    "trading":        LOG_DIR / "agent_trading.log",
}

KOREAN_TICKERS = {
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER",
    "035720": "카카오",   "005380": "현대차",     "051910": "LG화학",
    "006400": "삼성SDI", "207940": "삼성바이오로직스", "068270": "셀트리온",
    "005490": "POSCO홀딩스", "028260": "삼성물산", "012330": "현대모비스",
    "066570": "LG전자",  "096770": "SK이노베이션", "017670": "SK텔레콤",
    "030200": "KT",      "055550": "신한지주",   "105560": "KB금융",
    "086790": "하나금융", "316140": "우리금융",
}

# 채팅 작업 추적 (in-memory) — 단일 워커가 큐를 소비해 한 번에 1개만 Supervisor 호출
_chats: dict[str, dict] = {}
_chats_lock = threading.Lock()
_chat_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def check_service(url: str, timeout: float = 1.5) -> tuple[bool, int]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.status
    except urllib.error.HTTPError as e:
        return (e.code < 500), e.code
    except Exception:
        return False, 0


def get_status() -> list[dict]:
    with ThreadPoolExecutor(max_workers=14) as ex:
        results = list(ex.map(lambda s: check_service(s[3]), SERVICES))
    out = []
    for (name, port, kind, url), (ok, code) in zip(SERVICES, results):
        out.append({"name": name, "port": port, "kind": kind, "up": ok, "code": code})
    return out


_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_TICKER_RE = re.compile(r"\b(\d{6})\b")
_TASK_STATE_RE = re.compile(r"TaskState\.(\w+)")
_TOOL_RE = re.compile(r"(call_data_collector|call_analysis_agent|call_trading_agent)")


def tail_lines(path: Path, n: int = 200) -> list[str]:
    if not path.exists():
        return []
    try:
        data = path.read_bytes()[-65536:]
        text = data.decode("utf-8", errors="replace")
        return text.splitlines()[-n:]
    except Exception:
        return []


def get_activity() -> dict:
    activity: dict = {"agents": {}, "recent_tickers": [], "last_state": None}
    seen_tickers: dict[str, str] = {}

    for agent, path in AGENT_LOGS.items():
        lines = tail_lines(path, 300)
        agent_info = {"last_ts": None, "last_state": None, "last_tool": None, "tickers": []}
        for line in reversed(lines):
            if agent_info["last_ts"] is None:
                m = _TIMESTAMP_RE.match(line)
                if m:
                    agent_info["last_ts"] = m.group(1)
            if agent_info["last_state"] is None:
                m = _TASK_STATE_RE.search(line)
                if m:
                    agent_info["last_state"] = m.group(1)
            if agent_info["last_tool"] is None:
                m = _TOOL_RE.search(line)
                if m:
                    agent_info["last_tool"] = m.group(1)
            for tk in _TICKER_RE.findall(line):
                if tk in KOREAN_TICKERS and tk not in seen_tickers:
                    seen_tickers[tk] = agent_info["last_ts"] or ""
                    agent_info["tickers"].append(tk)
            if (agent_info["last_state"] and agent_info["last_tool"]
                    and len(agent_info["tickers"]) >= 3):
                break
        activity["agents"][agent] = agent_info

    for tk, ts in sorted(seen_tickers.items(), key=lambda x: x[1], reverse=True)[:10]:
        activity["recent_tickers"].append(
            {"code": tk, "name": KOREAN_TICKERS.get(tk, "?"), "last_seen": ts}
        )

    sup = activity["agents"].get("supervisor", {})
    activity["last_state"] = sup.get("last_state")
    return activity


# ==================== Supervisor 채팅 ====================

async def _ask_supervisor_async(chat_id: str, question: str):
    from src.a2a_integration.a2a_lg_client_utils_v2 import A2AClientManagerV2

    def _set(**kw):
        with _chats_lock:
            _chats[chat_id].update(kw)

    try:
        async with A2AClientManagerV2(base_url="http://localhost:8000") as client:
            resp = await client.text_client.send(question)
        text = resp.text if hasattr(resp, "text") else str(resp)
        _set(state="completed", answer=text, finished_at=datetime.now().isoformat())
    except Exception as e:
        # 클라이언트 폴링 타임아웃이어도 task_id로 재폴링하면 결과 회수 가능
        _set(state="failed", error=str(e), finished_at=datetime.now().isoformat())


def _queue_position(cid: str) -> int:
    """현재 큐에서 해당 chat 의 대기 순번 (1-based, 0이면 즉시 실행 예정)"""
    with _chats_lock:
        waiting = [c for c in _chats.values() if c["state"] == "queued"]
    waiting.sort(key=lambda c: c["started_at"])
    for i, c in enumerate(waiting):
        if c["id"] == cid:
            return i + 1
    return 0


def _worker_loop():
    """큐를 직렬 소비해 Supervisor 동시 호출이 1개를 넘지 않게 한다."""
    while True:
        cid, question = _chat_queue.get()
        try:
            with _chats_lock:
                if cid in _chats:
                    _chats[cid]["state"] = "working"
                    _chats[cid]["dequeued_at"] = datetime.now().isoformat()
            asyncio.run(_ask_supervisor_async(cid, question))
        except Exception as e:
            with _chats_lock:
                if cid in _chats:
                    _chats[cid].update(
                        state="failed", error=str(e),
                        finished_at=datetime.now().isoformat(),
                    )
        finally:
            _chat_queue.task_done()


def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, daemon=True).start()
        _worker_started = True


def submit_chat(question: str) -> str:
    _ensure_worker()
    cid = uuid.uuid4().hex[:12]
    with _chats_lock:
        _chats[cid] = {
            "id": cid,
            "question": question,
            "state": "queued",
            "answer": None,
            "error": None,
            "started_at": datetime.now().isoformat(),
            "dequeued_at": None,
            "finished_at": None,
        }
    _chat_queue.put((cid, question))
    return cid


def list_chats() -> list[dict]:
    with _chats_lock:
        chats = sorted(_chats.values(), key=lambda c: c["started_at"], reverse=True)[:20]
        chats = [dict(c) for c in chats]
    for c in chats:
        if c["state"] == "queued":
            c["queue_position"] = _queue_position(c["id"])
    return chats


def get_chat(cid: str) -> dict | None:
    with _chats_lock:
        return _chats.get(cid)


# ==================== HTML ====================

HTML_PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Multi-Agent Kiwoom 대시보드</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
         background: #0d1117; color: #e6edf3; margin: 0; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #8b949e; font-size: 12px; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
          padding: 16px; }
  .card h2 { font-size: 14px; margin: 0 0 12px; color: #8b949e;
             text-transform: uppercase; letter-spacing: 0.5px; }
  .svc { display: flex; align-items: center; padding: 6px 0;
         border-bottom: 1px solid #21262d; font-size: 13px; }
  .svc:last-child { border-bottom: none; }
  .dot { width: 8px; height: 8px; border-radius: 50%; margin-right: 10px; flex-shrink: 0; }
  .up { background: #3fb950; box-shadow: 0 0 6px #3fb950; }
  .down { background: #f85149; }
  .name { flex: 1; font-weight: 500; }
  .port { color: #8b949e; font-size: 11px; }
  .summary { font-size: 13px; padding: 8px 12px; background: #0d1117;
             border-radius: 6px; margin-bottom: 12px; }
  .ticker { display: flex; justify-content: space-between; padding: 6px 0;
            border-bottom: 1px solid #21262d; font-size: 13px; }
  .ticker:last-child { border-bottom: none; }
  .code { font-family: ui-monospace, Consolas, monospace; color: #79c0ff; }
  .tname { flex: 1; margin: 0 12px; }
  .ts { color: #8b949e; font-size: 11px; }
  .agent-row { padding: 8px 0; border-bottom: 1px solid #21262d; font-size: 13px; }
  .agent-row:last-child { border-bottom: none; }
  .agent-name { font-weight: 600; color: #d2a8ff; }
  .agent-meta { color: #8b949e; font-size: 11px; margin-top: 2px; }
  .badge { display: inline-block; padding: 2px 6px; border-radius: 4px;
           font-size: 10px; margin-left: 6px; }
  .b-completed { background: #196c2e; color: #aff5b4; }
  .b-working { background: #9e6a03; color: #ffd33d; }
  .b-failed { background: #67060c; color: #ff7b72; }
  .b-submitted { background: #1f6feb; color: #cae8ff; }
  .b-queued { background: #30363d; color: #8b949e; }
  .empty { color: #6e7681; font-style: italic; font-size: 12px; }
  .footer { text-align: center; color: #6e7681; font-size: 11px; margin-top: 20px; }

  .chat-card { grid-column: 1 / -1; }
  .chat-form { display: flex; gap: 8px; margin-bottom: 12px; }
  .chat-input { flex: 1; background: #0d1117; border: 1px solid #30363d;
                color: #e6edf3; padding: 8px 12px; border-radius: 6px;
                font-size: 14px; font-family: inherit; }
  .chat-input:focus { outline: none; border-color: #58a6ff; }
  .chat-btn { background: #238636; color: white; border: none;
              padding: 8px 16px; border-radius: 6px; cursor: pointer;
              font-size: 14px; font-weight: 600; }
  .chat-btn:hover:not(:disabled) { background: #2ea043; }
  .chat-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .examples { font-size: 11px; color: #8b949e; margin-bottom: 12px; }
  .examples a { color: #58a6ff; cursor: pointer; margin-right: 12px; text-decoration: none; }
  .examples a:hover { text-decoration: underline; }

  .chat-item { background: #0d1117; border: 1px solid #30363d;
               border-radius: 6px; padding: 12px; margin-bottom: 12px; }
  .chat-q { font-weight: 600; color: #79c0ff; margin-bottom: 6px;
            display: flex; justify-content: space-between; align-items: center; }
  .chat-meta { font-size: 11px; color: #8b949e; margin-bottom: 8px; }
  .chat-a { background: #161b22; padding: 12px; border-radius: 4px;
            border-left: 3px solid #3fb950; max-height: 600px; overflow-y: auto; }
  .chat-a.working { border-left-color: #d29922; }
  .chat-a.queued { border-left-color: #6e7681; }
  .chat-a.failed { border-left-color: #f85149; }
  .chat-a h1, .chat-a h2, .chat-a h3 { margin-top: 12px; margin-bottom: 6px; }
  .chat-a h1 { font-size: 18px; } .chat-a h2 { font-size: 16px; } .chat-a h3 { font-size: 14px; }
  .chat-a p { margin: 6px 0; line-height: 1.5; }
  .chat-a table { border-collapse: collapse; margin: 8px 0; width: 100%; font-size: 12px; }
  .chat-a th, .chat-a td { border: 1px solid #30363d; padding: 4px 8px; }
  .chat-a th { background: #21262d; }
  .chat-a code { background: #21262d; padding: 1px 4px; border-radius: 3px;
                 font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
  .chat-a pre { background: #0d1117; padding: 8px; border-radius: 4px; overflow-x: auto; }
  .chat-a ul, .chat-a ol { padding-left: 20px; }
  .chat-a blockquote { border-left: 3px solid #30363d; margin: 8px 0;
                       padding-left: 12px; color: #8b949e; }
  .working-indicator { color: #d29922; font-style: italic; }
  .working-indicator::after { content: ''; animation: dots 1.5s steps(4) infinite;
                              display: inline-block; width: 24px; text-align: left; }
  @keyframes dots { 0% { content: ''; } 25% { content: '.'; }
                    50% { content: '..'; } 75% { content: '...'; } }
</style>
</head>
<body>
<h1>Multi-Agent Kiwoom 대시보드</h1>
<div class="sub">2초마다 자동 갱신 · <span id="now"></span></div>

<div class="grid">
  <div class="card">
    <h2>서비스 상태</h2>
    <div class="summary" id="summary">로딩 중...</div>
    <div id="agents"></div>
    <div style="height:8px"></div>
    <div id="mcps"></div>
  </div>

  <div class="card">
    <h2>에이전트 활동 / 검색 중인 종목</h2>
    <div id="recent_tickers" class="empty">최근 활동 없음</div>
    <div style="height:16px"></div>
    <h2 style="margin-top:8px">에이전트별 상태</h2>
    <div id="agent_activity"></div>
  </div>

  <div class="card chat-card">
    <h2>Supervisor에게 질문</h2>
    <form class="chat-form" id="chat-form">
      <input class="chat-input" id="chat-input" type="text"
             placeholder="예: 현재 한국에서 주목할 종목 알려줘"
             autocomplete="off" required />
      <button class="chat-btn" type="submit" id="chat-submit">전송</button>
    </form>
    <div class="examples">
      <span>예시:</span>
      <a data-q="현재 한국에서 주목할 종목 알려줘">주목할 종목</a>
      <a data-q="삼성전자(005930) 현재 주가를 알려줘">삼성전자 주가</a>
      <a data-q="SK하이닉스(000660) 종합 분석해줘">SK하이닉스 분석</a>
      <a data-q="2차전지 관련주 분석">2차전지 분석</a>
    </div>
    <div id="chats"></div>
  </div>
</div>

<div class="footer">d:\\kiwoom_rest_study\\multi_agent_kiwoom · dashboard.py</div>

<script>
function badge(state) {
  if (!state) return '';
  const cls = 'b-' + state.toLowerCase();
  return `<span class="badge ${cls}">${state}</span>`;
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function elapsed(startIso) {
  if (!startIso) return '';
  const sec = Math.floor((Date.now() - new Date(startIso).getTime()) / 1000);
  return sec + '초';
}

async function refreshStatus() {
  try {
    const [s, a] = await Promise.all([
      fetch('/api/status').then(r => r.json()),
      fetch('/api/activity').then(r => r.json()),
    ]);

    const agents = s.filter(x => x.kind === 'agent');
    const mcps = s.filter(x => x.kind === 'mcp');
    const upA = agents.filter(x => x.up).length;
    const upM = mcps.filter(x => x.up).length;
    document.getElementById('summary').innerHTML =
      `에이전트 <b>${upA}/${agents.length}</b> · MCP <b>${upM}/${mcps.length}</b>`;

    const renderSvc = arr => arr.map(x => `
      <div class="svc">
        <div class="dot ${x.up ? 'up' : 'down'}"></div>
        <div class="name">${x.name}</div>
        <div class="port">:${x.port}${x.up ? '' : (x.code ? ' (' + x.code + ')' : '')}</div>
      </div>`).join('');
    document.getElementById('agents').innerHTML = renderSvc(agents);
    document.getElementById('mcps').innerHTML = renderSvc(mcps);

    if (a.recent_tickers.length === 0) {
      document.getElementById('recent_tickers').innerHTML =
        '<div class="empty">최근 검색된 종목 없음</div>';
    } else {
      document.getElementById('recent_tickers').innerHTML = a.recent_tickers.map(t => `
        <div class="ticker">
          <span class="code">${t.code}</span>
          <span class="tname">${escapeHtml(t.name)}</span>
          <span class="ts">${t.last_seen || '-'}</span>
        </div>`).join('');
    }

    const agentNames = {
      supervisor: 'Supervisor', data_collector: 'DataCollector',
      analysis: 'Analysis', trading: 'Trading'
    };
    document.getElementById('agent_activity').innerHTML =
      Object.entries(a.agents).map(([key, v]) => `
        <div class="agent-row">
          <div><span class="agent-name">${agentNames[key]}</span>${badge(v.last_state)}</div>
          <div class="agent-meta">
            ${v.last_ts || '활동 없음'}
            ${v.last_tool ? ' · tool: ' + v.last_tool : ''}
            ${v.tickers.length ? ' · 종목: ' + v.tickers.join(', ') : ''}
          </div>
        </div>`).join('');
  } catch (e) {
    document.getElementById('summary').textContent = '갱신 실패: ' + e;
  }
}

async function refreshChats() {
  try {
    const list = await fetch('/api/chats').then(r => r.json());
    if (list.length === 0) {
      document.getElementById('chats').innerHTML =
        '<div class="empty">아직 질문이 없습니다. 위 입력창에 질문을 입력하세요.</div>';
      return;
    }
    document.getElementById('chats').innerHTML = list.map(c => {
      const stateBadge = badge(c.state);
      let body;
      if (c.state === 'queued') {
        const pos = c.queue_position || '?';
        body = `<div class="working-indicator">대기 중 (큐 ${pos}번째, ${elapsed(c.started_at)})</div>`;
      } else if (c.state === 'working') {
        const since = c.dequeued_at || c.started_at;
        body = `<div class="working-indicator">Supervisor가 답변 작성 중 (${elapsed(since)})</div>`;
      } else if (c.state === 'failed') {
        body = `<div style="color:#ff7b72">실패: ${escapeHtml(c.error || '')}</div>`;
      } else {
        body = marked.parse(c.answer || '');
      }
      return `
        <div class="chat-item">
          <div class="chat-q">
            <span>Q: ${escapeHtml(c.question)}</span>
            <span>${stateBadge}</span>
          </div>
          <div class="chat-meta">
            시작: ${c.started_at ? c.started_at.replace('T', ' ').slice(0, 19) : '-'}
            ${c.finished_at ? ' · 완료: ' + c.finished_at.replace('T', ' ').slice(0, 19) : ''}
          </div>
          <div class="chat-a ${c.state}">${body}</div>
        </div>`;
    }).join('');
  } catch (e) {
    console.error(e);
  }
}

async function refresh() {
  document.getElementById('now').textContent = new Date().toLocaleTimeString('ko-KR');
  await Promise.all([refreshStatus(), refreshChats()]);
}

document.getElementById('chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('chat-submit');
  const q = input.value.trim();
  if (!q) return;
  btn.disabled = true;
  try {
    await fetch('/api/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q}),
    });
    input.value = '';
    refreshChats();
  } catch (err) {
    alert('전송 실패: ' + err);
  } finally {
    btn.disabled = false;
  }
});

document.querySelectorAll('.examples a').forEach(a => {
  a.addEventListener('click', () => {
    document.getElementById('chat-input').value = a.dataset.q;
    document.getElementById('chat-input').focus();
  });
});

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(200, get_status())
        elif self.path == "/api/activity":
            self._json(200, get_activity())
        elif self.path == "/api/chats":
            self._json(200, list_chats())
        elif self.path.startswith("/api/chat/"):
            cid = self.path.split("/")[-1]
            chat = get_chat(cid)
            if chat:
                self._json(200, chat)
            else:
                self._json(404, {"error": "not found"})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path == "/api/ask":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._json(400, {"error": "invalid json"})
                return
            question = (payload.get("question") or "").strip()
            if not question:
                self._json(400, {"error": "empty question"})
                return
            cid = submit_chat(question)
            self._json(200, {"id": cid})
        else:
            self._send(404, b"not found", "text/plain")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"대시보드 실행 중: http://{args.host}:{args.port}")
    print("Ctrl+C 로 종료")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료.")
        server.shutdown()


if __name__ == "__main__":
    main()
