"""Claude 뉴스 판단 일지(llm_news) — 앞으로만 기록·깨끗한 조건·판정 잣대 (2026-11-25).

지난 날을 채우지 않는지, 같은 날 두 번 묻지 않는지, 다른 모델·이상한 답을 받아들이지 않는지, 판정이 선언대로인지
(진짜 신호는 통과, 무관한 판단은 탈락)를 확인한다. 실제 경계: record 가 쓴 파일을 load 가 읽는다.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import llm_news as N  # noqa: E402

DAY = "2026-11-26"
NOW = datetime(2026, 11, 26, 15, 56)


def _journal(tmp_path: Path, day: str = DAY, trading: bool = True, n_close: int = 350, n_morning: int = 150) -> Path:
    jd = tmp_path / "journal"
    jd.mkdir(parents=True, exist_ok=True)
    close_news = [{"time": f"{day} 15:{i % 60:02d}", "title": f"장중 기사 {i}", "link": f"c{i}"} for i in range(n_close)]
    close_news.append({"time": f"{day} 15:59", "title": "장중 기사 3", "link": "dup"})            # 같은 제목 — 한 번만
    morning_news = [{"time": f"{day} 08:{i % 60:02d}", "title": f"아침 기사 {i}", "link": f"m{i}"} for i in range(n_morning)]
    rec = {"date": day,
           "morning": {"news": morning_news, "headlines": [{"time": f"{day} 08:29", "title": "대표 아침"}],
                       "calendar": [{"date": "2026-12-09", "event": "FOMC"}, {"date": "2026-11-01", "event": "지난 일"}]},
           "close": {"news": close_news, "headlines": [{"time": f"{day} 15:50", "title": "대표 장중"}],
                     "news_window": [f"{day} 08:30:00", f"{day} 15:53:08"],
                     "dart": [{"corp_name": "가나", "report_nm": "주요사항보고서(유상증자결정)"}],
                     "flows_prelim": {"kospi": {"외국인": -100.0}} if trading else {}}}
    (jd / f"{day}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return jd


def _answer(direction=-1, risk="높음", model=N.MODEL, **kw) -> str:
    """headless claude --output-format json 결과 모양(11-25 시험 호출에서 본 그대로)."""
    j = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 6023, "total_cost_usd": 0.0204,
         "modelUsage": {"claude-haiku-5-5": {}, model: {}},
         "result": json.dumps({"direction": direction, "risk": risk, "reason": "이유"}, ensure_ascii=False),
         "structured_output": {"direction": direction, "risk": risk, "reason": " 반도체\n급락 뒤 "}}
    j.update(kw)
    return json.dumps(j, ensure_ascii=False)


# ── 넣는 글 ─────────────────────────────────────────────────────────────────
def test_prompt_is_deterministic_capped_and_deduped(tmp_path):
    jd = _journal(tmp_path)
    import market_journal as MJ
    rec = MJ.load_day(DAY, jd)
    a, n = N.build_prompt(DAY, rec)
    assert (a, n) == N.build_prompt(DAY, rec)                    # 같은 일지 → 같은 글
    assert n == 2 + N.N_CLOSE + N.N_MORNING                      # 대표 2 + 장중 300 + 아침 100
    assert a.count("장중 기사 3\n") == 1 and "대표 장중" in a and "가나: 주요사항보고서(유상증자결정)" in a
    assert "FOMC" in a and "지난 일" not in a and "2026-11-26(목)" in a and "15:53 까지" in a
    assert N.is_trading_day(rec) and not N.is_trading_day(MJ.load_day(DAY, _journal(tmp_path / "h", trading=False)))


# ── 묻기: 깨끗한 조건 · 답 검사 ─────────────────────────────────────────────
def test_command_runs_clean_outside_project(monkeypatch):
    """★ 도구·MCP·설정(훅·플러그인)·세션 저장 없이, 고정 모델로, 프로젝트 밖 폴더에서 — 지침·메모리가 끼지 않는다."""
    seen = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    def run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout=_answer(), stderr="")
    a = N.ask("글", run=run)
    cmd = seen["cmd"]
    for flag, val in (("--tools", ""), ("--setting-sources", ""), ("--model", N.MODEL), ("--output-format", "json")):
        assert cmd[cmd.index(flag) + 1] == val
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd and "--json-schema" in cmd
    assert seen["input"] == "글" and _ROOT not in Path(seen["cwd"]).resolve().parents and seen["timeout"] == N.TIMEOUT_S
    assert "ANTHROPIC_API_KEY" not in seen["env"] and "PATH" in {k.upper() for k in seen["env"]}   # 구독 로그인으로만
    raw = a.pop("_raw")
    assert a == {"direction": -1, "risk": "높음", "reason": "반도체 급락 뒤", "cost_usd": 0.0204, "duration_ms": 6023}
    assert json.loads(raw)["modelUsage"]                                  # 원문이 그대로 따라온다(감사용)


# 진짜 자식 프로세스 — 환경에 API 인증 변수가 보이면 claude 처럼 과금 오류("Credit balance is too low")로 답한다
_FAKE_CLAUDE = (
    "import os, json, sys; sys.stdin.read(); "
    f"leak = [k for k in {N.API_AUTH_ENV!r} if k in os.environ]; "
    "print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': bool(leak), "
    "'result': ('Credit balance is too low ' + ','.join(leak)) if leak else '', "
    f"'modelUsage': {{{N.MODEL!r}: {{}}}}, 'total_cost_usd': 0.17, 'duration_ms': 1, "
    "'structured_output': {'direction': 0, 'risk': '보통', 'reason': 'ok'}}))"
)


def test_ask_keeps_api_keys_away_from_real_child_process(tmp_path, monkeypatch):
    """★ 11-26 실패의 실제 경계: .env 키가 부모 환경에 있어도 자식 claude 에겐 안 보인다(구독 로그인으로만 — 과금 없음).
    일부러 깨뜨리기: 환경을 그대로 넘기면(옛 길) 같은 자식이 과금 오류로 답하고 ask 는 실패한다."""
    for k in N.API_AUTH_ENV:
        monkeypatch.setenv(k, "x")
    monkeypatch.setattr(N, "RUN_DIR", tmp_path / "cwd")
    monkeypatch.setattr(N, "command", lambda: [sys.executable, "-c", _FAKE_CLAUDE])
    a = N.ask("글")                                                                   # 새 길: 키가 안 넘어감
    assert (a["direction"], a["risk"], a["reason"]) == (0, "보통", "ok")
    monkeypatch.setattr(N, "child_env", lambda base=None: dict(os.environ))          # 옛 길: 환경 그대로
    with pytest.raises(ValueError, match="Credit balance is too low ANTHROPIC_API_KEY"):
        N.ask("글")


def test_child_env_keeps_everything_else():
    base = {"PATH": "p", "USERPROFILE": "u", "TELEGRAM_BOT_TOKEN": "t", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": "b"}
    assert N.child_env(base) == {"PATH": "p", "USERPROFILE": "u", "TELEGRAM_BOT_TOKEN": "t"}
    assert base["ANTHROPIC_API_KEY"] == "k"                                           # 원본은 건드리지 않는다


def test_record_keeps_raw_answer_beside_input(tmp_path):
    jd, out, inp = _journal(tmp_path), tmp_path / "daily.csv", tmp_path / "inputs"
    run = (lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=_answer(), stderr=""))
    N.record(NOW, journal_dir=jd, out=out, inputs=inp, asker=lambda p: N.ask(p, run=run))
    assert N.MODEL in json.loads((inp / f"{DAY}.answer.json").read_text(encoding="utf-8"))["modelUsage"]
    assert "_raw" not in N.load(out)[0]


@pytest.mark.parametrize("raw, why", [
    (_answer(model="claude-sonnet-5-5"), "모델"),                               # 다른 모델이 답함 — 대체하지 않는다
    (_answer(is_error=True, subtype="error_max_turns"), "오류"),
    (_answer(direction=3), "형식"),
    (_answer(risk="매우 높음"), "형식"),
])
def test_parse_answer_rejects_other_model_and_bad_answers(raw, why):
    """★ 일부러 깨뜨린다 — 이상한 답은 기록하지 않고 실패로(그날은 빈 날)."""
    with pytest.raises(ValueError, match=why):
        N.parse_answer(raw)


# ── 기록 (writer → reader) ─────────────────────────────────────────────────
def test_record_once_per_day_forward_only(tmp_path):
    """★ 오늘만 · 하루 한 번 · 거래일만. 쓴 파일을 load 가 그대로 읽는다."""
    jd, out, inp = _journal(tmp_path), tmp_path / "daily.csv", tmp_path / "inputs"
    calls = []

    def asker(prompt):
        calls.append(prompt)
        return N.parse_answer(_answer(direction=+1, risk="낮음"))
    r = N.record(NOW, journal_dir=jd, out=out, inputs=inp, asker=asker)
    row = N.load(out)[0]
    assert r["row"]["direction"] == 1 and row["date"] == DAY and row["direction"] == "1" and row["risk"] == "낮음"
    assert row["model"] == N.MODEL and row["asked_at"] == "2026-11-26T15:56:00"
    import hashlib
    assert hashlib.sha256((inp / f"{DAY}.txt").read_text(encoding="utf-8").encode("utf-8")).hexdigest() == row["input_sha256"]
    assert "이미 답" in N.record(NOW, journal_dir=jd, out=out, inputs=inp, asker=asker)["skip"] and len(calls) == 1
    assert "지난 날" in N.record(NOW, day="2026-11-25", journal_dir=jd, out=out, inputs=inp, asker=asker)["skip"]
    nxt = NOW + timedelta(days=1)
    assert "close 가 없다" in N.record(nxt, journal_dir=jd, out=out, inputs=inp, asker=asker)["skip"]
    hd = _journal(tmp_path / "hol", day="2026-11-27", trading=False)
    assert "휴장" in N.record(nxt, journal_dir=hd, out=out, inputs=inp, asker=asker)["skip"] and len(calls) == 1


def test_record_failure_leaves_no_row(tmp_path):
    jd, out = _journal(tmp_path), tmp_path / "daily.csv"

    def boom(prompt):
        raise ValueError("답한 모델이 다르다")
    with pytest.raises(ValueError):
        N.record(NOW, journal_dir=jd, out=out, inputs=tmp_path / "in", asker=boom)
    assert N.load(out) == []
    N.record(NOW, journal_dir=jd, out=out, inputs=tmp_path / "in",
             asker=lambda p: N.parse_answer(_answer()))                         # 같은 날 다시 — 채워진다
    assert len(N.load(out)) == 1


# ── 판정 잣대 ────────────────────────────────────────────────────────────────
def _market(n_days=140, signal=None, seed=1):
    """평일 n_days 의 가짜 코스피 — signal(날짜 집합)의 날 k 뒤 k+3 에 2% 빠졌다가 k+7 에 되돌아온다
    (그날의 뒤 5일 = k+1 시가 → k+6 시가 에만 하락이 들어간다)."""
    rng = random.Random(seed)
    days, d = [], date(2026, 11, 26)
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    mult = [1.0] * (n_days + 10)
    for k, dd in enumerate(days):
        if signal and dd in signal:
            mult[k + 3] *= 0.98
            mult[k + 7] /= 0.98
    px, bars = 1000.0, {}
    for k, dd in enumerate(days):
        px *= (1 + rng.gauss(0.0003, 0.004)) * mult[k]
        bars[dd] = {"open": px, "close": px}
    return days, bars


def _rows(days, neg):
    return [{"date": d, "direction": str(-1 if d in neg else 0), "risk": "보통"} for d in days[:N.JUDGE_DAYS]]


def test_judge_passes_real_signal_and_fails_unrelated_calls():
    """★ 판단 뒤에 실제로 빠지면 L1 통과(p ≤ 0.01), 같은 수의 판단을 시장과 무관하게 찍으면 탈락."""
    days0, _ = _market()
    neg = set(days0[3:N.JUDGE_DAYS - 8:7])                       # 16일 — 7일 간격
    days, kospi = _market(signal=neg)
    res = N.judge(_rows(days, neg), kospi)
    assert res["L1"]["n"] >= N.MIN_EVENTS and res["L1"]["pass"], res
    assert res["L1"]["p"] <= N.P_MAX and not res["L2"]["pass"]
    other = set(days0[5:N.JUDGE_DAYS - 8:7])                     # 시장과 무관한 날짜에 같은 수
    _, kospi2 = _market(signal=None, seed=7)
    res2 = N.judge(_rows(days, other), kospi2)
    assert not res2["L1"]["pass"]


def test_block_p_keeps_clustered_calls_honest():
    """뭉친 판단(연속 10일)이 우연히 약한 구간에 겹친 정도로는 p 가 작아지지 않는다 — 날짜별 섞기보다 엄격."""
    days, kospi = _market(seed=3)
    fwd = N.forward(kospi)
    use = [d for d in days if d in fwd][:110]
    x = [fwd[d] for d in use]
    worst = min(range(0, 100), key=lambda i: sum(x[i:i + 10]))
    flags = [worst <= i < worst + 10 for i in range(len(use))]  # 가장 약한 10일 구간에 몰린 '판단'
    assert N.block_p(flags, x, -1) > N.P_MAX


def test_report_does_not_look_before_judge_day(tmp_path):
    rows = [{"date": f"2026-12-{i:02d}", "direction": "-1"} for i in range(1, 11)]
    txt = N.report(rows, allow_judge=True)
    assert "판정 전" in txt and "L1 10일" in txt and "gap" not in txt


def test_trials_ledger_counts_the_two_hypotheses():
    import lab_trials as T
    assert T.total_through("scripts/llm_news.py") == T.total_through("scripts/lab_gen11.py") + 2
