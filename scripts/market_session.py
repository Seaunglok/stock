"""장 시간 — 개장·마감이 평소(09:00~15:30)와 다른 날을 일정 파일에서 읽는다 (백로그 ⑲, 2026-11-23).

왜
--
  판단·매매·주문 시간 훅이 시각을 상수로 갖고 있어(판단 15:35 뒤 · 매도 08:50 · 매수 09:05:30 · 매매 시간대 08:30~09:20),
  장 시간이 바뀌는 날엔 손으로 예약작업을 옮겼다(2026-11-19 수능 10:00~16:30 → `I3Decide` 그날만 16:45). 해마다 수능과
  **새해 첫 거래일(10:00 개장, 마감 그대로)** 이 온다 — 첫 번째가 2027-01-04.

어떻게
------
  평소 시각을 '개장·마감으로부터의 거리'로 적고 그날의 개장·마감에 더한다. **평소 날엔 옛 상수와 똑같다**(시험이 잠근다):
    판단        마감 + 5분       (15:35)        매도(동시호가)  개장 − 10분     (08:50 — 예약작업 시각)
    매매 시간대  개장 − 30분 ~ +20분 (08:30~09:20)  매수(지정가)    개장 + 5분 30초 (09:05:30, ETF LP 호가 의무 뒤)
    체결 대조    개장 + 30초     (09:00:30)     계좌 조회 대기  개장 + 15분     (09:15)
  동시호가 시각은 거래소 공지 기사에 없다(11-23 확인) — 개장이 한 시간 밀리면 동시호가도 같이 밀린다고 보고, 매도를
  '개장 10분 전'으로 둔다(09:00~10:00·09:30~10:00 어느 쪽이어도 안에 든다).

일정 파일 `scripts/market_calendar.json`(시장 일지가 읽는 그 파일): 항목에 "open"·"close"(HH:MM)가 있으면 그날의 장 시간.
  "confirmed": false = 관행으로 미리 적은 것(거래소 공지 전) — 그대로 따르되 판단 알림에 '공지 확인 필요'로 보인다.
  파일이 깨졌으면 예외 — 부르는 쪽이 평소 시간으로 보고 **critical 로 알린다**(조용히 믿지 않는다).
표준 라이브러리만 쓴다 — 주문 시간 훅(`claude_guard`)도 이 모듈을 읽는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

CALENDAR_FILE = Path(__file__).resolve().with_name("market_calendar.json")
NORMAL_OPEN = time(9, 0)
NORMAL_CLOSE = time(15, 30)

DECIDE_AFTER_CLOSE = timedelta(minutes=5)
TRADE_FROM_OPEN = timedelta(minutes=-30)
TRADE_UNTIL_OPEN = timedelta(minutes=20)
SELL_FROM_OPEN = timedelta(minutes=-10)
BUY_FROM_OPEN = timedelta(minutes=5, seconds=30)
SETTLE_FROM_OPEN = timedelta(seconds=30)
BROKER_WAIT_FROM_OPEN = timedelta(minutes=15)
# 주문 시간 훅 — 평소 08:30~09:20 · 15:50~16:00. 장 시간이 바뀐 날은 평소 창과 바뀐 창을 합친다(배치가 기다리는 동안도 막는다).
GUARD_NORMAL = ((time(8, 30), time(9, 20)), (time(15, 50), time(16, 0)))
GUARD_AFTER_DECIDE = timedelta(minutes=10)
SANE_RANGE = (time(7, 0), time(18, 0))           # 일정 파일의 시각이 이 밖이면 오타로 본다


def _plus(t: time, d: timedelta) -> time:
    return (datetime.combine(date(2000, 1, 1), t) + d).time()


@dataclass(frozen=True)
class Session:
    day: str
    open: time = NORMAL_OPEN
    close: time = NORMAL_CLOSE
    note: str = ""
    confirmed: bool = True

    @property
    def shifted(self) -> bool:
        return (self.open, self.close) != (NORMAL_OPEN, NORMAL_CLOSE)

    @property
    def decide_after(self) -> time:
        return _plus(self.close, DECIDE_AFTER_CLOSE)

    @property
    def trade_window(self) -> tuple[time, time]:
        return _plus(self.open, TRADE_FROM_OPEN), _plus(self.open, TRADE_UNTIL_OPEN)

    @property
    def sell_at(self) -> time:
        return _plus(self.open, SELL_FROM_OPEN)

    @property
    def buy_after(self) -> time:
        return _plus(self.open, BUY_FROM_OPEN)

    @property
    def settle_at(self) -> time:
        return _plus(self.open, SETTLE_FROM_OPEN)

    @property
    def broker_wait_until(self) -> time:
        return _plus(self.open, BROKER_WAIT_FROM_OPEN)

    def guard_windows(self) -> tuple[tuple[time, time], tuple[time, time]]:
        (m0, m1), (a0, a1) = GUARD_NORMAL
        t0, t1 = self.trade_window
        return (min(m0, t0), max(m1, t1)), (a0, max(a1, _plus(self.decide_after, GUARD_AFTER_DECIDE)))

    def label(self) -> str:
        return f"{self.open:%H:%M}~{self.close:%H:%M}"


def _hm(s: str) -> time:
    t = datetime.strptime(str(s).strip(), "%H:%M").time()
    if not SANE_RANGE[0] <= t <= SANE_RANGE[1]:
        raise ValueError(f"장 시각 {s} 이 {SANE_RANGE[0]:%H:%M}~{SANE_RANGE[1]:%H:%M} 밖")
    return t


def load_sessions(path: Path = CALENDAR_FILE) -> dict[str, Session]:
    """일정 파일의 장 시간 항목 → {날짜: Session}. 파일이 없거나 깨졌거나 시각이 이상하면 예외(빈 결과로 믿지 않는다)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{Path(path).name} 형식 오류(목록 아님)")
    out: dict[str, Session] = {}
    for e in raw:
        if not isinstance(e, dict) or not ("open" in e or "close" in e):
            continue
        day = date.fromisoformat(str(e["date"])).isoformat()
        s = Session(day, _hm(e.get("open", f"{NORMAL_OPEN:%H:%M}")), _hm(e.get("close", f"{NORMAL_CLOSE:%H:%M}")),
                    str(e.get("event", "")), bool(e.get("confirmed", True)))
        if s.open >= s.close:
            raise ValueError(f"{day} 개장 {s.open:%H:%M} ≥ 마감 {s.close:%H:%M}")
        out[day] = s
    return out


def session_for(day: str, path: Path = CALENDAR_FILE) -> Session:
    return load_sessions(path).get(day, Session(day))


def upcoming(today: str, horizon_days: int = 7, path: Path = CALENDAR_FILE) -> list[Session]:
    """오늘 뒤 horizon 일 안의 장 시간 변경일(판단 알림에 미리 보인다)."""
    end = (date.fromisoformat(today) + timedelta(days=horizon_days)).isoformat()
    return [s for d, s in sorted(load_sessions(path).items()) if today < d <= end and s.shifted]


def wait_seconds(now: datetime, target: time, max_wait: timedelta) -> float | None:
    """now 에서 같은 날 target 까지 기다릴 초 — 이미 지났으면 0, max_wait 보다 길면 None(이상한 일정 — 기다리지 않는다)."""
    secs = (datetime.combine(now.date(), target) - now).total_seconds()
    if secs <= 0:
        return 0.0
    return None if secs > max_wait.total_seconds() else secs


def weekdays_between(a: str, b: str) -> int:
    """a 다음 날부터 b 까지(포함) 월~금 날 수 — 판단(a)이 매매일(b)까지 묵은 정도. 주말은 세지 않는다(휴장 평일은 센다)."""
    d, end, n = date.fromisoformat(a) + timedelta(days=1), date.fromisoformat(b), 0
    while d <= end:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n
