"""시장 일지 — 매일 시장 자료를 모은다, 주문과 무관 (2026-11-06, 운용자 결정).

운용자(11-06): "매일 주식 관련 뉴스를 모아 놓는거는 어때? 주식 예측에 도움이 될 자료들을 꾸준히 모았으면 하는데"
→ 결정: 수급 + 뉴스 + 해외·일정 전부 · 텔레그램 아침 요약 + Notion 시장 일지DB 하루 1행 · 요약은 규칙 기반(AI 해설 없음).

왜 모으나: 예측보다 **나중에 다시 못 구하는 기록**. 키움 시장 수급(투자자별·프로그램 매매)은 지나면 다시 받기 어렵고,
'그날 아침에 알 수 있었던 뉴스'는 시점이 흐려진다(11-05 반도체 급락을 S&P500·나스닥만 보고 놓친 일). 이 자료로 전략을
만들 때는 지금처럼 **사전 선언 + 앞으로의 기록**으로만 검증한다.

  morning  평일 08:30(예약작업 MarketJournalMorning) — ① 전 거래일 **확정** 수급(ka10051 종합 지수 투자자별 순매수 KRX·
           대체거래소 · ka90010 프로그램 매매·선물 베이시스)을 그날 파일 close 에 ② 밤사이 해외(S&P500·나스닥·필라델피아
           반도체·VIX·미국 10년물·원/달러) · 밤사이 뉴스(전 거래일 15:30~) · 다가오는 일정 → 오늘 파일 morning
           ③ 텔레그램 아침 요약(전 거래일 확정 수급 포함)
  close    평일 판단 배치(i3_decide.cmd)에서 공격형 리그 뒤 — 오늘 뉴스(08:30~) · DART 주요사항보고 · **잠정** 수급
           (flows_prelim) → 오늘 파일 close. Notion 1행은 i3_notion 파이프라인이 넣는다 — 확정 수급이 들어온 뒤라
           **하루 늦게**(D 의 행은 D+1 15:5x 에).

- 실패해도 실전·리그에 영향 없다. 한 묶음이 실패해도 나머지는 기록하고 errors 에 남긴다.
- 원자료를 그대로 남긴다(뉴스 제목·링크·시각, API 원값 + 단위). 요약은 규칙(키워드별 건수·대표 제목)만.
- 수급 기준·단위(11-06 기사와 대조해 확정): ka10051 금액 = **억원**, 기준은 **KRX**(stex_tp 1 — 보도와 같다, 기관 +1.71조 일치).
  통합(3) = KRX + 대체거래소(2). 15:55 값은 시간외 거래 전 잠정치(외국인 잠정 −2.77조 ↔ 확정 −2.69조)라 확정치는 다음 날
  아침에 받는다. 지난 날짜도 받을 수 있다(2010-01-04 까지 확인). ka90010 금액 = 백만원.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

JOURNAL_DIR = _ROOT / "data" / "market_journal"
CALENDAR_FILE = _ROOT / "scripts" / "market_calendar.json"
KEYWORDS = ("코스피", "반도체", "삼성전자", "SK하이닉스", "외국인 순매도", "환율", "기준금리", "연준", "엔비디아", "관세")
#            ('금리'는 예·적금 상품 기사까지 잡혀 11-06 첫 실행 뒤 '기준금리'로 좁혔다)
OVERSEAS = {"^GSPC": "S&P500", "^IXIC": "나스닥", "^SOX": "필라델피아 반도체", "^VIX": "VIX", "^TNX": "미국 10년물(%)",
            "USD/KRW": "원/달러"}
LEVEL_ONLY = {"^VIX", "^TNX", "USD/KRW"}          # 등락률보다 수준이 의미 있는 것
NEWS_PER_KEYWORD = 100                            # 네이버 검색 API 한 번 최대
NEWS_MAX = 1000                                   # 네이버 검색 API start 상한
NEWS_PAUSE_S = 0.15                               # 호출 사이 간격(초) — 연속 호출은 429 로 끊긴다
NEWS_RETRIES = 3
HEADLINES = 5
CALENDAR_DAYS = 14
MORNING_FROM = "15:30"                            # 밤사이 뉴스 = 전 거래일 장 마감 뒤부터
CLOSE_FROM = "08:30"                              # 오늘 뉴스 = 아침 요약 뒤부터
FLOW_FIELDS = {"외국인": "frgnr_netprps", "기관": "orgn_netprps", "개인": "ind_netprps", "기타법인": "etc_corp_netprps",
               "금융투자": "sc_netprps", "연기금": "endw_netprps"}
WEEKDAY = "월화수목금토일"


# ── 순수 함수 ────────────────────────────────────────────────────────────────
def _num(s) -> float | None:
    """키움 숫자 문자열("+17583", "-505969", "0.60") → float. 비었거나 이상하면 None."""
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def index_flows(rows: list[dict]) -> dict | None:
    """ka10051 inds_netprps → 종합 지수 한 줄. 지수는 cur_prc 절댓값 ÷ 100, 등락률은 flu_rt ÷ 100(%)."""
    row = next((r for r in rows if str(r.get("inds_nm", "")).startswith("종합")), None)
    if row is None:
        return None
    cur, flu = _num(row.get("cur_prc")), _num(row.get("flu_rt"))
    return {"지수": None if cur is None else abs(cur) / 100, "등락(%)": None if flu is None else flu / 100,
            "단위": "억원", **{k: _num(row.get(f)) for k, f in FLOW_FIELDS.items()}}


def program_flows(rows: list[dict], day: str) -> dict | None:
    """ka90010 prm_trde_trnsn 에서 그날(cntr_tm 앞 8자리) 한 줄 — 차익·비차익·전체 순매수(백만원), KOSPI200, 베이시스."""
    key = day.replace("-", "")
    row = next((r for r in rows if str(r.get("cntr_tm", ""))[:8] == key), None)
    if row is None:
        return None
    return {"차익": _num(row.get("dfrt_trde_netprps")), "비차익": _num(row.get("ndiffpro_trde_netprps")),
            "전체": _num(row.get("all_netprps")), "단위": "백만원", "KOSPI200": _num(row.get("kospi200")),
            "베이시스": _num(row.get("basis"))}


def clean(text: str) -> str:
    """네이버 검색 결과의 <b> 태그·HTML 엔티티 제거."""
    return html.unescape(re.sub(r"</?b>", "", text or "")).strip()


def news_in_window(by_kw: dict[str, list[dict]], start: datetime, end: datetime) -> list[dict]:
    """키워드별 검색 결과 → 창 안의 기사만, 링크로 중복 제거(한 기사가 여러 키워드에 걸리면 keywords 에 모은다). 최신순."""
    out: dict[str, dict] = {}
    for kw, items in by_kw.items():
        for it in items:
            try:
                t = parsedate_to_datetime(it.get("pubDate", "")).replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
            if not start <= t < end:
                continue
            link = it.get("originallink") or it.get("link") or ""
            if not link:
                continue
            if link in out:
                if kw not in out[link]["keywords"]:
                    out[link]["keywords"].append(kw)
                continue
            out[link] = {"time": t.strftime("%Y-%m-%d %H:%M"), "title": clean(it.get("title", "")), "link": link,
                         "keywords": [kw]}
    return sorted(out.values(), key=lambda x: x["time"], reverse=True)


def topic_counts(news: list[dict]) -> dict[str, int]:
    """키워드별 기사 수(많은 순) — 그날 무엇이 많이 다뤄졌나."""
    c: dict[str, int] = {}
    for n in news:
        for kw in n["keywords"]:
            c[kw] = c.get(kw, 0) + 1
    return dict(sorted(c.items(), key=lambda x: (-x[1], KEYWORDS.index(x[0]) if x[0] in KEYWORDS else 99)))


def topics_text(topics: dict[str, int], capped: list[str] | None = None, k: int = 6) -> str:
    """'코스피 812+ · 반도체 240' — '+' 는 검색 상한(1,000건)에 걸려 실제보다 적게 센 주제."""
    capped = set(capped or [])
    return " · ".join(f"{kw} {n}{'+' if kw in capped else ''}" for kw, n in list((topics or {}).items())[:k])


def pick_headlines(news: list[dict], k: int = HEADLINES) -> list[dict]:
    """규칙: 기사 수가 많은 주제 순으로, 각 주제에서 **제목에 주제어가 들어간** 가장 최근 기사 하나(없으면 가장 최근 기사).
    같은 제목은 한 번. 검색은 본문까지 맞추므로 '최근 기사'만 고르면 주제와 먼 기사가 뽑힌다(11-06 첫 실행: 비트코인 기사)."""
    seen, out = set(), []
    for kw in topic_counts(news):
        tokens = kw.split()
        cands = [n for n in news if kw in n["keywords"] and n["title"] not in seen]
        best = next((n for n in cands if all(t in n["title"] for t in tokens)), cands[0] if cands else None)
        if best:
            seen.add(best["title"])
            out.append({**best, "topic": kw})
        if len(out) >= k:
            break
    return out


def second_thursday(y: int, m: int) -> date:
    d = date(y, m, 1)
    first_thu = d + timedelta(days=(3 - d.weekday()) % 7)
    return first_thu + timedelta(days=7)


def calendar_events(day: str, manual: list[dict], horizon: int = CALENDAR_DAYS) -> list[dict]:
    """오늘~horizon 일 안의 일정 — 수동 목록(market_calendar.json) + 계산(매월 둘째 목요일 옵션 만기, 3·6·9·12월은 동시만기)."""
    d0 = date.fromisoformat(day)
    d1 = d0 + timedelta(days=horizon)
    ev = [e for e in manual if day <= e["date"] <= d1.isoformat()]
    for y, m in {(d0.year, d0.month), (d1.year, d1.month)}:
        t = second_thursday(y, m)
        if d0 <= t <= d1:
            ev.append({"date": t.isoformat(), "event": "선물옵션 동시만기" if m in (3, 6, 9, 12) else "옵션 만기",
                       "source": "계산(매월 둘째 목요일)"})
    return sorted(ev, key=lambda e: e["date"])


def _signed_jo(v: float | None, unit: str) -> str:
    """억원·백만원 금액 → '−2.64조' / '+1,860억' 같은 짧은 표기."""
    if v is None:
        return "-"
    eok = v if unit == "억원" else v / 100
    return f"{eok / 10000:+.2f}조" if abs(eok) >= 10000 else f"{eok:+,.0f}억"


def overseas_text(ov: dict) -> str:
    parts = []
    for sym, name in OVERSEAS.items():
        x = ov.get(sym)
        if not x:
            continue
        if sym in LEVEL_ONLY:
            parts.append(f"{name} {x['close']:,.2f}" if sym != "USD/KRW" else f"{name} {x['close']:,.0f}")
        else:
            parts.append(f"{name} {x['chg_pct']:+.1f}%")
    return " · ".join(parts)


def flows_text(close: dict | None) -> str:
    if not close:
        return "기록 없음"
    ix, pg = close.get("kospi") or {}, close.get("program") or {}
    if not ix:
        return "수급 조회 실패"
    s = (f"코스피 {ix['지수']:,.0f}({ix['등락(%)']:+.2f}%) · 외국인 {_signed_jo(ix['외국인'], '억원')} · "
         f"기관 {_signed_jo(ix['기관'], '억원')} · 개인 {_signed_jo(ix['개인'], '억원')}")
    if pg:
        s += f" · 프로그램 {_signed_jo(pg['전체'], '백만원')}"
    return s


def morning_summary(day: str, morning: dict, prev_day: str | None, prev_close: dict | None) -> str:
    """텔레그램 아침 요약 — 규칙 기반(해석 없음)."""
    wd = WEEKDAY[date.fromisoformat(day).weekday()]
    us_day = morning.get("overseas_asof") or "-"
    lines = [f"🌅 [시장 일지] {day[5:]}({wd}) 아침"]
    lines.append(f"밤사이 미국({us_day[5:]}): {overseas_text(morning.get('overseas') or {}) or '조회 실패'}")
    if prev_day:
        lines.append(f"전 거래일 한국({prev_day[5:]}): {flows_text(prev_close)}")
    tc = morning.get("topics") or {}
    if tc:
        lines.append("밤사이 뉴스 많은 주제: " + topics_text(tc, morning.get("news_capped"), 5))
    for h in (morning.get("headlines") or [])[:3]:
        lines.append(f"· [{h['topic']}] {h['title']}")
    ev = morning.get("calendar") or []
    if ev:
        lines.append("다가오는 일정: " + " · ".join(f"{e['date'][5:]} {e['event']}" for e in ev[:4]))
    if morning.get("errors"):
        lines.append("⚠️ 조회 실패: " + ", ".join(morning["errors"]))
    return "\n".join(lines)


def _pct_of(ov: dict, sym: str):
    x = (ov or {}).get(sym)
    return None if not x else round(x["chg_pct"], 2)


def _level_of(ov: dict, sym: str):
    x = (ov or {}).get(sym)
    return None if not x else round(x["close"], 2)


def notion_row(day: str, rec: dict) -> dict | None:
    """Notion 시장 일지DB 한 행 — **확정** 수급(close.kospi, 다음 날 아침 fill_final_flows)이 들어온 날만. Notion 쪽은
    '없는 행만 추가'라 잠정치나 반쪽 행을 넣으면 나중에 고쳐지지 않는다(잠정 flows_prelim 은 쓰지 않는다). 확정 수급이
    빠진 날은 다음 아침들이 최근 10거래일을 다시 채운다. 속성 이름은 Notion 줄임말 규칙(「풀네임(줄임말)」)을 따른다.
    값이 없으면 넣지 않는다."""
    close, morning = rec.get("close"), rec.get("morning") or {}
    if not close or not close.get("kospi"):
        return None
    ix, pg = close.get("kospi") or {}, close.get("program") or {}
    ov = morning.get("overseas") or {}
    wd = WEEKDAY[date.fromisoformat(day).weekday()]
    chg = ix.get("등락(%)")
    title = f"{day[5:]}({wd}) 코스피(KOSPI) " + ("-" if chg is None else f"{chg:+.2f}%")
    heads = close.get("headlines") or []
    dart = close.get("dart") or []
    ev = morning.get("calendar") or close.get("calendar") or []
    row = {
        "날짜": title, "일자": day,
        "코스피(KOSPI)": ix.get("지수"), "코스피 등락(%)": chg,
        "외국인 순매수(억원)": ix.get("외국인"), "기관 순매수(억원)": ix.get("기관"), "개인 순매수(억원)": ix.get("개인"),
        "프로그램 순매수(억원)": None if pg.get("전체") is None else round(pg["전체"] / 100),
        "선물 베이시스": pg.get("베이시스"),
        "미국 S&P500(%)": _pct_of(ov, "^GSPC"), "미국 나스닥(%)": _pct_of(ov, "^IXIC"),
        "필라델피아 반도체지수(%)": _pct_of(ov, "^SOX"), "변동성 지수(VIX)": _level_of(ov, "^VIX"),
        "미국 10년물 금리(%)": _level_of(ov, "^TNX"), "원/달러 환율": _level_of(ov, "USD/KRW"),
        "뉴스 많은 주제": topics_text(close.get("topics") or {}, close.get("news_capped")) or None,
        "주요 헤드라인": " / ".join(f"[{h['topic']}] {h['title']}" for h in heads[:HEADLINES]) or None,
        "주요사항 공시": (f"{len(dart)}건 — " + " / ".join(f"{d['corp_name']} {d['report_nm']}" for d in dart[:5]))
        if dart else None,
        "다가오는 일정": " · ".join(f"{e['date'][5:]} {e['event']}" for e in ev[:5]) or None,
    }
    return {k: v for k, v in row.items() if v is not None}


def notion_rows(since: str, journal_dir: Path = JOURNAL_DIR) -> list[dict]:
    out = []
    for p in sorted(journal_dir.glob("????-??-??.json")):
        if p.stem < since:
            continue
        r = notion_row(p.stem, json.loads(p.read_text(encoding="utf-8")))
        if r:
            out.append(r)
    return out


# ── 저장 ─────────────────────────────────────────────────────────────────────
def load_day(day: str, journal_dir: Path = JOURNAL_DIR) -> dict:
    p = journal_dir / f"{day}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"date": day}


def save_section(day: str, section: str, data: dict, journal_dir: Path = JOURNAL_DIR) -> Path:
    """그날 파일의 한 묶음(morning/close)만 바꿔 쓴다 — 하루 두 번 돌아도 다른 묶음은 그대로. 원자적 쓰기."""
    journal_dir.mkdir(parents=True, exist_ok=True)
    rec = load_day(day, journal_dir)
    rec[section] = data
    p = journal_dir / f"{day}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


def update_section(day: str, section: str, patch: dict, journal_dir: Path = JOURNAL_DIR) -> Path:
    """그날 파일의 한 묶음에 키 몇 개만 덧쓴다(나머지 키는 그대로) — 다음 날 아침 확정 수급을 전 거래일 close 에 넣을 때."""
    cur = load_day(day, journal_dir).get(section) or {}
    return save_section(day, section, {**cur, **patch}, journal_dir)


def prev_journal_day(day: str, journal_dir: Path = JOURNAL_DIR) -> str | None:
    days = sorted(p.stem for p in journal_dir.glob("????-??-??.json") if p.stem < day)
    return days[-1] if days else None


def prev_trading_day(day: str, trading_days) -> str | None:
    """day 보다 앞선 마지막 거래일 — 거래소 달력(KODEX200 일봉 날짜)으로. 평일 휴장일을 거래일로 착각하지 않게."""
    ds = [d for d in trading_days if d < day]
    return max(ds) if ds else None


# ── 수집(네트워크) ────────────────────────────────────────────────────────────
def collect_overseas(day: str) -> tuple[dict, str | None]:
    """밤사이 = 한국 날짜 day 보다 앞선 마지막 미국 거래일. 등락은 그 전 거래일 대비."""
    import strategy_lab as L
    start = (date.fromisoformat(day) - timedelta(days=20)).isoformat()
    out, asof = {}, None
    for sym in OVERSEAS:
        b = L.load_bars(sym, start, day)
        ds = [d for d in sorted(b) if d < day]
        if len(ds) < 2:
            continue
        a, z = b[ds[-2]]["close"], b[ds[-1]]["close"]
        out[sym] = {"date": ds[-1], "close": z, "chg_pct": (z / a - 1) * 100}
        if sym == "^GSPC":
            asof = ds[-1]
    return out, asof


def _older_than(items: list[dict], since: datetime) -> bool:
    """이 페이지의 가장 오래된 기사가 창 시작보다 앞선가 — 그러면 더 넘길 필요가 없다."""
    try:
        return parsedate_to_datetime(items[-1].get("pubDate", "")).replace(tzinfo=None) < since
    except (TypeError, ValueError, IndexError):
        return True


async def fetch_news(since: datetime, keywords=KEYWORDS) -> tuple[dict[str, list[dict]], list[str]]:
    """키워드마다 최신순으로 100건씩 넘기며 창 시작(since)에 닿을 때까지 받는다 → (키워드별 기사, 상한에 걸린 키워드).
    한 페이지만 받으면 '코스피'처럼 기사가 많은 주제는 몇 시간 치만 잡힌다. 검색 API 는 1,000건이 상한이라 그래도 창 시작에
    못 닿으면 그 키워드는 '상한 도달'(건수가 잘림)로 남긴다(11-06 '코스피'는 하루 1,000건을 넘었다).
    호출 사이 간격 + 429(속도 제한)면 쉬었다 다시 — 11-06 첫 실행이 연속 호출로 실패했다."""
    import httpx
    cid, sec = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if not cid or not sec:
        raise RuntimeError("NAVER_CLIENT_ID/SECRET 없음")
    out, capped = {}, []
    async with httpx.AsyncClient(timeout=15) as c:
        for kw in keywords:
            items: list[dict] = []
            reached = False
            for start in range(1, NEWS_MAX + 1, NEWS_PER_KEYWORD):
                for attempt in range(NEWS_RETRIES):
                    await asyncio.sleep(NEWS_PAUSE_S * (1 + 4 * attempt))
                    r = await c.get("https://openapi.naver.com/v1/search/news.json",
                                    params={"query": kw, "display": NEWS_PER_KEYWORD, "start": start, "sort": "date"},
                                    headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec})
                    if r.status_code != 429:
                        break
                r.raise_for_status()
                page = r.json().get("items", [])
                items += page
                if len(page) < NEWS_PER_KEYWORD or _older_than(page, since):
                    reached = True
                    break
            if not reached:
                capped.append(kw)
            out[kw] = items
    return out, capped


async def fetch_dart(day: str) -> list[dict]:
    """OpenDART 주요사항보고(pblntf_ty=B) · 유가증권(corp_cls=Y) — 그날 접수분."""
    import httpx
    key = os.getenv("DART_API_KEY")
    if not key:
        raise RuntimeError("DART_API_KEY 없음")
    d = day.replace("-", "")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://opendart.fss.or.kr/api/list.json",
                        params={"crtfc_key": key, "bgn_de": d, "end_de": d, "pblntf_ty": "B", "corp_cls": "Y",
                                "page_count": 100})
        r.raise_for_status()
        j = r.json()
    if j.get("status") == "013":                 # 조회된 데이터 없음
        return []
    if j.get("status") != "000":
        raise RuntimeError(f"DART {j.get('status')} {j.get('message')}")
    return [{"corp_name": x.get("corp_name"), "stock_code": x.get("stock_code"), "report_nm": (x.get("report_nm") or "").strip(),
             "rcept_no": x.get("rcept_no")} for x in j.get("list", [])]


async def fetch_flows(day: str) -> dict:
    """키움 직접 호출(조회만) — 그날(base_dt) 종합 지수 투자자별 순매수(ka10051)와 프로그램 매매(ka90010).
    kospi·kosdaq = **KRX**(stex_tp 1 — 보도와 같은 기준), kospi_nxt = 대체거래소(2). 통합(3) = 둘의 합이라 따로 받지 않는다.
    지난 날짜도 확정치를 준다(2010-01-04 까지 확인, 11-06)."""
    from src.mcp_servers.kiwoom_mcp.common.client.kiwoom_restapi_client import KiwoomRESTAPIClient
    c = KiwoomRESTAPIClient()
    d = day.replace("-", "")

    async def ix(mrkt: str, stex: str):
        r = await c.call_api("ka10051", {"mrkt_tp": mrkt, "amt_qty_tp": "0", "base_dt": d, "stex_tp": stex})
        return index_flows(r.get("inds_netprps") or [])
    try:
        out = {"kospi": await ix("0", "1"), "kospi_nxt": await ix("0", "2"), "kosdaq": await ix("1", "1")}
        pg = await c.call_api("ka90010", {"date": d, "amt_qty_tp": "1", "mrkt_tp": "P00101", "min_tic_tp": "0",
                                          "stex_tp": "1"})
        out["program"] = program_flows(pg.get("prm_trde_trnsn") or [], day)
    finally:
        if hasattr(c, "close"):
            await c.close()
    return out


def _err(e: Exception) -> str:
    """실패 이름표 — HTTP 오류면 상태 코드까지(11-06 '뉴스(HTTPStatusError)'만으론 원인을 몰랐다)."""
    code = getattr(getattr(e, "response", None), "status_code", None)
    return f"{type(e).__name__} {code}" if code else type(e).__name__


def _manual_calendar() -> list[dict]:
    return json.loads(CALENDAR_FILE.read_text(encoding="utf-8")) if CALENDAR_FILE.exists() else []


def morning_since(day: str, prev: str | None) -> datetime:
    """밤사이 뉴스 창의 시작 = 직전 기록일(없으면 어제) 장 마감 — 월요일 아침이면 금요일 15:30 부터(주말 포함)."""
    base = prev or (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    return datetime.fromisoformat(f"{base} {MORNING_FROM}")


def _trading_days(day: str) -> list[str]:
    """거래소 달력 — KODEX200 일봉 날짜(FDR). 아침엔 오늘 봉이 없다."""
    import strategy_lab as L
    return sorted(L.load_bars("069500", (date.fromisoformat(day) - timedelta(days=40)).isoformat(), day))


def _ks_window(day: str) -> dict[str, float]:
    """날짜 대조용 FDR ^KS11 종가(최근 40일) — market_flows 의 가드와 같은 기준."""
    import market_flows as MF
    return MF.ks_closes((date.fromisoformat(day) - timedelta(days=40)).isoformat(), day)


async def fill_final_flows(day: str, now: datetime, journal_dir: Path = JOURNAL_DIR,
                           flows_file: Path | None = None) -> tuple[str | None, list[str]]:
    """전 거래일 확정 수급을 그날 파일의 close 에 넣는다 + 최근 10거래일 중 **일지 파일이 있는데** 확정 수급이 빠진 날도
    다시 채운다(하루 실패해도 다음 아침이 메운다 — Notion 행은 확정 수급이 들어온 뒤에 생긴다). 받은 날은 연구용 이력
    data/market_flows/daily.csv 에도 한 줄(날짜 대조 가드 포함, market_flows). → (전 거래일, 실패 목록)."""
    import market_flows as MF
    tds = _trading_days(day)
    prev = prev_trading_day(day, tds)
    targets = [d for d in tds if d < day][-10:]
    targets = [d for d in targets if d == prev or ((journal_dir / f"{d}.json").exists()
                                                   and not (load_day(d, journal_dir).get("close") or {}).get("kospi"))]
    errors = []
    try:
        ks = _ks_window(day)
    except Exception as e:  # noqa: BLE001 — 대조값이 없으면 check='unchecked' 로 남긴다
        ks = {}
        errors.append(f"대조 종가({_err(e)})")
    for d in targets:
        try:
            flows = await fetch_flows(d)
            if not flows.get("kospi"):
                errors.append(f"확정 수급 {d[5:]}(종합 행 없음)")
                continue
            stamp = now.isoformat(timespec="seconds")
            update_section(d, "close", {**flows, "flows_final_at": stamp}, journal_dir)
            row = MF.row_from(d, flows.get("kospi"), flows.get("kosdaq"), flows.get("program"), ks.get(d), stamp)
            MF.upsert([row], flows_file or MF.FLOWS_FILE)
            if row["check"] not in ("ok", "unchecked"):
                errors.append(f"확정 수급 {d[5:]} 날짜 대조 {row['check']}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"확정 수급 {d[5:]}({_err(e)})")
    return prev, errors


async def run_morning(now: datetime, notify: bool = True) -> dict:
    day = now.strftime("%Y-%m-%d")
    rec, errors = {"collected_at": now.isoformat(timespec="seconds")}, []
    try:
        prev, ferr = await fill_final_flows(day, now)
        errors += ferr
    except Exception as e:  # noqa: BLE001 — 거래소 달력 조회 실패
        prev = prev_journal_day(day)
        errors.append(f"확정 수급({_err(e)})")
    try:
        rec["overseas"], rec["overseas_asof"] = collect_overseas(day)
    except Exception as e:  # noqa: BLE001 — 한 묶음 실패가 나머지를 막지 않게
        errors.append(f"해외({type(e).__name__})")
    try:
        start = morning_since(day, prev)
        by_kw, capped = await fetch_news(start)
        news = news_in_window(by_kw, start, now)
        rec.update(news=news, topics=topic_counts(news), headlines=pick_headlines(news), news_capped=capped,
                   news_window=[str(start), str(now)])
    except Exception as e:  # noqa: BLE001
        errors.append(f"뉴스({_err(e)})")
    rec["calendar"] = calendar_events(day, _manual_calendar())
    rec["errors"] = errors
    save_section(day, "morning", rec)
    text = morning_summary(day, rec, prev, (load_day(prev).get("close") if prev else None))
    print(text)
    if notify:
        from ops_base import notify as tg
        await tg(text)
    return rec


async def run_close(now: datetime, notify: bool = True) -> dict:
    """장 마감 직후 — 뉴스·공시 + **잠정** 수급(flows_prelim). 확정 수급(kospi 등)은 다음 날 아침 fill_final_flows 가 넣는다
    (15:55 값은 시간외 거래 전 잠정치 — 11-06 외국인 잠정 −2.77조 ↔ 확정 −2.69조)."""
    day = now.strftime("%Y-%m-%d")
    rec, errors = {"collected_at": now.isoformat(timespec="seconds")}, []
    try:
        rec["flows_prelim"] = await fetch_flows(day)
    except Exception as e:  # noqa: BLE001
        errors.append(f"잠정 수급({_err(e)})")
    try:
        start = datetime.fromisoformat(f"{day} {CLOSE_FROM}")
        by_kw, capped = await fetch_news(start)
        news = news_in_window(by_kw, start, now)
        rec.update(news=news, topics=topic_counts(news), headlines=pick_headlines(news), news_capped=capped,
                   news_window=[str(start), str(now)])
    except Exception as e:  # noqa: BLE001
        errors.append(f"뉴스({_err(e)})")
    try:
        rec["dart"] = await fetch_dart(day)
    except Exception as e:  # noqa: BLE001
        errors.append(f"공시({_err(e)})")
    rec["calendar"] = calendar_events(day, _manual_calendar())
    rec["errors"] = errors
    p = update_section(day, "close", rec)            # 덧쓰기 — 다음 날 아침에 넣은 확정 수급을 지우지 않는다
    print(f"[market_journal close] {day} 잠정 {flows_text(rec.get('flows_prelim'))} · 뉴스 {len(rec.get('news', []))}건 · "
          f"공시 {len(rec.get('dart', []))}건 · 실패 {errors or '없음'} → {p}")
    if errors and notify:
        from ops_base import notify as tg
        await tg(f"⚠️ [시장 일지] {day} 장 마감 조회 실패: {', '.join(errors)}")
    return rec


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=("morning", "close"), required=True)
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    now = datetime.now()
    if now.weekday() >= 5:
        print(json.dumps({"skip": "주말"}, ensure_ascii=False))
        return 0
    if args.phase == "morning":
        asyncio.run(run_morning(now, notify=not args.no_notify))
    else:
        asyncio.run(run_close(now, notify=not args.no_notify))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
