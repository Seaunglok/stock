"""파일 원자적 쓰기 — 한 곳에서 (2026-11-18, 미뤄 둔 정리 · 운용자 "결함 수정 및 미뤄둔 정리 진행해줘").

왜
--
  12곳(I3 상태·리그·공격형 리그·분봉·일지·수급 이력·지표 일지·Notion 준비·연결 점검·연구 캐시)이 같은 세 줄
  (`<이름>.tmp` 쓰기 → 교체)을 따로 갖고 있었다. 그중 I3 상태(`i3_live.save_state`)는 **기존 파일을 먼저 .bak 으로 옮긴 뒤**
  새 파일을 넣었다 — 두 번째 교체가 실패하면(Windows 에서 백신·색인이 새 파일을 잠깐 잡으면 PermissionError) state.json 이
  없는 채로 남고, 다음 `load_state` 는 그것을 빈 상태 {} 로 받아 처음부터 시작했다(성과 지수·낙폭 예산 최고치·대기 판단 유실).
  실패한 쓰기는 반쯤 쓴 .tmp 도 남겼다.

무엇
----
  · `write_text(path, text, keep_bak=False)` — 같은 폴더 `<이름>.tmp` 에 쓰고 `os.replace` 로 바꾼다(같은 볼륨 원자적 교체).
    keep_bak=True 면 직전 본을 `<이름>.bak` 으로 **복사**한 뒤 바꾼다 — 대상 파일이 없는 순간이 없다.
  · `write_csv(path, cols, rows)` — csv.DictWriter(extrasaction="ignore") 그대로 tmp 에 쓰고 같은 방식으로 바꾼다.
  · 교체가 PermissionError 면 REPLACE_RETRIES 번 RETRY_GAP_S 쉬며 다시 — 그래도 안 되면 예외(조용히 넘어가지 않는다).
  · 어떤 단계에서 실패해도 원본은 그대로, .tmp 는 지우고, 예외는 그대로 위로 — 호출자 동작(배치 실패 알림)은 전과 같다.
  · 내용(직렬화)은 호출자가 만든 문자열 그대로 쓴다 — 바꾸기 전과 바이트가 같다(json 들여쓰기·ensure_ascii 는 호출자 몫).

`trend_runtime.save_state` 는 손상 복구 규칙(.bak 로 되돌림 · 손상 파일을 덮어쓰지 않음)까지 따로 시험되는 종료 트랙 기반이라
여기로 옮기지 않았다.
"""
from __future__ import annotations

import csv
import os
import shutil
import time
from pathlib import Path
from typing import Iterable

REPLACE_RETRIES = 5
RETRY_GAP_S = 0.2


def tmp_of(path: Path) -> Path:
    return path.with_suffix(".tmp")


def bak_of(path: Path) -> Path:
    return path.with_suffix(".bak")


def _replace(src: Path, dst: Path, sleep=None) -> None:
    for k in range(REPLACE_RETRIES + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if k == REPLACE_RETRIES:
                raise
            (sleep or time.sleep)(RETRY_GAP_S)


def _discard(tmp: Path) -> None:
    try:
        tmp.unlink()
    except OSError:
        pass


def _commit(path: Path, tmp: Path, keep_bak: bool) -> None:
    if keep_bak and path.exists():
        shutil.copy2(path, bak_of(path))
    _replace(tmp, path)


def write_text(path: Path | str, text: str, keep_bak: bool = False) -> None:
    """text 를 path 에 원자적으로(utf-8). 실패하면 원본 그대로 · tmp 지움 · 예외."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_of(path)
    try:
        tmp.write_text(text, encoding="utf-8")
        _commit(path, tmp, keep_bak)
    except BaseException:
        _discard(tmp)
        raise


def write_csv(path: Path | str, cols: list[str], rows: Iterable[dict], keep_bak: bool = False) -> None:
    """머리줄 cols + rows(없는 열은 빈칸, 남는 열은 버림)를 path 에 원자적으로(utf-8, newline="")."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_of(path)
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        _commit(path, tmp, keep_bak)
    except BaseException:
        _discard(tmp)
        raise
