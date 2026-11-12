"""키움 연결 점검(kiwoom_net_check) — 막히면 바로 알리고, 같은 걸 되풀이하지 않고, 복구를 알린다."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kiwoom_net_check as K  # noqa: E402

# 11-12 21:38 실측 원응답(조회 단계) — 토큰은 살아 있었는데 일봉 조회가 이렇게 막혔다
REAL_8050 = {"return_msg": "인증에 실패했습니다[8050:IP가 등록되지 않았습니다. 키움 REST API 홈페이지 > API 사용신청 "
                           "화면에서 IP를 등록해주세요.]", "return_code": 3}
TOKEN_8050 = "KiwoomAPIError: Token acquisition failed (rc=3): 인증에 실패했습니다[8050:IP가 등록되지 않았습니다.]"
T0 = datetime(2026, 11, 12, 15, 21)


def test_classify_catches_8050_at_both_stages():
    assert K.classify(REAL_8050, None)[0] == "ip"                       # ★ 조회 단계(11-12 실측)
    assert K.classify(None, TOKEN_8050)[0] == "ip"                      # 토큰 단계
    assert K.classify({"return_code": 0, "return_msg": "정상적으로 처리되었습니다"}, None)[0] == "ok"
    assert K.classify({"return_code": 1, "return_msg": "서버 점검"}, None) == ("fail", "rc=1 서버 점검")
    assert K.classify(None, "ConnectError: timeout")[0] == "fail" and K.classify(None, None)[0] == "fail"


def test_blocked_alert_carries_ip_and_is_not_repeated_within_cooldown():
    msgs, st = K.decide({"ip": "1.1.1.1", "status": "ok"}, "ip", REAL_8050["return_msg"], "61.98.4.87", T0)
    assert len(msgs) == 1 and msgs[0][1] is True and "61.98.4.87" in msgs[0][0] and "API 사용신청" in msgs[0][0]
    again, st2 = K.decide(st, "ip", "x", "61.98.4.87", T0 + timedelta(minutes=10))
    assert again == []                                                     # 네트워크 이벤트 몇 번이 와도 한 번
    later, st3 = K.decide(st2, "ip", "x", "61.98.4.87", T0 + timedelta(minutes=K.COOLDOWN_MIN + 1))
    assert len(later) == 1                                                 # 오래 막혀 있으면 다시 깨운다
    other_ip, _ = K.decide(st3, "ip", "x", "10.0.0.9", T0 + timedelta(minutes=K.COOLDOWN_MIN + 2))
    assert len(other_ip) == 1 and "10.0.0.9" in other_ip[0][0]            # IP 가 또 바뀌면 바로


def test_recovery_and_ip_change_and_quiet():
    _, blocked = K.decide({"ip": "1.1.1.1", "status": "ok"}, "ip", "8050", "61.98.4.87", T0)
    rec, st = K.decide(blocked, "ok", "정상", "61.98.4.87", datetime(2026, 11, 12, 21, 43))
    assert len(rec) == 1 and rec[0][1] is False and "복구" in rec[0][0] and "i3_decide.cmd" in rec[0][0]
    rec_am, _ = K.decide(blocked, "ok", "정상", "61.98.4.87", datetime(2026, 11, 13, 10, 0))
    assert "i3_decide.cmd" not in rec_am[0][0]                             # 판단 전 복구면 재실행 안내 없음
    assert "alerted_key" not in st
    quiet, _ = K.decide(st, "ok", "정상", "61.98.4.87", T0)
    assert quiet == []
    moved, _ = K.decide(st, "ok", "정상", "5.5.5.5", T0)
    assert len(moved) == 1 and "61.98.4.87 → 5.5.5.5" in moved[0][0] and moved[0][1] is False
    first, _ = K.decide({}, "ok", "정상", "61.98.4.87", T0)
    assert len(first) == 1 and "감시 시작" in first[0][0]


def _run_check(tmp_path, monkeypatch, results):
    """probe 결과를 차례로 돌려주는 가짜 바깥 — 실제 check() 흐름(재시도·판정·상태 저장)을 지난다."""
    seq = iter(results)
    slept = []

    async def fake_ip():
        return "61.98.4.87"

    async def fake_probe(now):
        return next(seq)

    async def fake_sleep(s):
        slept.append(s)
    monkeypatch.setattr(K, "public_ip", fake_ip)
    monkeypatch.setattr(K, "probe_kiwoom", fake_probe)
    st = tmp_path / "state.json"
    K.save_state({"ip": "61.98.4.87", "status": "ok"}, st)
    r = asyncio.run(K.check(delay=20, dry_run=True, state_file=st, sleep=fake_sleep, clock=lambda: T0))
    return r, slept


def test_check_retries_transient_failures_then_succeeds(tmp_path, monkeypatch):
    r, slept = _run_check(tmp_path, monkeypatch, [(None, "ConnectError"), ({"return_code": 0}, None)])
    assert r["status"] == "ok" and r["msgs"] == [] and slept == [20, K.RETRY_GAP_S]


def test_check_stops_retrying_on_8050_and_alerts(tmp_path, monkeypatch):
    r, slept = _run_check(tmp_path, monkeypatch, [(REAL_8050, None)])
    assert r["status"] == "ip" and slept == [20] and r["msgs"][0][1] is True


def test_check_gives_up_after_attempts(tmp_path, monkeypatch):
    r, slept = _run_check(tmp_path, monkeypatch, [(None, "ConnectError")] * K.ATTEMPTS)
    assert r["status"] == "fail" and len(slept) == 1 + (K.ATTEMPTS - 1) and r["msgs"][0][1] is True


def test_task_files_wire_the_declared_triggers():
    cmd = (_ROOT / "scripts" / "kiwoom_net_check.cmd").read_text(encoding="utf-8")
    ps1 = (_ROOT / "scripts" / "register_kiwoom_net_check.ps1").read_text(encoding="utf-8")
    assert "scripts\\kiwoom_net_check.py --delay 20" in cmd and "logs\\kiwoom_net\\check.log" in cmd
    assert "Microsoft-Windows-NetworkProfile/Operational" in ps1 and "EventID=10000" in ps1
    assert "-AtLogOn" in ps1 and "-At 15:30" in ps1 and "IgnoreNew" in ps1 and "AllowStartIfOnBatteries" in ps1
