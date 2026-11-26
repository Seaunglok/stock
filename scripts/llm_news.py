"""Claude 뉴스 판단 일지 — 앞으로만 쌓고, 정해 둔 날 미리 정한 가설로 판정 (2026-11-25, 사전 선언).

운용자(11-25): "챗gpt 나 제미나이로 투자 많이 한다고 하는데… 더 분발할 필요가 있어" → Claude 뉴스 판단을 정직하게 시험하자는
제안에 "시작하자". **매매 판단이 아니다** — 주문·리그 비중에 쓰지 않고 기록만 한다(11-19 평가: 언어 모델 매매 주장은 정직한
평가에서 무너졌다 — 과거로는 못 잰다, 모델이 과거를 이미 읽었다). 그래서 모델이 배운 적 없는 **앞으로의 날**로만 잰다.

매일(판단 배치 끝, 시장 일지 close 뒤) 그날 모은 뉴스 제목·공시 제목·일정을 Claude 에게 주고, 다음 5거래일 코스피 방향을
묻는다. 답은 `data/llm_news/daily.csv` 한 줄, 넣은 글 전체는 `data/llm_news/inputs/<날짜>.txt`(SHA256 을 줄에 남김).
결과(코스피 수익)는 파일에 넣지 않고 판정 때 계산한다.

조건(매일 같다 — 바꾸면 그 뒤 기록은 다른 시험)
  모델     MODEL 고정(claude-opus-5-5). 답한 모델이 다르면 실패로 본다(대체 모델로 채우지 않는다).
  깨끗함   headless `claude -p` · 도구 없음(--tools "") · MCP 없음 · 설정·훅·플러그인 없음(--setting-sources "") ·
           프로젝트 밖 폴더에서(지침·메모리 없음) · 세션 저장 안 함 · 답 형식 JSON 스키마.
  인증     구독 로그인(정액제)만 — 자식 환경에서 API 인증 변수(API_AUTH_ENV)를 뺀다(11-26). `.env` 의
           ANTHROPIC_API_KEY 가 ops_base(trend_config) 로 환경에 올라와 claude 에게 넘어가면, claude 는 구독보다
           API 키를 먼저 써서 API 계정으로 과금한다 — 11-26 "Credit balance is too low" 실패가 이것. 같은 모델·같은 글이라
           시험 조건은 그대로다(청구 경로만). cost_usd 는 claude 가 알려 주는 환산값일 뿐 구독에선 청구되지 않는다.
           로그인이 만료되면 실패 알림에 그 문구가 나온다 → 운용자가 터미널 `claude` → `/login` 뒤 그날 안에 재실행.
  넣는 글  `market_journal` 그날 파일에서 정해진 규칙으로(같은 파일이면 같은 글): 주요사항보고 공시 제목 전부 · 일정 ·
           대표 제목(아침·장중) · 장중 뉴스 최신 N_CLOSE(300) · 아침 뉴스 최신 N_MORNING(100) — 제목 중복 제거.
           가격·수급 숫자는 따로 주지 않는다(제목에 든 것만).
  언제     그날(d) 안에만 묻는다 — 다음 날 묻거나 지난 날을 채우지 않는다(뒤늦게 물으면 미래를 아는 상태가 될 수 있다).
           같은 날은 한 번만(이미 답이 있으면 다시 묻지 않는다). 거래일만(장 마감 잠정 수급이 있는 날).
  답       direction −2(크게 약함) … +2(크게 강함) · risk 높음/보통/낮음(5거래일 안 −5% 이상 하락 위험) · reason.

가설 (선언 — 판정일 전엔 결과를 보지 않는다: 그 전 실행은 '해당 날 수'만 보여 준다)
  L1 Claude 부정(direction ≤ −1) 날 뒤 5일(다음 날 시가 → 6일째 시가, ^KS11)이 평소보다 약하다.
  L2 Claude 긍정(direction ≥ +1) 날 뒤 5일이 평소보다 강하다.
판정일   기록 JUDGE_DAYS(120)거래일(2027-05 무렵). 해당 날이 모자라면 기준을 낮추지 않고 미룬다.
통과     (N2 와 같은 잣대) 해당 날 ≥ MIN_EVENTS(15) · 뒤 5일 평균이 기록 기간 전체 평균보다 GAP_PCT(0.5)%p 이상 약함(L2 는 강함) ·
         하락(L2 는 상승) 적중 ≥ 기저율 + HIT_GAIN_PP(10)%p
         **그리고** 구간 섞기 검정 p ≤ P_MAX(0.01) — 판단 열을 BLOCK(10)거래일 구간으로 잘라 순서를 DRAWS(10,000)번
         무작위로 섞었을 때(시드 SEED 고정) 같은 차이 이상이 나오는 비율. 판단이 며칠씩 몰리는 것·뒤 5일 수익이 겹치는 것을
         구간 안에 그대로 둔 채 재는 우연 기준(날짜별 섞기는 뭉침을 깨 너무 쉽게 통과한다 · 순환 이동은 120일이면 경우가
         100개 남짓이라 0.01 에 못 닿는다). 0.01 = 뉴스 가설 묶음(N1~N3 · L1~L2) 5개 본페로니 단측 5%.
         시험 횟수 장부(`lab_trials`)에 2 를 더한다.
보고만   L1 과 N2(헤드라인 부정 단어 비율 — 규칙 기반)를 같은 기간에 나란히 · risk 높음 날 뒤 5일 최저 · 방향 점수와 뒤 5일 순위 상관.
통과하면  공격형 리그 앞으로만 기록 멤버 후보(실계좌 없음 — 11-10 결정). 매매 판단에 넣는 것은 그 뒤에 운용자가 정한다.

사용:  python scripts/llm_news.py            # 오늘 기록(판단 배치가 부른다)
       python scripts/llm_news.py --status   # 기록 수·해당 날 수(결과 없음)
       python scripts/llm_news.py --judge    # 기록 JUDGE_DAYS 이상일 때만 판정
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import atomic_io as AIO  # noqa: E402
import market_journal as MJ  # noqa: E402

OUT_DIR = _ROOT / "data" / "llm_news"
FILE = OUT_DIR / "daily.csv"
INPUTS = OUT_DIR / "inputs"
CLAUDE_EXE = os.getenv("LLM_NEWS_CLAUDE", r"C:\Users\hihih\.local\bin\claude.exe")
RUN_DIR = Path(tempfile.gettempdir()) / "llm_news_cwd"      # 프로젝트 밖 — CLAUDE.md·메모리가 끼지 않게
MODEL = "claude-opus-5-5"
# 자식 claude 에게 넘기지 않는 변수 — 하나라도 있으면 claude 가 구독 로그인 대신 그 경로(API 과금·다른 서버)로 간다
API_AUTH_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
TIMEOUT_S = 600
N_CLOSE = 300
N_MORNING = 100
N_CALENDAR = 20

H = 5
JUDGE_DAYS = 120
MIN_EVENTS = 15
GAP_PCT = 0.5
HIT_GAIN_PP = 10.0
P_MAX = 0.01
BLOCK = 10
DRAWS = 10_000
SEED = 20261125

COLS = ["date", "asked_at", "model", "direction", "risk", "reason", "n_titles", "input_sha256", "cost_usd", "duration_ms"]
SCHEMA = {"type": "object",
          "properties": {"direction": {"type": "integer", "minimum": -2, "maximum": 2},
                         "risk": {"type": "string", "enum": ["높음", "보통", "낮음"]},
                         "reason": {"type": "string"}},
          "required": ["direction", "risk", "reason"], "additionalProperties": False}
SYSTEM = ("너는 한국 주식시장을 보는 분석가다. 사용자가 주는 그날의 뉴스 제목·공시 제목·일정만 근거로 판단한다. "
          "그날 뒤의 일은 모른다 — 다른 지식으로 추측하지 않는다. 답은 지정한 JSON 형식으로만 한다.")
QUESTION = """질문: 아래 글만 읽고 다음 5거래일 코스피 흐름을 판단하라 — 내일 시가에 사서 6거래일째 시가에 판다고 할 때의 등락.
  direction: -2 크게 약함(-3% 이하 예상) · -1 약함 · 0 판단 어려움·보합 · +1 강함 · +2 크게 강함(+3% 이상 예상)
  risk: 그 5거래일 안에 코스피가 크게(-5% 이상) 빠질 위험 — 높음 · 보통 · 낮음
  reason: 판단의 핵심 근거 한두 문장(200자 이내)
가격 차트·수급 숫자는 따로 주지 않는다(제목에 든 것만 본다)."""
WEEKDAY = "월화수목금토일"


# ── 넣는 글 ─────────────────────────────────────────────────────────────────
def is_trading_day(rec: dict) -> bool:
    """장 마감 잠정 수급이 있으면 거래일(휴장일엔 없다)."""
    c = rec.get("close") or {}
    return bool(((c.get("flows_prelim") or {}).get("kospi") or {}))


def build_prompt(day: str, rec: dict) -> tuple[str, int]:
    """그날 일지 → (넣을 글, 제목 수). 같은 일지면 같은 글(정해진 순서·개수)."""
    m, c = rec.get("morning") or {}, rec.get("close") or {}
    seen: set[str] = set()

    def pick(items, n=None):
        out = []
        for x in sorted(items, key=lambda z: str(z.get("time") or ""), reverse=True):
            t = str(x.get("title") or "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append(f"- {str(x.get('time') or '')[5:]} {t}")
                if n is not None and len(out) >= n:
                    break
        return out
    heads = pick((m.get("headlines") or []) + (c.get("headlines") or []))
    close = pick(c.get("news") or [], N_CLOSE)
    morning = pick(m.get("news") or [], N_MORNING)
    dart = [f"- {x.get('corp_name', '')}: {x.get('report_nm', '')}" for x in (c.get("dart") or [])]
    cal = [f"- {e.get('date', '')} {e.get('event', '')}" for e in (m.get("calendar") or c.get("calendar") or [])
           if str(e.get("date", "")) >= day][:N_CALENDAR]
    win = (c.get("news_window") or [None, None])[1] or ""
    wd = WEEKDAY[datetime.fromisoformat(day).weekday()]
    parts = [f"날짜: {day}({wd}) — 한국 장 마감(15:30) 뒤, {str(win)[11:16] or '장 마감 무렵'} 까지 나온 글.", QUESTION,
             f"\n[공시 — 주요사항보고 {len(dart)}건]", *(dart or ["- 없음"]),
             f"\n[일정 — 오늘부터]", *(cal or ["- 없음"]),
             f"\n[대표 제목 {len(heads)}건]", *heads,
             f"\n[장중 뉴스 제목 — 최신 {len(close)}건(08:30~)]", *close,
             f"\n[아침 뉴스 제목 — 최신 {len(morning)}건(전날 15:30~08:30)]", *morning]
    return "\n".join(parts) + "\n", len(heads) + len(close) + len(morning)


# ── 묻기 ─────────────────────────────────────────────────────────────────────
def command() -> list[str]:
    return [CLAUDE_EXE, "-p", "--model", MODEL, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
            "--no-session-persistence", "--output-format", "json", "--json-schema", json.dumps(SCHEMA, ensure_ascii=False),
            "--system-prompt", SYSTEM]


def parse_answer(raw: str) -> dict:
    """headless claude JSON 결과 → 답. 형식이 어긋나거나 다른 모델이 답했으면 ValueError(대체하지 않는다)."""
    j = json.loads(raw)
    if j.get("is_error") or j.get("subtype") != "success":
        raise ValueError(f"claude 오류: {j.get('subtype')} {str(j.get('result'))[:200]}")
    if MODEL not in (j.get("modelUsage") or {}):
        raise ValueError(f"답한 모델이 {MODEL} 이 아니다: {list((j.get('modelUsage') or {}).keys())}")
    a = j.get("structured_output")
    if not isinstance(a, dict):
        a = json.loads(j.get("result") or "{}")
    d, r, why = a.get("direction"), a.get("risk"), a.get("reason")
    if not isinstance(d, int) or isinstance(d, bool) or not -2 <= d <= 2 or r not in ("높음", "보통", "낮음") \
            or not isinstance(why, str):
        raise ValueError(f"답 형식 오류: {a}")
    return {"direction": d, "risk": r, "reason": " ".join(why.split())[:300],
            "cost_usd": round(float(j.get("total_cost_usd") or 0), 4), "duration_ms": int(j.get("duration_ms") or 0)}


def child_env(base=None) -> dict:
    """자식 claude 의 환경 — 지금 환경에서 API 인증 변수만 뺀다(구독 로그인으로만 돈다, 11-26)."""
    env = dict(os.environ if base is None else base)
    for k in API_AUTH_ENV:
        env.pop(k, None)
    return env


def ask(prompt: str, run=subprocess.run) -> dict:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    p = run(command(), input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_S, cwd=RUN_DIR,
            env=child_env())
    if p.returncode != 0 and not (p.stdout or "").strip():
        raise ValueError(f"claude 종료코드 {p.returncode}: {(p.stderr or '')[-300:]}")
    return {**parse_answer(p.stdout), "_raw": p.stdout}        # 원문은 record 가 inputs/<날짜>.answer.json 으로(감사용)


# ── 기록 ─────────────────────────────────────────────────────────────────────
def load(path: Path = FILE) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def record(now: datetime, day: str | None = None, journal_dir: Path = MJ.JOURNAL_DIR, out: Path = FILE,
           inputs: Path = INPUTS, asker=ask) -> dict:
    """오늘(d) 판단 한 줄. {'skip': 이유} 또는 {'row': 줄}. 실패는 예외."""
    today = now.strftime("%Y-%m-%d")
    day = day or today
    if day != today:
        return {"skip": f"{day} 는 오늘({today})이 아니다 — 지난 날은 묻지 않는다(앞으로만)"}
    rows = load(out)
    if any(r["date"] == day for r in rows):
        return {"skip": f"{day} 는 이미 답이 있다 — 다시 묻지 않는다"}
    rec = MJ.load_day(day, journal_dir)
    if not rec.get("close"):
        return {"skip": f"{day} 시장 일지 close 가 없다"}
    if not is_trading_day(rec):
        return {"skip": f"{day} 휴장(잠정 수급 없음)"}
    prompt, n = build_prompt(day, rec)
    sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    inputs.mkdir(parents=True, exist_ok=True)
    AIO.write_text(inputs / f"{day}.txt", prompt)
    a = dict(asker(prompt))
    raw = a.pop("_raw", None)
    if raw:
        AIO.write_text(inputs / f"{day}.answer.json", raw)
    row = {"date": day, "asked_at": now.strftime("%Y-%m-%dT%H:%M:%S"), "model": MODEL, "n_titles": n,
           "input_sha256": sha, **a}
    rows = sorted(rows + [{k: row.get(k, "") for k in COLS}], key=lambda r: r["date"])
    AIO.write_csv(out, COLS, rows, keep_bak=True)
    return {"row": row}


# ── 가설 해당 날 (결과 없이 셀 수 있다) ───────────────────────────────────────
def l_days(rows: list[dict], side: int) -> list[str]:
    """side −1: direction ≤ −1 · +1: direction ≥ +1."""
    return [r["date"] for r in rows if r.get("direction") not in (None, "")
            and (int(r["direction"]) * side) >= 1]


# ── 판정 (JUDGE_DAYS 전엔 결과를 보지 않는다) ──────────────────────────────────
def forward(kospi: dict) -> dict[str, float]:
    """d → 다음 날 시가 → (1+H)일째 시가 수익(market_features.judge 와 같은 정의)."""
    kd = sorted(kospi)
    return {d: kospi[kd[k + 1 + H]]["open"] / kospi[kd[k + 1]]["open"] - 1
            for k, d in enumerate(kd) if k + 1 + H < len(kd)}


def _gap(flags: list[bool], x: list[float]) -> float | None:
    sel = [v for f, v in zip(flags, x) if f]
    return (statistics.fmean(sel) - statistics.fmean(x)) if sel else None


def block_p(flags: list[bool], x: list[float], side: int, block: int = BLOCK, draws: int = DRAWS,
            seed: int = SEED) -> float | None:
    """구간 섞기 검정 — 판단 열을 block 구간으로 잘라 순서만 draws 번 섞었을 때, 차이가 관측값만큼(L1 은 더 약하게,
    L2 는 더 강하게) 나오는 비율 (≥ 1/(draws+1)). 구간 안의 뭉침은 그대로 — 수익 열은 건드리지 않는다."""
    import random
    obs = _gap(flags, x)
    if obs is None or len(x) < 2 * block:
        return None
    blocks = [flags[i:i + block] for i in range(0, len(flags), block)]
    rng = random.Random(seed)
    hits = 0
    for _ in range(draws):
        rng.shuffle(blocks)
        g = _gap([f for b in blocks for f in b], x)
        if g is not None and g * side >= obs * side:
            hits += 1
    return (hits + 1) / (draws + 1)


def judge(rows: list[dict], kospi: dict) -> dict:
    fwd = forward(kospi)
    use = [r for r in rows if r["date"] in fwd]
    x = [fwd[r["date"]] for r in use]
    out = {}
    for name, side in (("L1", -1), ("L2", +1)):
        picked = set(l_days(use, side))
        flags = [r["date"] in picked for r in use]
        sel = [v for f, v in zip(flags, x) if f]
        res: dict = {"n": len(sel)}
        if sel and x:
            hit = sum((v * side) > 0 for v in sel) / len(sel)
            base = sum((v * side) > 0 for v in x) / len(x)
            res.update(gap_pct=round(_gap(flags, x) * 100, 3), hit=round(hit, 3), base_hit=round(base, 3),
                       p=block_p(flags, x, side))
            res["pass"] = (len(sel) >= MIN_EVENTS and res["gap_pct"] * side >= GAP_PCT
                           and (hit - base) * 100 >= HIT_GAIN_PP and res["p"] is not None and res["p"] <= P_MAX)
        else:
            res["pass"] = False
        out[name] = res
    return out


def _ranks(v: list[float]) -> list[float]:
    """평균 순위(동점은 같은 순위) — 스피어만 상관용."""
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def side_report(rows: list[dict], kospi: dict) -> dict:
    """보고만 — L1 vs N2 같은 기간, risk 높음 날 뒤 5일 최저, 방향 점수 순위 상관."""
    import market_features as MF
    fwd = forward(kospi)
    days = [r["date"] for r in rows if r["date"] in fwd]
    feats = [r for r in MF.load() if r["date"] >= (days[0] if days else "9999")]
    n2 = [d for d in MF.n2_days(feats) if d in days]
    l1 = [d for d in l_days(rows, -1) if d in fwd]
    mean = (lambda ds: round(statistics.fmean(fwd[d] for d in ds) * 100, 3) if ds else None)
    hi = [fwd[r["date"]] for r in rows if r.get("risk") == "높음" and r["date"] in fwd]
    pairs = [(int(r["direction"]), fwd[r["date"]]) for r in rows if r["date"] in fwd]
    rho = None
    if len(pairs) >= 3 and len({a for a, _ in pairs}) > 1:
        rho = round(statistics.correlation(_ranks([a for a, _ in pairs]), _ranks([b for _, b in pairs])), 3)
    return {"all_pct": mean(days), "L1_pct": mean(l1), "N2_pct": mean(n2), "L1_n": len(l1), "N2_n": len(n2),
            "risk_high_min_pct": round(min(hi) * 100, 2) if hi else None, "rank_corr": rho}


def report(rows: list[dict], allow_judge: bool) -> str:
    n = len(rows)
    counts = f"L1 {len(l_days(rows, -1))}일 · L2 {len(l_days(rows, +1))}일"
    if n < JUDGE_DAYS or not allow_judge:
        return f"[llm_news] 기록 {n}/{JUDGE_DAYS}거래일 — 판정 전(결과는 보지 않는다) · 해당 날 {counts}"
    import strategy_lab as L
    kospi = L.load_bars("^KS11", rows[0]["date"], "9999-12-31")
    res = judge(rows, kospi)
    return (f"[llm_news] 판정({n}거래일) " + " · ".join(f"{k} {'통과' if v['pass'] else '탈락'} {v}" for k, v in res.items())
            + f" · 보고만 {side_report(rows, kospi)}")


def _label(d: int) -> str:
    return {-2: "크게 약함", -1: "약함", 0: "보합·판단 어려움", 1: "강함", 2: "크게 강함"}[d]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="기록 수·해당 날 수만")
    ap.add_argument("--judge", action="store_true", help=f"기록이 {JUDGE_DAYS}거래일 이상일 때만 판정한다")
    args = ap.parse_args(argv)
    if args.status or args.judge:
        print(report(load(), args.judge))
        return 0
    import asyncio
    from ops_base import notify
    now = datetime.now()
    try:
        r = record(now)
    except Exception as e:                       # 기록 실패는 그날 빈 날 — 같은 날 안에 다시 돌리면 채워진다
        msg = (f"⚠️ [Claude 뉴스 판단] {now:%m-%d} 기록 실패 — {str(e)[:300]}. 오늘 안에 "
               f"`python scripts\\llm_news.py` 를 다시 돌리면 기록된다(다음 날엔 묻지 않는다 — 앞으로만)")
        print(msg)
        asyncio.run(notify(msg))
        return 1
    if "skip" in r:
        print(f"[llm_news] 건너뜀 — {r['skip']}")
        return 0
    row, n = r["row"], len(load())
    print(f"[llm_news] {row['date']} direction {row['direction']} · risk {row['risk']} · 제목 {row['n_titles']} · "
          f"${row['cost_usd']} · {row['reason']}")
    print(report(load(), False))
    asyncio.run(notify(f"🤖 [Claude 뉴스 판단] {row['date'][5:]} — 다음 5거래일 코스피 {row['direction']:+d}({_label(row['direction'])}) "
                       f"· 큰 하락 위험 {row['risk']} · {row['reason']} (기록 {n}/{JUDGE_DAYS} — 판정 전, 결과는 보지 않는다)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
