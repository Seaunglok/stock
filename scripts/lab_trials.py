"""시험 횟수 장부 — 많이 잴수록 통과선을 올린다 (2026-11-18, 운용자 "오픈되지 않은 좋은 조건식… 더 발굴하는거는 어때?" → "진행해줘").

왜
--
  후보를 많이 재면 우연히 통과하는 것도 늘어난다 — 유의수준 5% 면 20개 중 1개는 운으로 통과한다. 사전 선언·두 구간·앞으로의
  기록이 이것을 막아 왔지만 **몇 개를 쟀는지 세는 장치가 없었다**. 금융 학계 권고: Harvey·Liu·Zhu(2016, RFS) 새 요인은 t ≥ 3.0,
  Bailey·López de Prado(2014) 보정 샤프 비율(시험 횟수를 반영).

무엇
----
  · TRIALS = 사전 선언으로 잰 후보 묶음(선언 무렵 날짜 · 연구 · 변형 수 · 근거 문서).
  · hurdle_t(n) = max(T_FLOOR 3.0, 본페로니 양측 α/n 의 z) — n 이 늘수록 천천히(로그) 오른다. n=20 → 3.02 · 100 → 3.48 · 500 → 3.89.
  · 새 판정대는 **측정 전에** 여기에 행을 더해 선언과 함께 커밋하고, 그 행까지 합친 n 으로 통과선을 쓴다.

세는 법(실제보다 적게 센다 — 하한)
  · 이름 붙은 후보(변형) 하나 = 1. 격자 점은 강건성 확인(격자 중앙값 조건)이라 따로 세지 않는다.
  · 10-21 전 대형주 추세추종 시기(개별 종목 · 08-27 결함으로 무효가 된 측정 포함)는 대상이 달라 넣지 않았다.
  · '앞으로만 기록'(리그 멤버·지표 일지 가설)도 결국 판정하므로 센다. 사전 선언 아닌 탐색도 1 로 센다(숫자를 봤다).
"""
from __future__ import annotations

from statistics import NormalDist

ALPHA = 0.05
T_FLOOR = 3.0

# (선언 무렵, 연구, 변형 수, 근거)
TRIALS: list[tuple[str, str, int, str]] = [
    ("2026-10-21", "연구소 1차 A 지수+추세필터 · B 레버리지+추세필터 · C 듀얼모멘텀", 3, "docs/2026-10-22-lab-criteria-declaration.md"),
    ("2026-10-21", "연구소 2차 D 위험관리 · E 버핏식 · F 버핏식+위험관리", 3, "docs/2026-10-22-lab-criteria-declaration.md"),
    ("2026-10-21", "연구소 3차 G1·G2 혼합", 2, "docs/2026-10-22-lab-criteria-declaration.md"),
    ("2026-10-22", "연구소 4차 H1·H2 이탈·재진입", 2, "docs/2026-10-22-lab-criteria-declaration.md"),
    ("2026-10-22", "연구소 5차 I1a·I1b·I2a·I2b·I3", 5, "docs/2026-10-22-lab-criteria-declaration.md"),
    ("2026-10-22", "I4a·I4b·I4c 레버리지 보강·한미 교체", 3, "docs/2026-10-22-lab-criteria-declaration.md"),
    ("2026-10-22", "I3 계보 1~3세대 R1~R7 · 장중 손절 S1", 8, "docs/2026-10-22-i3-league.md"),
    ("2026-10-22", "기초지수 KRX300", 1, "docs/2026-10-22-i3-league.md"),
    ("2026-10-22", "4세대 G4a·G4b", 2, "docs/2026-10-22-i3-league.md"),
    ("2026-10-22", "5세대 D5a·D5b", 2, "docs/2026-10-22-i3-league.md"),
    ("2026-10-22", "고전 9종(lab_classics)", 9, "scripts/lab_classics.py"),
    ("2026-10-22", "AQR 저베타·퀄리티(lab_factors)", 2, "scripts/lab_factors.py"),
    ("2026-10-22", "체결 시각 10시·종가(lab_exec_timing)", 2, "scripts/lab_exec_timing.py"),
    ("2026-10-23", "6세대 T6a·T6b·T6c", 3, "docs/2026-10-22-i3-league.md"),
    ("2026-10-23", "7세대 V7a·V7b", 2, "docs/2026-10-22-i3-league.md"),
    ("2026-10-26", "8세대 V8a·V8b", 2, "docs/2026-10-22-i3-league.md"),
    ("2026-10-27", "탐색: 밤사이 미국 → 다음 날(사전 선언 아님)", 1, "docs/i3-improvement-backlog.md"),
    ("2026-10-28", "공격형 1세대 A 양방향", 6, "docs/2026-10-28-aggressive-track.md"),
    ("2026-10-28", "하락 예측 판정대 C(V1·V2·U1·F1·K1·K2·M1)", 7, "docs/2026-10-28-aggressive-track.md"),
    ("2026-10-28", "공격형 리그 ORB-B1·B2 · FEAR-V1·V2·K1·K2(앞으로만)", 6, "docs/2026-10-28-aggressive-track.md"),
    ("2026-10-29", "공격형 2세대 G1·G2", 2, "docs/2026-10-28-aggressive-track.md"),
    ("2026-10-29", "공격형 3세대 HH1·HH2", 2, "docs/2026-10-28-aggressive-track.md"),
    ("2026-11-10", "공격형 리그 ORB-B3 · FEAR-P1·P2(앞으로만)", 3, "docs/2026-10-28-aggressive-track.md"),
    ("2026-11-10", "9세대 F9a·F9b", 2, "docs/2026-10-22-i3-league.md"),
    ("2026-11-16", "수급 판정대 S1~S5(lab_flows)", 5, "scripts/lab_flows.py"),
    ("2026-11-16", "뉴스·경제 지표 N1~N3(앞으로만, 판정 2027-04-30)", 3, "scripts/market_features.py"),
    ("2026-11-18", "구조적 수급 날짜 C1~C5(lab_calendar)", 5, "scripts/lab_calendar.py"),
    ("2026-11-18", "한국 팩터 기울기 F1~F5(lab_jkp, 사는 쪽만)", 5, "scripts/lab_jkp.py"),
]


def total(upto: str | None = None) -> int:
    """upto(포함)까지 선언된 변형 수 합 — None 이면 전부."""
    return sum(n for d, _, n, _ in TRIALS if upto is None or d <= upto)


def total_through(source: str) -> int:
    """그 근거(source) 행까지(포함)의 누적 — 판정대의 통과선은 이것으로 쓴다(첫 번째로 일치하는 행).

    같은 날 묶음을 둘 이상 선언해도 앞 묶음의 통과선이 바뀌지 않는다(11-18: lab_calendar 93 → 그대로, lab_jkp 98)."""
    s = 0
    for _, _, n, src in TRIALS:
        s += n
        if src == source:
            return s
    raise KeyError(source)


def hurdle_t(n: int, alpha: float = ALPHA, floor: float = T_FLOOR) -> float:
    """시험 n 개를 했을 때 하나가 우연히 넘지 않을 t — 본페로니 양측(α/n), 하한 floor."""
    if n < 1:
        raise ValueError("n ≥ 1")
    return max(floor, NormalDist().inv_cdf(1 - alpha / (2 * n)))
