"""DART 공시 리스트 종목별 디스크 캐시.

OpenDartReader 의 list(code, start, end) 결과를 JSON 으로 저장.
회귀·백테스트에서 매번 API 호출 없이 로딩하기 위함.

사용:
  from scripts._dart_cache import load_disclosures
  records = load_disclosures("005930", "2025-01-01", "2026-04-30")
  # records: list[{"date":"2026-04-30","report_nm":"...","rcept_no":"..."}]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CACHE_DIR = PROJECT_ROOT / "docs_cache" / "dart"

_dart = None


def _client():
    global _dart
    if _dart is None:
        from dotenv import load_dotenv
        load_dotenv()
        import OpenDartReader
        key = os.getenv("DART_API_KEY")
        if not key:
            raise RuntimeError("DART_API_KEY 미설정")
        _dart = OpenDartReader(key)
    return _dart


def _cache_path(code: str, start: str, end: str) -> Path:
    return CACHE_DIR / f"{code}_{start}_{end}.json"


def load_disclosures(code: str, start: str, end: str) -> list[dict[str, Any]]:
    """종목별 공시 리스트. 캐시 우선, 없으면 fetch.

    Returns: [{"date": "YYYY-MM-DD", "report_nm": str, "rcept_no": str}]
    """
    path = _cache_path(code, start, end)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    df = _client().list(code, start, end)
    if df is None or len(df) == 0:
        out: list[dict[str, Any]] = []
    else:
        out = []
        for _, row in df.iterrows():
            dt = str(row.get("rcept_dt", ""))
            if len(dt) != 8 or not dt.isdigit():
                continue
            out.append({
                "date": f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}",
                "report_nm": str(row.get("report_nm", "")),
                "rcept_no": str(row.get("rcept_no", "")),
            })

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
