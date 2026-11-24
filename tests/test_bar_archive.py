"""일봉 보관소(bar_archive) — FDR 3,000거래일 상한 대비 (2026-11-24, 백로그 ⑮).

FDR 은 한국 ETF 를 최근 3,000거래일만 주고, 분배금이 나오면 앞의 모든 날을 같은 비율로 다시 계산한다.
보관소가 ① 앞쪽 날을 새 가격 기준으로 맞춰 붙이는지 ② 이상한 비율·깨진 파일이면 붙이지도 덮어쓰지도 않는지
③ 실제 경계(load_bars → 보관 파일 → 다음 날 load_bars)를 지나 이력이 줄지 않는지 확인한다.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import atomic_io as AIO  # noqa: E402
import bar_archive as BA  # noqa: E402
import strategy_lab as L  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_archive(tmp_path, monkeypatch):
    """실제 data/bar_archive 를 절대 건드리지 않는다."""
    monkeypatch.setattr(BA, "ARCHIVE_DIR", tmp_path / "archive")
    BA.ERRORS.clear()
    yield
    BA.ERRORS.clear()


def _days(n, d0=date(2014, 7, 28)):
    out, d = [], d0
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _raw(days):
    """원가격 — 매일 조금씩 오르내린다(정수 호가)."""
    return {d: {"open": float(20000 + (i * 37) % 900), "close": float(20000 + (i * 53) % 1100)}
            for i, d in enumerate(days)}


def _rebase(rows, q):
    return {d: {k: v * q for k, v in b.items()} for d, b in rows.items()}


def _returns(rows):
    ds = sorted(rows)
    return [rows[b]["close"] / rows[a]["close"] - 1 for a, b in zip(ds, ds[1:])]


# ── 순수 함수 ───────────────────────────────────────────────────────────────
def test_stitch_rescales_older_days_to_fresh_basis():
    """★ 분배금 재계산(× 0.985) 뒤 받은 이력에 옛 보관을 붙여도 이음매에서 가격이 튀지 않는다 — 수익률 열이 원본과 같다."""
    days = _days(300)
    raw = _raw(days)
    archive = {d: raw[d] for d in days[:250]}                   # 어제까지 받은 것(옛 기준)
    fresh = _rebase({d: raw[d] for d in days[40:]}, 0.985)       # 오늘 받은 것: 앞 40일이 빠지고 전부 × 0.985
    out, why = BA.stitch(archive, fresh)
    assert why is None and sorted(out) == days
    assert out[days[0]]["close"] == pytest.approx(raw[days[0]]["close"] * 0.985)
    assert _returns(out) == pytest.approx(_returns(raw), abs=1e-12)
    assert all(out[d] == fresh[d] for d in fresh)                # 겹치는 날은 새 이력 그대로


def test_stitch_is_noop_when_nothing_older():
    days = _days(100)
    raw = _raw(days)
    out, why = BA.stitch({d: raw[d] for d in days[10:]}, raw)
    assert why is None and out == raw
    assert BA.stitch({}, raw) == (raw, None) and BA.stitch(raw, {}) == ({}, None)


def test_stitch_refuses_scattered_ratios_and_too_few_common():
    """★ 일부러 깨뜨린다 — 같은 비율 재계산이 아닌 차이(일부 날만 3%)·겹치는 날 부족이면 붙이지 않고 이유를 남긴다."""
    days = _days(200)
    raw = _raw(days)
    archive = {d: dict(raw[d]) for d in days[:150]}
    for d in days[50:60]:
        archive[d] = {k: v * 1.03 for k, v in archive[d].items()}
    fresh = {d: raw[d] for d in days[50:]}
    out, why = BA.stitch(archive, fresh)
    assert out == fresh and "흩어짐" in why
    out, why = BA.stitch({d: raw[d] for d in days[:53]}, fresh)    # 겹치는 날 3일
    assert out == fresh and "겹치는 날 3일" in why


def test_stitch_tolerates_integer_rounding_of_rebased_prices():
    """FDR 은 다시 계산한 가격을 정수로 반올림한다 — 그 정도 흩어짐(~0.005%)은 붙인다."""
    days = _days(120)
    raw = _raw(days)
    fresh = {d: {k: float(round(v * 0.99858)) for k, v in raw[d].items()} for d in days[30:]}
    out, why = BA.stitch({d: raw[d] for d in days[:100]}, fresh)
    assert why is None and min(out) == days[0]


# ── 실제 경계: load_bars(archive=True) → 보관 파일 → 다음 날 ─────────────────
def _capped_source(all_days, raw, cap):
    """FDR 흉내 — end 까지의 최근 cap 일만 준다. calls 에 (end, q) 를 남긴다. q = 그날의 가격 기준."""
    state = {"q": 1.0}

    def fetch(code, start, end):
        ds = [d for d in all_days if start <= d <= end][-cap:]
        return _rebase({d: raw[d] for d in ds}, state["q"])
    return fetch, state


def test_load_bars_keeps_history_across_days_through_archive(tmp_path, monkeypatch):
    """★ 매일 앞쪽이 하루씩 빠지고 분배금으로 기준이 바뀌어도, 실전 조회(archive=True)의 첫 날은 그대로이고 이음매가 없다."""
    days = _days(400)
    raw = _raw(days)
    fetch, src = _capped_source(days, raw, cap=300)
    monkeypatch.setattr(L, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(L, "_fetch", fetch)
    d1, d2, d3 = days[320], days[340], days[360]
    a = L.load_bars("069500", "2010-01-01", d1, archive=True)
    assert min(a) == days[21]                                   # 첫 날 보관 = FDR 그대로
    src["q"] = 0.985                                            # 분배금 — FDR 이 앞의 모든 날을 다시 계산
    b = L.load_bars("069500", "2010-01-01", d2, archive=True)
    assert min(b) == days[21] and len(b) == 320                 # FDR 은 days[41]~ 만 줬지만 앞 20일이 붙었다
    assert _returns(b) == pytest.approx(_returns({d: raw[d] for d in b}), abs=1e-12)
    c = L.load_bars("069500", "2010-01-01", d3, archive=True)
    assert min(c) == days[21] and max(c) == d3
    saved = BA.read("069500")
    assert min(saved) == days[21] and max(saved) == d3 and AIO.bak_of(BA.path_of("069500")).exists()
    plain = L.load_bars("069500", "2010-01-01", d3)              # 연구(archive 없음)는 FDR 원본 그대로
    assert min(plain) == days[61]


def test_past_end_query_does_not_rewrite_archive(tmp_path, monkeypatch):
    """과거 종료일 조회는 보관을 읽기만 한다 — 보관의 최근 날을 지우지 않는다."""
    days = _days(400)
    raw = _raw(days)
    fetch, _ = _capped_source(days, raw, cap=300)
    monkeypatch.setattr(L, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(L, "_fetch", fetch)
    L.load_bars("069500", "2010-01-01", days[390], archive=True)
    before = BA.path_of("069500").read_bytes()
    old = L.load_bars("069500", "2010-01-01", days[350], archive=True)
    assert max(old) == days[350] and BA.path_of("069500").read_bytes() == before


def test_merge_leaves_archive_untouched_on_mismatch_or_broken_file():
    """★ 일부러 깨뜨린다 — 비율이 흩어진 보관·깨진 보관 파일이면 FDR 만 돌려주고, 보관 파일은 그대로, 이유는 ERRORS 에."""
    days = _days(200)
    raw = _raw(days)
    bad = {d: dict(raw[d]) for d in days[:150]}
    for d in days[50:60]:
        bad[d] = {k: v * 1.03 for k, v in bad[d].items()}
    BA._write("069500", bad)
    before = BA.path_of("069500").read_bytes()
    fresh = {d: raw[d] for d in days[50:]}
    assert BA.merge("069500", fresh) == fresh and "흩어짐" in BA.ERRORS["069500"]
    assert BA.path_of("069500").read_bytes() == before
    BA.path_of("069500").write_text("{깨짐", encoding="utf-8")
    assert BA.merge("069500", fresh) == fresh and "읽기 실패" in BA.ERRORS["069500"]
    assert BA.path_of("069500").read_text(encoding="utf-8") == "{깨짐"
    BA._write("069500", {d: raw[d] for d in days[:150]})
    assert min(BA.merge("069500", fresh)) == days[0] and "069500" not in BA.ERRORS   # 고치면 오류가 지워진다


def test_seed_joins_old_caches_newest_basis_first():
    """--seed: 가장 최근에 받은 캐시가 기준, 더 옛 캐시는 앞쪽 날만 그 기준으로 맞춰 붙인다."""
    days = _days(300)
    raw = _raw(days)
    new = _rebase({d: raw[d] for d in days[30:]}, 0.98)
    old = {d: raw[d] for d in days[:280]}
    rows, notes = BA.seed([new, old])
    assert notes == [] and min(rows) == days[0] and rows[days[100]] == new[days[100]]
    assert _returns(rows) == pytest.approx(_returns(raw), abs=1e-12)


# ── 실데이터: 10월 분배금 재계산 전후 캐시 ─────────────────────────────────────
def test_real_caches_stitch_across_october_distribution_and_keep_engine_state():
    """★ 실데이터 — 10-22 에 받은 KODEX200(옛 기준)과 11-23 에 받은 것(10월 분배 뒤 × 0.99858)을 이어 붙인다.
    2027 상한을 흉내 내 새 이력을 2015-07-01 부터로 자르면 가드가 잡고, 보관을 붙이면 엔진 판단이 원본과 같다."""
    import i3_core as K
    cache = _ROOT / "docs_cache" / "lab"
    need = ["069500_2026-10-21.json", "069500_2026-09-30.json", "IDX_KS11_2026-10-21.json"]
    if not all((cache / n).exists() for n in need):
        pytest.skip("실데이터 캐시 없음")
    old = json.loads((cache / need[0]).read_text(encoding="utf-8"))          # 10-22 받음 — 2014-07-28~
    new = json.loads((cache / need[1]).read_text(encoding="utf-8"))          # 11-23 받음 — 분배 뒤 기준
    ks = L.load_bars("^KS11", "1996-01-01", "2026-10-21")
    q = new["2015-07-28"]["close"] / old["2015-07-28"]["close"]
    if abs(q - 1) < 1e-4:
        pytest.skip("두 캐시의 가격 기준이 같다 — 다시 받은 캐시")
    assert q == pytest.approx(0.99858, abs=2e-4)
    cut = {d: v for d, v in new.items() if d >= "2015-07-01"}
    assert "이력 부족" in K.history_short(cut, ks)
    out, why = BA.stitch(old, cut)
    assert why is None and min(out) == min(old) and K.history_short(out, ks) is None
    probe = sorted(d for d in new if d >= K.REPLAY_START)[::61]
    assert all(K.engine_state(out, ks, d) == K.engine_state(old, ks, d) for d in probe)
