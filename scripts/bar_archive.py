"""일봉 보관소 — FDR 이 한국 ETF 를 최근 3,000거래일만 주는 상한 대비 (2026-11-24, 백로그 ⑮).

FDR 은 KODEX200 같은 한국 ETF 를 **최근 3,000거래일만** 준다 — 이력 첫 날이 매일 하루씩 밀린다
(10-22 받은 것 2014-07-28~ → 11-24 받은 것 2014-09-01~). 실전 I3 는 2015-07-28 부터 엔진을 재생하고(20일 고점이라
그 앞 20일이 필요), 리그 멤버는 더 긴 되돌아보기(252일 등)를 쓴다. 보관소는 실전·리그가 매일 받은 이력을 쌓아 두고,
FDR 이 더는 주지 않는 앞쪽 날을 이어 붙인다 — 재생 시작일 앞 이력이 줄지 않는다.

⚠️ FDR(과 키움 수정주가)은 분배금·분할이 있으면 **그 앞의 모든 날 가격을 같은 비율로 다시 계산한다**
(11-24 실측: 10월 분배 뒤 KODEX200 2014-09-01~2026-10-21 전부 × 0.99858 · 키움 ka10081 수정주가와 150일 비율 1.0000).
그래서 보관한 옛 날을 그대로 붙이면 이음매에서 가격이 튄다 — **겹치는 가장 오래된 날들의 비율(새 이력 ÷ 보관)을 재서
옛 날에 곱해** 붙인다. 비율이 흩어져 있으면(같은 비율 재계산이 아닌 무언가) 붙이지 않고 원인을 `ERRORS` 에 남긴다.

  · `stitch(archive, fresh)` — 순수 함수 → (합친 것, 문제 설명 | None). 겹치는 날은 새 이력이 이긴다.
  · `merge(key, fresh)` — 보관 파일을 읽어 붙인다. 앞으로 가는 조회(새 이력 마지막 날 ≥ 보관 마지막 날)일 때만 보관을
    갱신한다(과거 종료일 조회가 보관의 최근 날을 지우지 않게). 읽기 실패·비율 불일치면 보관을 건드리지 않는다.
  · `seed(sources)` — 처음 한 번: 남아 있는 옛 기준일 캐시들을 이어 붙여 보관을 만든다(`--seed`).

쓰는 곳은 실전·리그뿐(`strategy_lab.load_bars(..., archive=True)` · `lab_classics.load_ohlc(..., archive=True)`).
연구는 고정 기준일 캐시를 그대로 쓴다(재현성). 보관 파일은 `data/bar_archive/<key>.json`(+ `.bak`).

    python scripts/bar_archive.py --seed 069500 ^KS11 …   # 캐시 파일들로 보관 만들기(이미 있으면 그 위에 붙임)
    python scripts/bar_archive.py --status                 # 보관별 첫 날·마지막 날·일수
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import atomic_io as AIO  # noqa: E402

log = logging.getLogger("bar_archive")

ARCHIVE_DIR = _ROOT / "data" / "bar_archive"
FIELDS = ("open", "high", "low", "close")
PROBE = 20            # 비율을 재는 겹치는 날 수(가장 오래된 쪽부터)
MIN_COMMON = 5        # 겹치는 날이 이보다 적으면 붙이지 않는다
TOL = 0.001           # 비율이 중앙값에서 이만큼 넘게 흩어지면 붙이지 않는다(정수 호가 반올림은 ~0.005%)

ERRORS: dict[str, str] = {}     # 이번 실행에서 보관을 붙이지 못한 key → 이유(판단·리그 알림이 읽는다)


def stitch(archive: dict[str, dict], fresh: dict[str, dict], probe: int = PROBE,
           tol: float = TOL) -> tuple[dict[str, dict], str | None]:
    """보관 이력 중 fresh 첫 날보다 이른 날을 fresh 기준 가격으로 맞춰 앞에 붙인다 → (합친 것, 문제 | None).

    붙일 옛 날이 없으면 fresh 그대로(문제 없음). 문제가 있으면 fresh 그대로 + 설명."""
    if not archive or not fresh:
        return dict(fresh), None
    first = min(fresh)
    older = sorted(d for d in archive if d < first)
    if not older:
        return dict(fresh), None
    common = [d for d in sorted(fresh) if d in archive][:probe]
    qs = sorted(fresh[d][f] / archive[d][f] for d in common for f in FIELDS
                if archive[d].get(f) and fresh[d].get(f))
    if len(common) < MIN_COMMON or not qs:
        return dict(fresh), f"겹치는 날 {len(common)}일 — 보관 이력 {len(older)}일을 붙이지 않음"
    q = qs[len(qs) // 2]
    worst = max(abs(x / q - 1) for x in qs)
    if worst > tol:
        return dict(fresh), (f"겹치는 날 가격 비율이 흩어짐(중앙 {q:.5f}, 최대 차이 {worst:.2%}) — "
                             f"보관 이력 {len(older)}일을 붙이지 않음")
    out = {d: {f: (v * q if f in FIELDS else v) for f, v in archive[d].items()} for d in older}
    out.update(fresh)
    return out, None


def path_of(key: str, root: Path | None = None) -> Path:
    return (root or ARCHIVE_DIR) / f"{key}.json"


def read(key: str, root: Path | None = None) -> dict[str, dict]:
    """보관 이력. 없으면 {}. 깨졌으면 예외(호출자가 보관을 덮어쓰지 않게)."""
    p = path_of(key, root)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _write(key: str, rows: dict[str, dict], root: Path | None = None) -> None:
    p = path_of(key, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    AIO.write_text(p, json.dumps({d: rows[d] for d in sorted(rows)}), keep_bak=True)


def merge(key: str, fresh: dict[str, dict], root: Path | None = None) -> dict[str, dict]:
    """fresh(FDR 에서 막 받은 이력) + 보관의 앞쪽 날. 보관은 앞으로 가는 조회일 때만 갱신한다."""
    ERRORS.pop(key, None)
    try:
        arch = read(key, root)
    except (OSError, ValueError) as e:
        ERRORS[key] = f"보관 파일 읽기 실패({e}) — 보관을 건드리지 않음(.bak 확인)"
        log.warning("[ARCHIVE] %s %s", key, ERRORS[key])
        return dict(fresh)
    merged, why = stitch(arch, fresh)
    if why:
        ERRORS[key] = why
        log.warning("[ARCHIVE] %s %s", key, why)
        return merged
    if fresh and (not arch or max(fresh) >= max(arch)) and merged != arch:
        try:
            _write(key, merged, root)
        except OSError as e:          # 보관 갱신 실패는 오늘 결과를 바꾸지 않는다 — 다음 실행이 다시 쓴다
            ERRORS[key] = f"보관 파일 쓰기 실패({e})"
            log.warning("[ARCHIVE] %s %s", key, ERRORS[key])
    return merged


def seed(sources: list[dict[str, dict]]) -> tuple[dict[str, dict], list[str]]:
    """sources = **가격 기준이 새것부터**(가장 최근에 받은 캐시 먼저). 앞의 것에 뒤의 것의 앞쪽 날을 이어 붙인다."""
    acc: dict[str, dict] = {}
    notes = []
    for rows in sources:
        if not acc:
            acc = dict(rows)
            continue
        nxt, why = stitch(rows, acc)
        if why:
            notes.append(why)
            continue
        acc = nxt
    return acc, notes


def cache_files(key: str, cache_dir: Path) -> list[Path]:
    """`<key>_<YYYY-MM-DD>.json` 캐시들 — 받은 시각(파일 수정 시각)이 새것부터. 가격 기준은 받은 시각이 정한다."""
    pat = re.compile(rf"^{re.escape(key)}_\d{{4}}-\d{{2}}-\d{{2}}\.json$")
    files = [p for p in cache_dir.glob(f"{key}_*.json") if pat.match(p.name)]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _key(code: str) -> str:
    """strategy_lab.load_bars 와 같은 파일 이름 규칙."""
    return code.replace("^", "IDX_").replace("/", "_").replace(":", "_")


def main(argv: list[str]) -> int:
    cache_dir = _ROOT / "docs_cache" / "lab"
    if argv[:1] == ["--status"]:
        for p in sorted(ARCHIVE_DIR.glob("*.json")):
            rows = json.loads(p.read_text(encoding="utf-8"))
            print(f"{p.stem:20s} {min(rows)} ~ {max(rows)}  {len(rows)}일")
        return 0
    if argv[:1] != ["--seed"] or len(argv) < 2:
        print(__doc__)
        return 2
    for code in argv[1:]:                     # 'ohlc:069500' = lab_classics.load_ohlc 의 고가·저가 이력
        key = "ohlc_" + _key(code[5:]) if code.startswith("ohlc:") else _key(code)
        files = cache_files(key, cache_dir)
        if not files:
            print(f"{key}: 캐시 파일 없음 — 건너뜀")
            continue
        srcs = [json.loads(p.read_text(encoding="utf-8")) for p in files]
        try:
            have = read(key)
        except (OSError, ValueError) as e:
            print(f"{key}: 보관 파일 읽기 실패 — 건너뜀({e})")
            continue
        rows, notes = seed(([have] if have else []) + srcs)     # 있는 보관 = 마지막 실행 때 받은 것(가장 새 기준)
        _write(key, rows)
        print(f"{key}: 캐시 {len(files)}개({', '.join(p.name for p in files)}) → {min(rows)} ~ {max(rows)} "
              f"{len(rows)}일" + (f" · 못 붙임: {' / '.join(notes)}" if notes else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
