"""기준 1 (재료) 점수화 로직 — 순수 함수.

데이터 수집은 호출자(DataCollector 등)가 다른 MCP로 처리.
이 모듈은 입력된 뉴스 제목/공시 제목/설명 텍스트로 점수만 계산.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# 시기별 트렌드 키워드 — 운영 중 갱신 가능
TREND_KEYWORDS: dict[str, list[str]] = {
    "AI/반도체":   ["AI", "인공지능", "HBM", "반도체", "엔비디아", "GPU", "온디바이스", "파운드리"],
    "2차전지":    ["2차전지", "양극재", "음극재", "배터리", "ESS", "전고체"],
    "방산":       ["방산", "K-방산", "수출 계약", "미사일", "무기"],
    "바이오":     ["바이오", "임상", "FDA", "신약", "CMO", "CDMO"],
    "원전/전력":  ["원전", "SMR", "전력", "송전", "재생에너지"],
    "로봇":       ["로봇", "휴머노이드", "협동로봇"],
    "조선":       ["조선", "LNG선", "수주"],
    "양자":       ["양자", "퀀텀"],
}


@dataclass
class CatalystResult:
    has_catalyst: bool
    news_count: int
    disclosure_count: int
    matched_trends: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    score: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_catalyst": self.has_catalyst,
            "news_count": self.news_count,
            "disclosure_count": self.disclosure_count,
            "matched_trends": self.matched_trends,
            "matched_keywords": self.matched_keywords,
            "score": round(self.score, 1),
            "rationale": self.rationale,
        }


def match_trends(texts: list[str]) -> tuple[list[str], list[str]]:
    """텍스트들에서 트렌드 키워드 매칭"""
    blob = " ".join(t for t in texts if t).lower()
    matched_trends: list[str] = []
    matched_keywords: list[str] = []
    for trend, kws in TREND_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in blob:
                if trend not in matched_trends:
                    matched_trends.append(trend)
                if kw not in matched_keywords:
                    matched_keywords.append(kw)
    return matched_trends, matched_keywords


def score_catalyst(
    news_titles: list[str],
    news_descriptions: list[str] | None = None,
    disclosure_titles: list[str] | None = None,
) -> CatalystResult:
    """재료 점수 산정.

    입력은 호출자가 미리 수집한 텍스트만.
      news_titles / news_descriptions: 최근 N일 뉴스
      disclosure_titles: 최근 N일 DART 공시

    배점:
      - 뉴스 N건당 4점, 최대 40점 (10건이면 만점)
      - 공시 1건 이상 +15점
      - 트렌드 매칭 트렌드당 15점, 최대 45점
    """
    news_titles = news_titles or []
    news_descriptions = news_descriptions or []
    disclosure_titles = disclosure_titles or []

    texts = list(news_titles) + list(news_descriptions) + list(disclosure_titles)
    matched_trends, matched_keywords = match_trends(texts)

    news_score = min(40.0, len(news_titles) * 4.0)
    disc_score = 15.0 if disclosure_titles else 0.0
    trend_score = min(45.0, len(matched_trends) * 15.0)
    total = news_score + disc_score + trend_score

    has_catalyst = (
        len(news_titles) >= 2
        or len(disclosure_titles) >= 1
        or len(matched_trends) >= 1
    )

    parts = []
    if news_titles:
        parts.append(f"뉴스 {len(news_titles)}건")
    if disclosure_titles:
        parts.append(f"공시 {len(disclosure_titles)}건")
    if matched_trends:
        parts.append(f"트렌드 {','.join(matched_trends)}")
    if not parts:
        parts.append("재료 없음")

    return CatalystResult(
        has_catalyst=has_catalyst,
        news_count=len(news_titles),
        disclosure_count=len(disclosure_titles),
        matched_trends=matched_trends,
        matched_keywords=matched_keywords,
        score=total,
        rationale=" / ".join(parts),
    )
