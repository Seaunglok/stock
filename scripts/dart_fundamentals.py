"""DART 연간 재무 수집 — 버핏식 후보(우량·저평가)용 시점별 재무 데이터 (2026-10-22).

출력: data/fundamentals/dart_annual.json
  {code: {year: {"avail": "YYYY-MM-DD", "fs": "CFS"|"OFS", "revenue", "op_income",
                 "net_income", "assets", "liabilities", "equity"}}}

시점별(PIT) 원칙
----------------
`avail` 은 **접수번호(rcept_no) 앞 8자리 = 실제 공시일**이다. 백테스트는 그 날짜 **다음 영업일부터만**
이 숫자를 쓸 수 있다(`latest_as_of`). 사업연도 말(12-31) 기준으로 쓰면 3개월 미래 정보가 된다.

연결(CFS) 우선, 없으면 별도(OFS). 금융업(은행·보험)은 계정 체계가 달라 매출액이 비는 경우가 많다 —
전략 쪽에서 금융 업종을 제외한다. 정정공시 반영 여부는 API 가 돌려주는 대로다(최초/정정 구분 없음).

사용:  python scripts/dart_fundamentals.py              # 2014~2025 사업연도, 시점별 풀 350
       python scripts/dart_fundamentals.py --years 2024 2025
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT = _ROOT / "data" / "fundamentals" / "dart_annual.json"
ACCOUNTS = {"매출액": "revenue", "영업이익": "op_income", "당기순이익(손실)": "net_income",
            "자산총계": "assets", "부채총계": "liabilities", "자본총계": "equity"}
BATCH = 50


def _num(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_rows(rows: list[dict]) -> dict[str, dict]:
    """API 행(여러 종목 섞임) → {code: {...}}. 연결 우선, 같은 계정이 여러 행이면 첫 행."""
    by: dict[str, dict[str, dict]] = {}
    for r in rows:
        code = str(r.get("stock_code") or "").strip()
        key = ACCOUNTS.get(str(r.get("account_nm") or "").strip())
        if not code or not key:
            continue
        fs = str(r.get("fs_div") or "")
        slot = by.setdefault(code, {}).setdefault(fs, {})
        if key not in slot:
            v = _num(r.get("thstrm_amount"))
            if v is not None:
                slot[key] = v
        rc = str(r.get("rcept_no") or "")
        if len(rc) >= 8 and "avail" not in slot:
            slot["avail"] = f"{rc[:4]}-{rc[4:6]}-{rc[6:8]}"
    out = {}
    for code, fss in by.items():
        for fs in ("CFS", "OFS"):
            s = fss.get(fs)
            if s and "avail" in s and ("equity" in s or "assets" in s):
                out[code] = {"fs": fs, **s}
                break
    return out


def latest_as_of(fund: dict[str, dict], date: str) -> dict | None:
    """date **이전에 공시된**(avail < date) 가장 최근 사업연도 재무. 공시 당일은 쓰지 않는다
    (장 마감 후 공시가 많아 당일 종가 신호에 쓰면 미래 정보)."""
    best = None
    for year, rec in fund.items():
        if rec.get("avail", "9999") < date and (best is None or year > best[0]):
            best = (year, rec)
    return best[1] if best else None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=list(range(2014, 2026)))
    ap.add_argument("--pool", type=int, default=350)
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    import OpenDartReader
    import requests
    from backtest_dynamic import get_pit_pool
    key = os.getenv("DART_API_KEY")
    dart = OpenDartReader(key)
    # 종목코드 → 고유번호. OpenDartReader.finstate 는 묶음 안에 매핑 안 되는 코드가 하나라도 있으면
    # 묶음 전체를 실패시킨다(2026-10-22 실측: 345 중 ~70 만 수집). 미리 매핑하고 API 를 직접 부른다.
    cc = dart.corp_codes
    cmap = {str(s).strip(): str(c) for s, c in zip(cc["stock_code"], cc["corp_code"]) if str(s).strip()}
    pool = [c for c, _ in get_pit_pool(args.pool) if c.isdigit() and len(c) == 6]
    codes = [c for c in pool if c in cmap]
    missing = sorted(set(pool) - set(codes))
    print(f"풀 {len(pool)} · 고유번호 매핑 {len(codes)} · 미매핑 {len(missing)} {missing[:10]}")

    data: dict = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    url = "https://opendart.fss.or.kr/api/fnlttMultiAcnt.json"
    for year in args.years:
        got = 0
        for k in range(0, len(codes), BATCH):
            chunk = codes[k:k + BATCH]
            rows = []
            for attempt in range(3):
                try:
                    r = requests.get(url, timeout=30, params={
                        "crtfc_key": key, "corp_code": ",".join(cmap[c] for c in chunk),
                        "bsns_year": str(year), "reprt_code": "11011"})
                    j = r.json()
                    if j.get("status") not in ("000", "013"):     # 013 = 조회 데이터 없음
                        raise RuntimeError(f"status {j.get('status')} {j.get('message')}")
                    rows = j.get("list", []) or []
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"  {year} 배치 {k // BATCH} 실패: {str(e)[:80]}")
                    time.sleep(2)
            for code, rec in parse_rows(rows).items():
                data.setdefault(code, {})[str(year)] = rec
                got += 1
            time.sleep(0.3)
        print(f"  {year}: {got}/{len(codes)}종목")
        OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"저장 {OUT} · 종목 {len(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
