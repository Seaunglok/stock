"""한국 팩터 기울기 판정대 — 해외 팩터 연구의 한국판, 사는 쪽만(롱온리) (2026-11-18, 사전 선언).

운용자(11-18): "오픈되지 않은 좋은 조건식이나 매매 알고리즘이 많이 있을 거 같어. 이런거를 더 발굴하는거는 어때?" → "진행해줘" →
1묶음(달력, 통과 없음) 뒤 "다음 진행 해줘" → 아이디어 장부 8번(해외 팩터 연구의 한국판)을 2묶음으로.

왜 이 묶음인가
-------------
  · 학계가 미국에서 찾은 팩터(저변동·모멘텀·가치·퀄리티·배당)가 **한국에서도, 지금도** 있는가 — 공개 자료(Jensen·Kelly·Pedersen
    2023 'Is There a Replication Crisis in Finance?', JF)가 나라별로 같은 방법으로 다시 만들어 공개했다. 우리가 고른 숫자가 아니다.
  · 왜 돈이 되나: 저변동 = 레버리지를 못 쓰는 투자자가 고베타를 비싸게 산다(Frazzini·Pedersen 2014) · 모멘텀 = 정보에 늦게 반응
    · 가치 = 위험 보상·외면받는 종목의 과소평가 · 퀄리티 = 좋은 회사의 미래 이익을 시장이 덜 쳐준다(Asness 외 2019) · 배당 = 세금·
    선호. 손해 보는 쪽이 있는 구조라 공개 뒤에도 일부 남을 수 있다(McLean·Pontiff 2016 은 평균 절반 넘게 줄었다고 — 그것까지 잰다).
  · 실행: **사고 동시에 공매도하는 롱숏은 우리가 못 한다** → 논문이 '좋다'고 하는 3분위만 사는 쪽(롱온리)이 시장보다 나은지를 잰다.
    한국에 이 팩터를 따르는 ETF 가 있다(아래 후보 표 — 11-18 FDR 목록, 배당 외에는 50~370억원으로 작다).
  · 10-22 lab_factors(저베타·퀄리티)는 '현재 대형주 100' 으로 과거를 재서 생존편향이 있었다. JKP 는 상장폐지 수익까지 넣은
    Compustat Global 전체(설명서 RET 정의) — 같은 질문을 편향 없이 다시 묻는 것이기도 하다.

선언 (측정 전 — 결과를 보고 고치면 무효, 같은 숫자로 다시 재지 않는다)
-------------------------------------------------------------------
  자료     JKP Global Factor Data(jkpfactors.com, 자료 CC BY-NC 4.0 — 비상업 연구, 저장소에 넣지 않는다 → docs_cache/lab/jkp/)
           11-18 내려받음, 2025-12 까지. 한국(kor) · 월간 · capped value weight(시총 가중, NYSE 80분위에서 상한 — 한두 종목이
           지배하지 않게). 파일마다 SHA256 을 FILES 에 고정 — 다르면 측정하지 않는다(JKP 는 판을 갈아 끼운다).
             factors     153 특성의 롱숏 수익(논문 방향으로 부호 맞춤)
             portfolios  특성별 3분위(pf 1 낮음 · 2 · 3 높음) 수익 — 사는 쪽은 여기서
             mkt         한국 시장(같은 가중)
             themes      13 주제 롱숏(구성 대조용) · v0 cluster_labels·factor_directions(GitHub bkelly-lab/jkp-data — 주제 구성과 방향)
           단위: 전부 USD 총수익(배당 포함) − 미국 1개월 국채(설명서 ret_exc). 11-18 확인 — 시총 3분위로 시장을 재구성한 절편이
           고금리 2023~2025 에도 +0.002%/월(±0.012) → 같은 단위. '사는 쪽 − 시장' 에서 환율·무위험 금리는 지워진다(2차 항만 남는다).
  후보 (한국 ETF 로 살 수 있는 팩터만 — 아이디어 장부 네 칸)
    F1 저변동  low_risk 주제(v0 18 특성)  TIGER 로우볼(174350) · KODEX 최소변동성(279540)
    F2 모멘텀  momentum 주제(8)           TIGER 모멘텀(147970) · KODEX 모멘텀주(275280)
    F3 가치    value 주제(18)             TIGER 우량가치(227570) · KODEX 200가치저변동(223190)
    F4 퀄리티  quality 주제(17)           KODEX 우량주(275300)
    F5 배당    div12m_me 하나(배당수익률, Litzenberger·Ramaswamy 1979)  PLUS 고배당주(161510) · KODEX 고배당주(279530)
               (배당은 value 주제의 한 특성이지만 한국 팩터 ETF 의 대부분이 배당이라 따로 묻는다)
  구성     특성 c 의 방향 s(v0 factor_directions) — s>0 이면 사는 쪽 = pf 3, s<0 이면 pf 1(파는 쪽은 반대).
           그 달 JKP 팩터 수익이 있는(다리마다 5종목 이상) 특성만 쓴다. 주제의 사는 쪽 = 그 달 있는 구성 특성들의 사는 쪽 단순 평균
           (JKP 주제 롱숏과 같은 방식 — 롱숏 대신 사는 쪽만).
           가드(어긋나면 측정 중단): G1 특성마다 팩터 수익 = 사는 쪽 − 파는 쪽(오차 1e-9) — 방향 대응 · G2 13 주제 모두 구성
           평균 롱숏 = JKP 주제 파일(오차 1e-6, 그 달 구성 수도 같게) — 구성 대조. 11-18 측정 전 확인은 --check(성과 숫자 안 봄).
  비용     사는 쪽에서 연 COST 를 뺀다(월 1/12): 모멘텀 1.0%p · 나머지 0.5%p — ETF 보수 차(KODEX200 대비 약 0.2~0.3%p) +
           리밸런싱 회전(편도 11.5bp × 연 회전율 — 모멘텀 400% 넘게, 나머지 100~200% 로 추정).
  재는 것  기울기 x_t = 사는 쪽_t − 비용/12 − 시장_t  ·  알파: (사는 쪽_t − 비용/12) = α + β·시장_t + e (최소제곱, 월간).
  구간     A 1996-01~2009-12(외환위기·닷컴·금융위기) · B 2010-01~2020-12 · C 2021-01~2025-12(B·C = 지금까지 판정대 경계,
           자료 끝 2025-12). 전체 = 1996-01~2025-12.
  통과(전부)
    P1 표본  구간마다 값이 있는 달 ≥ 그 구간 달 수의 90%
    P2 방향  구간마다 α > 0(비용 뒤) — 2021 이후에도 살아 있어야 한다
    P3 수익  전체 기간 기울기 평균(비용 뒤) ≥ 0 — 위험만 줄이고 수익을 내주는 쪽은 KODEX200 대신 쓸 이유가 약하다
             (I3 는 수익 엔진 + 낙폭 예산 — 낙폭은 엔진이 맡는다)
    P4 유의  전체 기간 α 의 t ≥ 시험 횟수 장부 통과선 `hurdle_t(total_through('scripts/lab_jkp.py'))` — 98개 → 약 3.48
  보고만   구간별 기울기 평균·t · β · 적중(기울기 > 0 인 달 비율) · 롱숏 평균(논문과 비교). 실제 ETF 의 성적은 판정에 쓰지 않는다
           (FDR 가격엔 분배금이 빠져 배당 ETF 가 불리하고, 상장 2011~2017 이라 기간이 짧다).
  통과하면 그 팩터 ETF 로 I3 엔진을 돌리는 도전자를 리그에 **앞으로만** 등록(어느 ETF·신호를 무엇으로 볼지는 통과 뒤 따로 선언).
           JKP 사는 쪽은 ETF 가 아니다(구성·리밸런싱 주기·비용이 다르다) — 이 판정대는 입장 거름망이고 실전 교체는 리그 기록으로만.

결과 (fb77fa5 선언대로 1회, 기준 수정 없음 — 가드 G1 53,971건 오차 0 · G2 13 주제 최대 오차 2.8e-17) — **F3 가치 통과, 나머지 탈락**
  시험 98개 → 통과선 t ≥ 3.48. 값은 연%(월 × 12), 기울기·알파는 비용 뒤, 롱숏은 비용 없이 보고만.
        후보    구간   달   기울기     t    알파     t     β    적중   롱숏     t   P1 P2
  F1 저변동    A    168  +1.68  +0.86  +2.37  +1.51  0.89  54.2%  +4.24  +1.02  O O
               B    132  −0.83  −0.74  −0.21  −0.21  0.92  50.8%  −0.96  −0.38  O X
               C     60  +2.33  +0.85  +2.64  +1.28  0.83  51.7%  +6.21  +1.03  O O
               전체 360  +0.87  +0.79  +1.54  +1.72  0.89  52.5%  +2.66  +1.12  P3 O · P4 X → 탈락
  F2 모멘텀    A    168  −0.11  −0.04  +0.00  +0.00  0.98  44.6%  +0.52  +0.09  O O
               B    132  +0.74  +0.39  +0.88  +0.47  0.98  56.1%  +2.24  +0.64  O O
               C     60  +2.37  +0.78  +2.29  +0.76  1.04  55.0%  +6.62  +1.18  O O
               전체 360  +0.61  +0.42  +0.69  +0.47  0.99  50.6%  +2.17  +0.72  P3 O · P4 X → 탈락
  F3 가치      A    168  +8.68  +4.95  +8.67  +4.93  1.00  72.0% +10.43  +3.21  O O
               B    132  +1.77  +1.60  +1.88  +1.69  0.99  57.6%  +1.91  +0.71  O O
               C     60  +5.39  +1.88  +5.63  +2.24  0.87  56.7%  +8.04  +1.27  O O
               전체 360  +5.60  +5.38  +5.68  +5.46  0.99  64.2%  +6.91  +3.30  P3 O · P4 O → **통과**
  F4 퀄리티    A    168  +7.78  +2.93  +8.02  +3.04  0.96  56.0%  +9.10  +2.39  O O
               B    132  +1.55  +1.30  +2.16  +1.97  0.92  59.8%  +3.84  +1.67  O O
               C     60  −0.90  −0.57  −0.83  −0.54  0.96  50.0%  −0.62  −0.24  O X
               전체 360  +4.05  +3.00  +4.32  +3.24  0.96  56.4%  +5.55  +2.75  P3 O · P4 X → 탈락
  F5 배당      A    156  +6.65  +2.19  +6.97  +2.42  0.91  59.6%  +3.53  +0.60  O O
               B    132  +2.29  +1.14  +2.59  +1.29  0.96  57.6%  +4.25  +1.12  O O
               C     60  +6.88  +1.44  +7.32  +1.83  0.76  61.7%  +7.92  +0.96  O O
               전체 348  +5.04  +2.86  +5.51  +3.29  0.90  59.2%  +4.56  +1.37  P3 O · P4 X → 탈락(통과선 3.48 에 0.19 모자람)
읽는 법
  · **가치(F3)만 통과** — 싼 3분위만 사도 한국 시장보다 연 +5.7%p(비용 0.5%p 뒤), β 1.0 이라 위험을 줄여서 얻은 게 아니다.
    세 구간 모두 플러스지만 **힘은 A(1996~2009, +8.7%p · t 4.9)에 몰려 있다**. B(2010~2020)는 +1.9%p · t 1.7 로 약했고(세계적으로
    가치가 부진했던 10년), C(2021~2025)는 +5.6%p · t 2.2. 2024 기업 밸류업 정책(저PBR 재평가)이 C 에 들어 있다 — 정책 한 번의
    효과인지 지속될 우위인지는 이 자료로 가를 수 없다.
  · JKP 의 '사는 쪽'은 코스피·코스닥 전체(소형주 포함, 시총 상한 가중)다. 한국 가치 ETF 는 대부분 코스피200 안에서 고르고 작다
    (TIGER 우량가치 51억 · KODEX 200가치저변동 224억) — **ETF 로 실제 잡히는 몫은 이보다 작을 수 있다**. 그래서 판정은 리그(앞으로만).
  · 배당(F5)은 세 구간 모두 플러스 · t 3.29 로 아깝게 탈락 — 배당수익률은 가치 주제의 한 특성이라 같은 현상의 일부로 보인다.
    퀄리티(F4)는 2021 이후 마이너스(−0.8%p) — 발표 뒤 줄어든다는 문헌(McLean·Pontiff 2016)과 같은 모양. 모멘텀(F2)은 30년 내내 0 근처 —
    아시아 시장에서 모멘텀이 약하다는 문헌(Chui·Titman·Wei 2010)과 같다. 저변동(F1)은 2010~2020 에 마이너스.
  · 보고만: 롱숏(공매도 포함)으로도 가치가 가장 강하다(+6.9%p · t 3.30 — 롱숏엔 비용을 안 뺐다).
  다음: 선언대로 '가치 ETF × I3 엔진' 도전자를 따로 선언해 리그에 앞으로만 — 어느 ETF·신호를 무엇으로 볼지가 그 선언의 내용.
"""
from __future__ import annotations

import csv
import hashlib
import math
import re
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_trials as T  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
SOURCE = "scripts/lab_jkp.py"                     # 시험 횟수 장부의 이 묶음 행
DATA_DIR = _ROOT / "docs_cache" / "lab" / "jkp"
_BASE = "https://data.jkpfactors.com/public"
FILES: dict[str, tuple[str, str]] = {             # 캐시 이름 → (SHA256, 받은 곳) — 11-18 내려받음
    "kor_factors_monthly.csv": ("e90e75c7f2320da74a849d0d532ed8be5ab1ecc04a85395b2b3916cef6795201",
                                f"{_BASE}/[kor]_[all_factors]_[monthly]_[vw_cap].zip"),
    "kor_pf_monthly.csv": ("237e913cc5f693e73618db999895289211f157db108d5f4bb4757f8b50e0cd33",
                           f"{_BASE}/portfolios/[kor]_[all_factors]_[monthly]_[vw_cap].zip"),
    "kor_mkt_monthly.csv": ("091de6b0f0b8f90d4ce0a012ba07159bca0a1a3f443096b765bddc6c413fb919",
                            f"{_BASE}/[kor]_[mkt]_[monthly]_[vw_cap].zip"),
    "kor_themes_monthly.csv": ("ccec3042a68cd2ee70316d5f51cc20c0eda465ae00509c270063a9a22a41ca89",
                               f"{_BASE}/[kor]_[all_themes]_[monthly]_[vw_cap].zip"),
    "v0_cluster_labels.csv": ("22c7fdd214218d1210ab9922efed59bf607538098cc06b6f2c5f326d2e6cf64b",
                              "https://github.com/bkelly-lab/jkp-data/tree/main/src/jkp/data/resources/themes/superseded_themes/v0"),
    "v0_factor_directions.csv": ("bbc2f71189c7fd6fba8b4aff7a0ff54eebaa3f268d36048c03d4113e6877dcc3",
                                 "https://github.com/bkelly-lab/jkp-data/tree/main/src/jkp/data/resources/themes/superseded_themes/v0"),
}
PERIODS = {"A": ("1996-01", "2009-12"), "B": ("2010-01", "2020-12"), "C": ("2021-01", "2025-12")}
FULL = ("1996-01", "2025-12")
MIN_COVER = 0.9
LEG_TOL = 1e-9
THEME_TOL = 1e-6
# 이름 → (설명, (종류, 키), 연 비용, 한국 ETF) — 종류 'theme' 은 v0 주제 이름, 'char' 는 특성 하나
CANDIDATES: dict[str, tuple[str, tuple[str, str], float, str]] = {
    "F1": ("저변동", ("theme", "Low Risk"), 0.005, "TIGER 로우볼(174350) · KODEX 최소변동성(279540)"),
    "F2": ("모멘텀", ("theme", "Momentum"), 0.010, "TIGER 모멘텀(147970) · KODEX 모멘텀주(275280)"),
    "F3": ("가치", ("theme", "Value"), 0.005, "TIGER 우량가치(227570) · KODEX 200가치저변동(223190)"),
    "F4": ("퀄리티", ("theme", "Quality"), 0.005, "KODEX 우량주(275300)"),
    "F5": ("배당", ("char", "div12m_me"), 0.005, "PLUS 고배당주(161510) · KODEX 고배당주(279530)"),
}


def trials() -> int:
    return T.total_through(SOURCE)


def hurdle() -> float:
    return T.hurdle_t(trials())


# ── 자료 ─────────────────────────────────────────────────────────────────────
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_files(d: Path = DATA_DIR, files: dict[str, tuple[str, str]] = FILES) -> None:
    """선언 때 고정한 파일과 같은가 — 없거나 다르면 RuntimeError(측정하지 않는다)."""
    bad = []
    for name, (digest, url) in files.items():
        p = d / name
        if not p.exists():
            bad.append(f"{name} 없음 — {url}")
        elif sha256(p) != digest:
            bad.append(f"{name} 해시 다름(JKP 판이 바뀌었나?) — 선언한 자료가 아니면 재지 않는다")
    if bad:
        raise RuntimeError("JKP 자료 확인 실패: " + " · ".join(bad))


def _num(x: str) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def theme_key(cluster: str) -> str:
    """v0 주제 이름 → 주제 파일의 name('Short-Term Reversal' → 'short_term_reversal')."""
    return re.sub(r"[^a-z]+", "_", cluster.lower()).strip("_")


def load(d: Path = DATA_DIR, verify: bool = True) -> dict:
    if verify:
        verify_files(d)

    def rows(name):
        with open(d / name, encoding="utf-8", newline="") as f:
            yield from csv.DictReader(f)

    factors: dict[str, dict[str, float]] = {}
    for r in rows("kor_factors_monthly.csv"):
        if (v := _num(r["ret"])) is not None:
            factors.setdefault(r["name"], {})[r["date"][:7]] = v
    pf: dict[str, dict[str, dict[int, float]]] = {}
    for r in rows("kor_pf_monthly.csv"):
        if (v := _num(r["ret"])) is not None:
            pf.setdefault(r["name"], {}).setdefault(r["date"][:7], {})[int(float(r["pf"]))] = v
    mkt = {r["date"][:7]: v for r in rows("kor_mkt_monthly.csv") if (v := _num(r["ret"])) is not None}
    themes: dict[str, dict[str, tuple[float, int]]] = {}
    for r in rows("kor_themes_monthly.csv"):
        if (v := _num(r["ret"])) is not None:
            themes.setdefault(r["name"], {})[r["date"][:7]] = (v, int(r["n_factors"]))
    clusters = {r["characteristic"]: r["cluster"] for r in rows("v0_cluster_labels.csv")}
    dirs = {r["characteristic"]: int(float(r["direction"])) for r in rows("v0_factor_directions.csv")}
    return {"factors": factors, "pf": pf, "mkt": mkt, "themes": themes, "clusters": clusters, "dirs": dirs}


# ── 구성 ─────────────────────────────────────────────────────────────────────
def long_pf(direction: int) -> int:
    return 3 if direction > 0 else 1


def short_pf(direction: int) -> int:
    return 1 if direction > 0 else 3


def members(cluster: str, data: dict) -> list[str]:
    return sorted(c for c, cl in data["clusters"].items() if cl == cluster)


def char_point(c: str, ym: str, data: dict) -> tuple[float, float] | None:
    """특성 c 의 그 달 (사는 쪽, 롱숏) — JKP 팩터 수익이 있고 두 다리가 다 있을 때만."""
    f = data["factors"].get(c, {}).get(ym)
    legs = data["pf"].get(c, {}).get(ym, {})
    d = data["dirs"].get(c)
    if f is None or d is None or long_pf(d) not in legs or short_pf(d) not in legs:
        return None
    return legs[long_pf(d)], f


def series(spec: tuple[str, str], data: dict) -> dict[str, tuple[float, float, int]]:
    """{YYYY-MM: (사는 쪽, 롱숏, 쓴 특성 수)} — 주제는 그 달 있는 구성 특성의 단순 평균."""
    kind, key = spec
    if kind == "theme":
        chars = members(key, data)
    elif kind == "char":
        chars = [key]
    else:
        raise ValueError(kind)
    months = sorted(set().union(*(data["factors"].get(c, {}).keys() for c in chars))) if chars else []
    out = {}
    for ym in months:
        pts = [p for c in chars if (p := char_point(c, ym, data)) is not None]
        if pts:
            out[ym] = (statistics.fmean(a for a, _ in pts), statistics.fmean(b for _, b in pts), len(pts))
    return out


# ── 가드 ─────────────────────────────────────────────────────────────────────
def guard_legs(data: dict, tol: float = LEG_TOL) -> dict:
    """G1 — 특성마다 팩터 수익 = 사는 쪽 − 파는 쪽(방향 대응). 다리가 빠진 달도 실패로 센다."""
    worst, n, missing, bad = 0.0, 0, 0, []
    for c, fs in data["factors"].items():
        d = data["dirs"].get(c)
        if d is None:
            continue
        for ym, f in fs.items():
            legs = data["pf"].get(c, {}).get(ym, {})
            if long_pf(d) not in legs or short_pf(d) not in legs:
                missing += 1
                continue
            e = abs(f - (legs[long_pf(d)] - legs[short_pf(d)]))
            n += 1
            if e > worst:
                worst = e
            if e > tol and len(bad) < 5:
                bad.append(f"{c} {ym}")
    no_dir = sorted(c for c in data["factors"] if c not in data["dirs"])
    return {"checked": n, "missing": missing, "worst": worst, "examples": bad, "no_direction": no_dir,
            "ok": n > 0 and worst <= tol and missing == 0}


def guard_themes(data: dict, tol: float = THEME_TOL) -> dict:
    """G2 — 13 주제 모두, 구성 특성 평균 롱숏 = JKP 주제 파일, 그 달 구성 수도 같게."""
    worst, n, bad = 0.0, 0, []
    clusters = sorted(set(data["clusters"].values()))
    for cl in clusters:
        ser = series(("theme", cl), data)
        theirs = data["themes"].get(theme_key(cl), {})
        if not theirs:
            bad.append(f"{cl}: 주제 파일에 없음")
            continue
        for ym in sorted(set(theirs) | set(ser)):
            if ym not in theirs or ym not in ser:
                if len(bad) < 8:
                    bad.append(f"{cl} {ym}: {'우리만' if ym in ser else 'JKP 만'}")
                n += 1
                worst = math.inf
                continue
            r, k = theirs[ym]
            e = abs(ser[ym][1] - r)
            n += 1
            worst = max(worst, e)
            if ser[ym][2] != k and len(bad) < 8:
                bad.append(f"{cl} {ym}: 구성 {ser[ym][2]} ≠ {k}")
    return {"themes": len(clusters), "checked": n, "worst": worst, "examples": bad,
            "ok": n > 0 and worst <= tol and not bad}


# ── 판정 ─────────────────────────────────────────────────────────────────────
def months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7]) + 1


def ols(y: list[float], x: list[float]) -> dict:
    """y = α + βx — α 의 t 는 보통 최소제곱 표준오차."""
    n = len(y)
    if n < 3:
        return {"alpha": float("nan"), "beta": float("nan"), "t": float("nan")}
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx <= 0:
        return {"alpha": float("nan"), "beta": float("nan"), "t": float("nan")}
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    alpha = my - beta * mx
    s2 = sum((b - alpha - beta * a) ** 2 for a, b in zip(x, y)) / (n - 2)
    se = math.sqrt(s2 * (1 / n + mx * mx / sxx))
    return {"alpha": alpha, "beta": beta, "t": alpha / se if se > 0 else float("nan")}


def _mean_t(xs: list[float]) -> tuple[float, float]:
    if len(xs) < 2:
        return (xs[0] if xs else float("nan")), float("nan")
    m, sd = statistics.fmean(xs), statistics.stdev(xs)
    return m, (m / (sd / math.sqrt(len(xs))) if sd > 0 else float("nan"))


def window(ser: dict, mkt: dict, cost: float, a: str, b: str) -> dict:
    """한 구간 — 사는 쪽에서 연 비용(월 1/12)을 뺀 뒤 기울기·알파·롱숏."""
    ms = [m for m in sorted(ser) if a <= m <= b and m in mkt]
    long = [ser[m][0] - cost / 12 for m in ms]
    mk = [mkt[m] for m in ms]
    tilt = [x - y for x, y in zip(long, mk)]
    tm, tt = _mean_t(tilt)
    lm, lt = _mean_t([ser[m][1] for m in ms])
    reg = ols(long, mk)
    return {"months": len(ms), "expected": months_between(a, b), "tilt": tm, "tilt_t": tt,
            "alpha": reg["alpha"], "alpha_t": reg["t"], "beta": reg["beta"],
            "hit": (sum(x > 0 for x in tilt) / len(tilt)) if tilt else float("nan"), "ls": lm, "ls_t": lt}


def judge(name: str, data: dict, hurdle_t: float) -> dict:
    _, spec, cost, _ = CANDIDATES[name]
    ser = series(spec, data)
    per = {}
    for p, (a, b) in PERIODS.items():
        s = window(ser, data["mkt"], cost, a, b)
        s["checks"] = {"P1": s["months"] >= MIN_COVER * s["expected"], "P2": s["months"] > 2 and s["alpha"] > 0}
        per[p] = s
    full = window(ser, data["mkt"], cost, *FULL)
    full["P3"] = full["months"] > 0 and full["tilt"] >= 0
    full["P4"] = full["months"] > 2 and full["alpha_t"] >= hurdle_t
    ok = all(all(s["checks"].values()) for s in per.values()) and full["P3"] and full["P4"]
    return {"periods": per, "full": full, "pass": ok}


def guards(data: dict) -> tuple[dict, dict]:
    g1, g2 = guard_legs(data), guard_themes(data)
    if not (g1["ok"] and g2["ok"]):
        raise RuntimeError(f"구성 가드 실패 — G1 {g1} · G2 {g2}")
    return g1, g2


def measure(data: dict) -> dict:
    g1, g2 = guards(data)
    h = hurdle()
    return {"hurdle": h, "trials": trials(), "g1": g1, "g2": g2,
            "res": {n: judge(n, data, h) for n in CANDIDATES}}


def coverage(data: dict) -> dict:
    """--check: 후보·구간별 값이 있는 달 수만(성과 숫자는 계산하지 않는다)."""
    out = {}
    for n, (_, spec, _, _) in CANDIDATES.items():
        ser = series(spec, data)
        out[n] = {p: (sum(1 for m in ser if a <= m <= b and m in data["mkt"]), months_between(a, b))
                  for p, (a, b) in PERIODS.items()}
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    data = load()
    if "--check" in argv:
        g1, g2 = guard_legs(data), guard_themes(data)
        print(f"G1 방향 대응: 확인 {g1['checked']} · 다리 빠짐 {g1['missing']} · 최대 오차 {g1['worst']:.2e} · "
              f"방향 없는 특성 {g1['no_direction']} → {'OK' if g1['ok'] else '실패 ' + str(g1['examples'])}")
        print(f"G2 주제 구성: {g2['themes']} 주제 · {g2['checked']} 달 · 최대 오차 {g2['worst']:.2e} → "
              f"{'OK' if g2['ok'] else '실패 ' + str(g2['examples'])}")
        for n, cov in coverage(data).items():
            print(f"  {n} {CANDIDATES[n][0]:4} " + " · ".join(f"{p} {k}/{e}" for p, (k, e) in cov.items()))
        print(f"시험 {trials()}개 → 통과선 t ≥ {hurdle():.2f}")
        return 0 if (g1["ok"] and g2["ok"]) else 1
    m = measure(data)
    print("=" * 122)
    print(f"한국 팩터 기울기 판정대(사는 쪽만) — JKP 한국 월간 capped VW · 구간 {FULL[0]}~{FULL[1]} · "
          f"시험 {m['trials']}개 → 통과선 t ≥ {m['hurdle']:.2f}")
    print(f"  가드 G1 {m['g1']['checked']}건 최대 오차 {m['g1']['worst']:.1e} · G2 {m['g2']['themes']} 주제 {m['g2']['checked']}달 "
          f"최대 오차 {m['g2']['worst']:.1e}")
    print(f"  {'':4}{'후보':6}{'구간':6}{'달':>5}{'기울기%/년':>11}{'t':>7}{'알파%/년':>10}{'t':>7}{'β':>6}{'적중':>7}"
          f"{'롱숏%/년':>10}{'t':>7}  P1 P2")
    passed = []
    for name, (desc, _, cost, _) in CANDIDATES.items():
        r = m["res"][name]
        rows = list(r["periods"].items()) + [("전체", r["full"])]
        for i, (p, s) in enumerate(rows):
            ch = (" ".join("O " if s["checks"][k] else "X " for k in ("P1", "P2")) if "checks" in s
                  else f"P3 {'O' if s['P3'] else 'X'} P4 {'O' if s['P4'] else 'X'}  {'통과' if r['pass'] else '탈락'}")
            head = f"{name:4}{desc:6}" if i == 0 else " " * 10
            print(f"  {head}{p:6}{s['months']:>5}{s['tilt'] * 1200:>+11.2f}{s['tilt_t']:>+7.2f}"
                  f"{s['alpha'] * 1200:>+10.2f}{s['alpha_t']:>+7.2f}{s['beta']:>6.2f}{s['hit'] * 100:>6.1f}%"
                  f"{s['ls'] * 1200:>+10.2f}{s['ls_t']:>+7.2f}  {ch}")
        if r["pass"]:
            passed.append(name)
    print("=" * 122)
    print(f"(기울기·알파 = 사는 쪽 − 연 비용 기준: 모멘텀 1.0%p · 나머지 0.5%p — 롱숏은 비용 없이 보고만)")
    print(f"통과(구간마다 P1·P2 + 전체 P3 + 알파 t ≥ {m['hurdle']:.2f}): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
