"""MCP 서버 공통 포맷터 유틸리티."""

import json
from datetime import datetime
from typing import Any


def format_number(value: float | int, decimals: int = 0) -> str:
    """
    숫자를 한국식으로 포맷팅.

    Args:
        value: 포맷팅할 숫자
        decimals: 소수점 자리수

    Returns:
        포맷팅된 문자열

    """
    formatted = f"{value:,.{decimals}f}" if decimals > 0 else f"{int(value):,}"

    return formatted


def format_currency(value: float | int, symbol: str = "원") -> str:
    """
    통화 포맷팅.

    Args:
        value: 금액
        symbol: 통화 기호

    Returns:
        포맷팅된 문자열

    """
    return f"{format_number(value)} {symbol}"


def format_percentage(value: float, decimals: int = 2, show_sign: bool = True) -> str:
    """
    백분율 포맷팅.

    Args:
        value: 백분율 값 (0.1 = 10%)
        decimals: 소수점 자리수
        show_sign: 부호 표시 여부

    Returns:
        포맷팅된 문자열

    """
    percentage = value * 100

    if show_sign and percentage > 0:
        return f"+{percentage:.{decimals}f}%"
    else:
        return f"{percentage:.{decimals}f}%"


def format_date(date: datetime | str, format: str = "%Y-%m-%d") -> str:
    """
    날짜 포맷팅.

    Args:
        date: 날짜 객체 또는 문자열
        format: 날짜 형식

    Returns:
        포맷팅된 날짜 문자열

    """
    if isinstance(date, str):
        # ISO 형식 파싱 시도
        try:
            date = datetime.fromisoformat(date.replace("Z", "+00:00"))
        except ValueError:
            return date

    return date.strftime(format)


def format_datetime(dt: datetime | str, format: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    날짜시간 포맷팅.

    Args:
        dt: 날짜시간 객체 또는 문자열
        format: 날짜시간 형식

    Returns:
        포맷팅된 날짜시간 문자열

    """
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt

    return dt.strftime(format)


def format_stock_price_change(
    current: float, previous: float, show_ratio: bool = True
) -> dict[str, str]:
    """
    주가 변동 포맷팅.

    Args:
        current: 현재가
        previous: 이전가
        show_ratio: 변동률 표시 여부

    Returns:
        포맷팅된 변동 정보

    """
    change = current - previous
    change_ratio = change / previous if previous != 0 else 0

    result = {
        "current": format_currency(current),
        "change": format_currency(abs(change)),
        "direction": "▲" if change > 0 else "▼" if change < 0 else "-",
    }

    if show_ratio:
        result["change_ratio"] = format_percentage(abs(change_ratio))

    return result


def format_volume(volume: int) -> str:
    """
    거래량 포맷팅.

    Args:
        volume: 거래량

    Returns:
        포맷팅된 거래량 (예: 1.2M, 3.5K)

    """
    if volume >= 1_000_000_000:
        return f"{volume / 1_000_000_000:.1f}B"
    elif volume >= 1_000_000:
        return f"{volume / 1_000_000:.1f}M"
    elif volume >= 1_000:
        return f"{volume / 1_000:.1f}K"
    else:
        return str(volume)


def format_table(
    headers: list[str], rows: list[list[Any]], alignments: list[str] | None = None
) -> str:
    """
    텍스트 테이블 포맷팅.

    Args:
        headers: 헤더 목록
        rows: 데이터 행 목록
        alignments: 정렬 방식 목록 ("left", "center", "right")

    Returns:
        포맷팅된 테이블 문자열

    """
    if not alignments:
        alignments = ["left"] * len(headers)

    # 각 열의 최대 너비 계산
    col_widths = []
    for i, header in enumerate(headers):
        max_width = len(str(header))
        for row in rows:
            if i < len(row):
                max_width = max(max_width, len(str(row[i])))
        col_widths.append(max_width)

    # 구분선 생성
    separator = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    # 헤더 포맷팅
    header_row = "|"
    for i, header in enumerate(headers):
        if alignments[i] == "center":
            header_row += f" {str(header).center(col_widths[i])} |"
        elif alignments[i] == "right":
            header_row += f" {str(header).rjust(col_widths[i])} |"
        else:
            header_row += f" {str(header).ljust(col_widths[i])} |"

    # 테이블 조립
    lines = [separator, header_row, separator]

    # 데이터 행 포맷팅
    for row in rows:
        data_row = "|"
        for i, cell in enumerate(row):
            if i < len(col_widths):
                cell_str = str(cell)
                if alignments[i] == "center":
                    data_row += f" {cell_str.center(col_widths[i])} |"
                elif alignments[i] == "right":
                    data_row += f" {cell_str.rjust(col_widths[i])} |"
                else:
                    data_row += f" {cell_str.ljust(col_widths[i])} |"
        lines.append(data_row)

    lines.append(separator)

    return "\n".join(lines)


def format_json_pretty(data: Any, ensure_ascii: bool = False) -> str:
    """
    JSON을 보기 좋게 포맷팅.

    Args:
        data: JSON으로 변환할 데이터
        ensure_ascii: ASCII로만 인코딩할지 여부

    Returns:
        포맷팅된 JSON 문자열

    """
    return json.dumps(
        data,
        indent=2,
        ensure_ascii=ensure_ascii,
        default=str,  # datetime 등을 문자열로 변환
    )


def format_stock_list(stocks: list[dict], columns: list[str] | None = None) -> str:
    """
    주식 목록을 테이블 형태로 포맷팅.

    Args:
        stocks: 주식 정보 리스트
        columns: 표시할 컬럼 목록

    Returns:
        포맷팅된 테이블 문자열

    """
    if not stocks:
        return "주식 데이터가 없습니다."

    if not columns:
        columns = ["symbol", "name", "price", "change", "change_rate", "volume"]

    headers = []
    for col in columns:
        if col == "symbol":
            headers.append("종목코드")
        elif col == "name":
            headers.append("종목명")
        elif col == "price":
            headers.append("현재가")
        elif col == "change":
            headers.append("전일대비")
        elif col == "change_rate":
            headers.append("등락률")
        elif col == "volume":
            headers.append("거래량")
        else:
            headers.append(col)

    rows = []
    for stock in stocks:
        row = []
        for col in columns:
            value = stock.get(col, "-")

            if col == "price" and isinstance(value, int | float):
                row.append(format_currency(value))
            elif col == "change" and isinstance(value, int | float):
                direction = "▲" if value > 0 else "▼" if value < 0 else "-"
                row.append(f"{direction} {format_currency(abs(value))}")
            elif col == "change_rate" and isinstance(value, int | float):
                row.append(format_percentage(value / 100))
            elif col == "volume" and isinstance(value, int | float):
                row.append(format_volume(int(value)))
            else:
                row.append(str(value))

        rows.append(row)

    alignments = (
        ["center", "left", "right", "right", "right", "right"]
        if len(columns) == 6
        else None
    )
    return format_table(headers, rows, alignments)


def format_technical_analysis_result(analysis: dict) -> str:
    """
    기술적 분석 결과 포맷팅.

    Args:
        analysis: 분석 결과 딕셔너리

    Returns:
        포맷팅된 분석 결과 문자열

    """
    lines = [f"=== {analysis.get('symbol', 'N/A')} 기술적 분석 ==="]
    lines.append(f"분석일시: {format_datetime(analysis.get('timestamp', ''))}")
    lines.append("")

    # 주요 지표
    if "indicators" in analysis:
        lines.append("【주요 지표】")
        indicators = analysis["indicators"]

        for name, data in indicators.items():
            if isinstance(data, dict):
                if "value" in data:
                    value = data["value"]
                    if isinstance(value, int | float):
                        if name.upper() in ["RSI", "STOCH"]:
                            lines.append(f"  {name}: {value:.2f}")
                        else:
                            lines.append(f"  {name}: {format_number(value, 2)}")
                    else:
                        lines.append(f"  {name}: {value}")

                if "signal" in data:
                    signal = data["signal"]
                    signal_symbol = (
                        "" if signal == "SELL" else "🟢" if signal == "BUY" else ""
                    )
                    lines.append(f"    → 신호: {signal_symbol} {signal}")

        lines.append("")

    # 종합 신호
    if "overall_signal" in analysis:
        signal = analysis["overall_signal"]
        confidence = analysis.get("confidence", 0)

        signal_symbol = "" if signal == "SELL" else "🟢" if signal == "BUY" else ""
        lines.append("【종합 신호】")
        lines.append(f"  신호: {signal_symbol} {signal}")
        lines.append(f"  신뢰도: {confidence:.1%}")
        lines.append("")

    # 지지/저항선
    if "support_resistance" in analysis:
        sr = analysis["support_resistance"]
        lines.append("【지지/저항선】")

        if "resistance" in sr:
            lines.append(f"  저항선: {format_currency(sr['resistance'])}")
        if "support" in sr:
            lines.append(f"  지지선: {format_currency(sr['support'])}")

        lines.append("")

    return "\n".join(lines)


def format_market_summary(summary: dict) -> str:
    """
    시장 요약 정보 포맷팅.

    Args:
        summary: 시장 요약 정보

    Returns:
        포맷팅된 시장 요약 문자열

    """
    lines = ["=== 시장 요약 ==="]
    lines.append(f"업데이트: {format_datetime(summary.get('timestamp', ''))}")
    lines.append("")

    # 주요 지수
    if "indices" in summary:
        lines.append("【주요 지수】")
        for index_name, index_data in summary["indices"].items():
            if isinstance(index_data, dict):
                current = index_data.get("current", 0)
                change = index_data.get("change", 0)
                change_rate = index_data.get("change_rate", 0)

                direction = "▲" if change > 0 else "▼" if change < 0 else "-"
                lines.append(
                    f"  {index_name}: {format_number(current, 2)} "
                    f"({direction} {format_number(abs(change), 2)}, "
                    f"{format_percentage(change_rate / 100)})"
                )
        lines.append("")

    # 시장 통계
    if "statistics" in summary:
        stats = summary["statistics"]
        lines.append("【시장 통계】")

        if "advancing" in stats:
            lines.append(f"  상승: {format_number(stats['advancing'])}개")
        if "declining" in stats:
            lines.append(f"  하락: {format_number(stats['declining'])}개")
        if "unchanged" in stats:
            lines.append(f"  보합: {format_number(stats['unchanged'])}개")
        if "total_volume" in stats:
            lines.append(f"  총 거래량: {format_volume(stats['total_volume'])}")
        if "total_amount" in stats:
            lines.append(f"  총 거래대금: {format_currency(stats['total_amount'])}")

        lines.append("")

    return "\n".join(lines)


def format_error_response(error: Exception, context: str | None = None) -> str:
    """
    에러 응답 포맷팅.

    Args:
        error: 에러 객체
        context: 추가 컨텍스트 정보

    Returns:
        포맷팅된 에러 메시지

    """
    error_type = type(error).__name__
    error_message = str(error)

    lines = [" 오류가 발생했습니다"]
    lines.append(f"유형: {error_type}")
    lines.append(f"메시지: {error_message}")

    if context:
        lines.append(f"컨텍스트: {context}")

    lines.append("\n문제가 지속되면 관리자에게 문의하세요.")

    return "\n".join(lines)


def format_data_quality_report(report: dict) -> str:
    """
    데이터 품질 보고서 포맷팅.

    Args:
        report: 데이터 품질 보고서

    Returns:
        포맷팅된 품질 보고서 문자열

    """
    lines = ["=== 데이터 품질 보고서 ==="]
    lines.append(f"검사일시: {format_datetime(report.get('timestamp', ''))}")
    lines.append("")

    # 전체 점수
    if "overall_score" in report:
        score = report["overall_score"]
        score_emoji = "🟢" if score >= 90 else "🟡" if score >= 70 else ""
        lines.append("【전체 품질 점수】")
        lines.append(f"  {score_emoji} {score:.1f}/100")
        lines.append("")

    # 카테고리별 점수
    if "categories" in report:
        lines.append("【카테고리별 점수】")
        for category, score in report["categories"].items():
            score_emoji = "🟢" if score >= 90 else "🟡" if score >= 70 else ""
            lines.append(f"  {category}: {score_emoji} {score:.1f}")
        lines.append("")

    # 이슈
    if report.get("issues"):
        lines.append("【발견된 이슈】")
        for issue in report["issues"]:
            severity = issue.get("severity", "INFO")
            severity_emoji = (
                "" if severity == "ERROR" else "🟡" if severity == "WARNING" else "ℹ️"
            )
            lines.append(f"  {severity_emoji} {issue.get('message', '')}")
        lines.append("")

    return "\n".join(lines)
