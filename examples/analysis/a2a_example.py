#!/usr/bin/env python3
"""
Analysis Agent - A2A 프로토콜 호출 예제

A2A 프로토콜을 통해 Analysis Agent와 통신하는 예제입니다.
주식 데이터에 대한 통합 분석(기술적, 기본적, 거시경제, 감성분석)을 수행합니다.

실행 전제 조건:
1. MCP 서버들이 실행 중이어야 함 (./1-run-all-services.sh)
2. Analysis A2A 서버가 Docker compose로 실행되어 있어야 함
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.a2a_integration.a2a_lg_client_utils_v2 import A2AClientManagerV2


def print_section(title: str):
    """섹션 구분선 출력"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ============== Analysis Agent 통합 테스트 기능 추가 ==============

class AnalysisIntegrationTestResult:
    """Analysis Agent 통합 테스트 결과 저장 클래스"""
    def __init__(self):
        self.test_cases: List[Dict[str, Any]] = []
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.start_time = None
        self.end_time = None
        
    def add_test_result(self, test_name: str, success: bool, details: Dict[str, Any]):
        """테스트 결과 추가"""
        self.test_cases.append({
            "test_name": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat()
        })
        self.total_tests += 1
        if success:
            self.passed_tests += 1
        else:
            self.failed_tests += 1
    
    def generate_report(self) -> str:
        """테스트 보고서 생성"""
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        
        report = f"""
🧪 AnalysisAgent A2A 통합 테스트 보고서
{'='*50}
 테스트 결과: {self.passed_tests}/{self.total_tests} 성공
⏱️  실행 시간: {duration:.2f}초
 실행 시간: {self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}

 상세 결과:
"""
        for test_case in self.test_cases:
            status = " 성공" if test_case["success"] else " 실패"
            report += f"   {status} - {test_case['test_name']}\n"
            if not test_case["success"] and "error" in test_case["details"]:
                report += f"     오류: {test_case['details']['error']}\n"
        
        return report


def validate_analysis_output(response: Dict[str, Any], expected_agent_type: str = "analysis") -> Dict[str, Any]:
    """Analysis Agent A2AOutput 검증 (Category-based signal 포함)"""
    validation_result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "found_fields": [],
        "category_signals_found": []
    }
    
    # 기본 A2AOutput 필드 확인
    required_fields = ["agent_type", "status"]
    for field in required_fields:
        if field in response:
            validation_result["found_fields"].append(field)
        else:
            validation_result["valid"] = False
            validation_result["errors"].append(f"필수 필드 '{field}' 누락")
    
    # agent_type 검증
    if "agent_type" in response:
        actual_agent_type = response.get("agent_type")
        if actual_agent_type != expected_agent_type:
            validation_result["warnings"].append(
                f"예상 agent_type: '{expected_agent_type}', 실제: '{actual_agent_type}'"
            )
    
    # Category-based signal 검증 (Analysis Agent 특화)
    valid_signals = ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]
    
    # data_content나 text_content에서 카테고리 신호 검색
    content_to_check = []
    if "data_content" in response:
        content_to_check.append(json.dumps(response["data_content"]) if isinstance(response["data_content"], dict) else str(response["data_content"]))
    if "text_content" in response:
        content_to_check.append(response["text_content"])
    
    for content in content_to_check:
        for signal in valid_signals:
            if signal in content:
                validation_result["category_signals_found"].append(signal)
    
    # Category signal 검증
    if validation_result["category_signals_found"]:
        print(f"     발견된 카테고리 신호: {', '.join(validation_result['category_signals_found'])}")
    else:
        validation_result["warnings"].append("Category-based 투자 신호를 찾을 수 없습니다")
    
    # 4차원 분석 검증 (기술적, 기본적, 거시경제, 감성)
    analysis_dimensions = ["technical", "fundamental", "macro", "sentiment"]
    found_dimensions = []
    
    for content in content_to_check:
        for dimension in analysis_dimensions:
            if dimension in content.lower():
                found_dimensions.append(dimension)
    
    if found_dimensions:
        validation_result["found_dimensions"] = list(set(found_dimensions))
        print(f"     발견된 분석 차원: {', '.join(found_dimensions)}")
    
    return validation_result


async def test_category_signal_consistency(
    symbols: List[str],
    collected_data: Dict[str, Any],
    user_question: str,
    analysis_url: str = "http://localhost:8002"
) -> Dict[str, Any]:
    """Category-based signal 일관성 테스트"""
    
    input_data = {
        "symbols": symbols,
        "collected_data": collected_data,
        "user_question": user_question,
    }
    
    test_results = []
    signals_found = []
    
    print("   Category-based Signal 일관성 테스트 (5회 실행)...")
    
    for i in range(5):
        print(f"     테스트 실행 {i+1}/5...")
        try:
            async with A2AClientManagerV2(base_url=analysis_url) as client_manager:
                response = await client_manager.send_data_with_full_messages(input_data)
                
            # 응답에서 신호 추출
            if isinstance(response, list) and response:
                final_response = response[-1]
            else:
                final_response = response
            
            validation = validate_analysis_output(final_response, "analysis")
            signals_in_response = validation.get("category_signals_found", [])
            
            test_results.append({
                "run": i+1,
                "success": len(signals_in_response) > 0,
                "signals": signals_in_response,
                "validation": validation
            })
            
            signals_found.extend(signals_in_response)
            
        except Exception as e:
            test_results.append({
                "run": i+1,
                "success": False,
                "error": str(e)
            })
    
    # 일관성 분석
    successful_runs = [r for r in test_results if r["success"]]
    consistency_analysis = {
        "total_runs": 5,
        "successful_runs": len(successful_runs),
        "all_signals_found": list(set(signals_found)),
        "signal_frequency": {},
        "consistency_score": 0
    }
    
    # 신호 빈도 계산
    for signal in signals_found:
        consistency_analysis["signal_frequency"][signal] = signals_found.count(signal)
    
    # 일관성 점수 (가장 빈번한 신호의 빈도 / 총 성공 실행 수)
    if successful_runs:
        max_frequency = max(consistency_analysis["signal_frequency"].values()) if consistency_analysis["signal_frequency"] else 0
        consistency_analysis["consistency_score"] = max_frequency / len(successful_runs)
    
    print(f"     일관성 분석 완료: {len(successful_runs)}/5 성공")
    print(f"     주요 신호: {consistency_analysis['all_signals_found']}")
    print(f"     일관성 점수: {consistency_analysis['consistency_score']:.2f}")
    
    return {
        "test_results": test_results,
        "consistency_analysis": consistency_analysis
    }


async def test_four_dimension_analysis(
    symbols: List[str],
    collected_data: Dict[str, Any],
    user_question: str,
    analysis_url: str = "http://localhost:8002"
) -> Dict[str, Any]:
    """4차원 분석 검증 테스트 (기술적, 기본적, 거시경제, 감성)"""
    
    input_data = {
        "symbols": symbols,
        "collected_data": collected_data,
        "user_question": "종합적인 4차원 분석을 수행해주세요.",
    }
    
    print("   4차원 분석 검증 테스트...")
    
    try:
        async with A2AClientManagerV2(base_url=analysis_url) as client_manager:
            response = await client_manager.send_data_with_full_messages(input_data)
        
        # 응답에서 4차원 분석 검증
        if isinstance(response, list) and response:
            final_response = response[-1]
        else:
            final_response = response
            
        content_to_analyze = ""
        if "data_content" in final_response:
            content_to_analyze += json.dumps(final_response["data_content"]) if isinstance(final_response["data_content"], dict) else str(final_response["data_content"])
        if "text_content" in final_response:
            content_to_analyze += final_response["text_content"]
        
        # 4차원 키워드 검증
        dimension_keywords = {
            "technical": ["기술적", "차트", "RSI", "MACD", "볼린저", "이동평균", "technical"],
            "fundamental": ["기본적", "PER", "PBR", "ROE", "재무", "매출", "이익", "fundamental"],
            "macro": ["거시경제", "금리", "환율", "GDP", "인플레이션", "macro"],
            "sentiment": ["감성", "투자심리", "뉴스", "시장분위기", "sentiment"]
        }
        
        found_dimensions = {}
        for dimension, keywords in dimension_keywords.items():
            found_keywords = [kw for kw in keywords if kw.lower() in content_to_analyze.lower()]
            found_dimensions[dimension] = {
                "found": len(found_keywords) > 0,
                "keywords_found": found_keywords,
                "keyword_count": len(found_keywords)
            }
        
        # 결과 분석
        dimensions_covered = sum(1 for d in found_dimensions.values() if d["found"])
        coverage_score = dimensions_covered / 4
        
        print(f"     4차원 분석 커버리지: {dimensions_covered}/4 ({coverage_score*100:.1f}%)")
        for dimension, info in found_dimensions.items():
            status = "" if info["found"] else ""
            keywords = info["keywords_found"][:3]  # 처음 3개만 표시
            print(f"    {status} {dimension}: {', '.join(keywords) if keywords else '미발견'}")
        
        return {
            "success": dimensions_covered >= 2,  # 최소 2차원 이상 분석이 있어야 성공
            "dimensions_covered": dimensions_covered,
            "coverage_score": coverage_score,
            "dimension_details": found_dimensions,
            "response": final_response
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


async def check_a2a_server() -> bool:
    """A2A 서버 상태 확인"""
    import httpx
    
    # Agent Card 엔드포인트로 서버 상태 확인
    server_url = "http://localhost:8002/.well-known/agent-card.json"
    
    print_section("A2A 서버 상태 확인")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(server_url, timeout=2.0)
            if response.status_code == 200:
                print(f" Analysis A2A 서버: 정상 작동")
                return True
            else:
                print(f"️ Analysis A2A 서버: 응답 이상 (status: {response.status_code})")
                return False
        except Exception as e:
            print(f" Analysis A2A 서버: 연결 실패")
            print(f"   오류: {str(e)[:100]}")
            print("\n 해결 방법:")
            print("   1. 터미널에서 다음 명령 실행:")
            print("      docker-compose -f docker/a2a_agents/docker-compose.yml up analysis-agent")
            print("   2. 서버가 포트 8002에서 실행 중인지 확인")
            return False


async def call_analysis_via_a2a(
    symbols: list,
    collected_data: dict,
    user_question: str
) -> Dict[str, Any]:
    """A2A 프로토콜을 통해 Analysis Agent 호출"""
    
    # Analysis A2A 서버 URL (도커 컨테이너 포트)
    analysis_url = "http://localhost:8002"
    
    # 입력 데이터 준비
    input_data = {
        "symbols": symbols,
        "collected_data": collected_data,
        "user_question": user_question,
    }
    
    print("\n 분석 요청 전송:")
    print(f"   - 종목: {symbols}")
    print(f"   - 수집된 데이터: {list(collected_data.keys())}")
    print(f"   - 질문: {user_question}")

    # A2A 클라이언트 매니저 사용 (async with 패턴)
    async with A2AClientManagerV2(base_url=analysis_url) as client_manager:
        try:
            # JSON 문자열로 변환
            # 전체 메시지 히스토리를 포함한 A2A 호출 실행
            response_data = await client_manager.send_data_with_full_messages(input_data)
            
            # 응답이 리스트인 경우 마지막 항목을 결과로 사용
            if isinstance(response_data, list) and response_data:
                return response_data[-1]  # 최종 결과
            else:
                return response_data
                
        except Exception as e:
            print(f" A2A 호출 실패: {str(e)}")
            raise


def parse_analysis_response(response_text: str):
    """Analysis Agent 응답 파싱 및 출력"""
    
    print("\n Agent 응답:")
    print("-" * 50)
    
    # 응답을 섹션별로 분리하여 표시
    lines = response_text.split("\n")
    current_section = None
    
    for line in lines[:30]:  # 처음 30줄만 표시
        line = line.strip()
        if not line:
            continue
            
        # 섹션 헤더 감지
        if line.startswith("") or line.startswith("") or line.startswith(""):
            current_section = line
            print(f"\n{line}")
        elif line.startswith("-") and current_section:
            print(f"  {line}")
        else:
            print(f"  {line}")
    
    if len(lines) > 30:
        print("\n  ... (더 많은 내용은 JSON 파일 참조)")


def format_analysis_result(result: Dict[str, Any]):
    """분석 결과 포맷팅 및 출력 (Analysis Agent 전용 구조)"""

    # A2AOutput 표준 구조 처리 (text_content, data_content 우선 확인)
    text_content = result.get("text_content")
    data_content = result.get("data_content")
    # 루트에 status/final이 있으면 우선 신뢰
    status = result.get("status")
    final = result.get("final")

    # JSON으로 요약 구조화 출력 헬퍼
    def print_structured_summary(dc: Dict[str, Any]):
        summary = dc.get("result", {}) if isinstance(dc, dict) else {}
        signal = summary.get("analysis_signal")
        tech = summary.get("technical_score")
        fund = summary.get("fundamental_score")
        senti = summary.get("sentiment_score")
        macro = summary.get("macro_score")
        comp = summary.get("composite_score")
        conf = summary.get("confidence_level")
        print("\n 요약(구조화 데이터):")
        print(f"  - Signal: {signal}")
        print(f"  - Scores: technical={tech}, fundamental={fund}, sentiment={senti}, macro={macro}")
        print(f"  - Composite: {comp}, Confidence: {conf}")

    # text_content가 있으면 이를 우선 사용
    if text_content and text_content.strip():
        print(" 주식 데이터 통합 분석 완료!")
        print("\n Agent 응답:")
        print("-" * 50)

        # 분석 내용을 줄 단위로 출력
        lines = text_content.split("\n")
        for line in lines[:30]:
            if line.strip():
                print(f"  {line}")

        if len(lines) > 30:
            print("\n  ... (더 많은 내용은 JSON 파일 참조)")

        # 메타데이터 (A2AOutput 표준)
        metadata = result.get("metadata", {})
        print("\n 메타데이터:")
        print(f"  - Agent 타입: {result.get('agent_type', 'AnalysisA2AAgent')}")
        print(f"  - 최종 신호: {metadata.get('final_signal', 'N/A')}")
        print(f"  - 신뢰도: {metadata.get('confidence', 'N/A')}")
        print(f"  - 실행 상태: {metadata.get('execution_complete', 'N/A')}")

        # 구조화 요약 추가
        if data_content:
            print_structured_summary(data_content)

        return

    # data_content에서 분석 내용 추출 시도 (루트가 비어 있을 때)
    if data_content and isinstance(data_content, dict):
        # data_content.result.raw_analysis에서 분석 내용 추출
        raw_analysis = None
        if data_content.get("result", {}).get("raw_analysis"):
            raw_analysis = data_content["result"]["raw_analysis"]

        if raw_analysis and raw_analysis.strip():
            print(" 주식 데이터 통합 분석 완료! (Data Content)")
            print("\n Agent 응답:")
            print("-" * 50)

            # 분석 내용을 줄 단위로 출력
            lines = raw_analysis.split("\n")
            for line in lines[:30]:
                if line.strip():
                    print(f"  {line}")

            if len(lines) > 30:
                print("\n  ... (더 많은 내용은 JSON 파일 참조)")

            # 메타데이터
            metadata = result.get("metadata", {})
            print("\n 메타데이터:")
            print(f"  - Agent 타입: {result.get('agent_type', 'AnalysisA2AAgent')}")
            print(f"  - 최종 신호: {metadata.get('final_signal', data_content.get('result', {}).get('analysis_signal', 'N/A'))}")
            print(f"  - 신뢰도: {metadata.get('confidence', 'N/A')}")
            print(f"  - 실행 상태: {metadata.get('execution_complete', 'N/A')} / status={status} final={final}")

            print_structured_summary(data_content)

            return

    # A2A Analysis Agent 결과 구조 처리 (data_parts 백업)
    if "data_parts" in result:
        data_parts = result.get("data_parts", [])
        if data_parts and isinstance(data_parts, list) and len(data_parts) > 0:
            # 첫 번째 DataPart에서 분석 결과 추출 (직접/raw 경로 모두 시도)
            first_data_part = data_parts[0]
            # 1) raw 경로
            raw = first_data_part.get("result", {}).get("raw_analysis")
            if raw and isinstance(raw, str) and raw.strip():
                print(" 주식 데이터 통합 분석 완료! (DataPart)")
                print("\n Agent 응답:")
                print("-" * 50)
                for line in raw.split("\n")[:30]:
                    if line.strip():
                        print(f"  {line}")
                meta = result.get("metadata", {})
                signal = meta.get("final_signal", first_data_part.get("result", {}).get("analysis_signal"))
                print("\n 메타데이터:")
                print(f"  - Agent 타입: {result.get('agent_type', 'AnalysisA2AAgent')}")
                print(f"  - 최종 신호: {signal or 'N/A'}")
                print(f"  - 신뢰도: {meta.get('confidence', 'N/A')}")
                print(f"  - 실행 상태: {meta.get('execution_complete', 'N/A')} / status={status} final={final}")
                print_structured_summary(first_data_part)
                return

            # 실제 데이터 구조: data_parts[0].analysis_result.analysis_result.messages
            analysis_result = first_data_part.get("analysis_result", {})
            nested_analysis = analysis_result.get("analysis_result", {})
            messages = nested_analysis.get("messages", [])
            
            if messages:
                # 마지막 AI 메시지에서 분석 결과 추출
                final_ai_message = None
                for msg in reversed(messages):
                    # 실제 메시지 구조: message.data.content
                    msg_data = msg.get("data", {})
                    if msg.get("type") == "ai" and msg_data.get("content"):
                        final_ai_message = msg
                        break
                
                if final_ai_message:
                    print(" 주식 데이터 통합 분석 완료!")
                    
                    # 도구 호출 통계 (실제 구조: message.data.additional_kwargs.tool_calls)
                    tool_calls_count = 0
                    for msg in messages:
                        msg_data = msg.get("data", {})
                        if msg.get("type") == "ai":
                            additional_kwargs = msg_data.get("additional_kwargs", {})
                            if "tool_calls" in additional_kwargs:
                                tool_calls_count += len(additional_kwargs["tool_calls"])
                    
                    print(f" 도구 호출 횟수: {tool_calls_count}")
                    print(f" 총 메시지 수: {len(messages)}")
                    
                    # 분석 내용 출력 (실제 구조: message.data.content)
                    analysis_content = final_ai_message["data"]["content"]
                    print("\n Agent 응답:")
                    print("-" * 50)
                    
                    # 분석 내용을 줄 단위로 출력 (처음 20줄)
                    lines = analysis_content.split("\n")
                    for line in lines[:20]:
                        if line.strip():
                            print(f"  {line}")
                    
                    if len(lines) > 20:
                        print("  ... (더 많은 내용은 JSON 파일 참조)")
                    
                    # 메타데이터
                    print("\n 메타데이터:")
                    print(f"  - Agent 이름: {first_data_part.get('agent_metadata', {}).get('agent_name', 'AnalysisAgent')}")
                    print(f"  - 실행 성공: True")
                    print(f"  - 전체 DataPart 수: {len(data_parts)}")
                    
                    return
        
        print(" 분석 실패: 유효한 분석 결과를 찾을 수 없습니다.")
        return
    else:
        # 기존 포맷 호환성 유지
        main_result = result
        
        if not main_result.get("success", False):
            print(f" 분석 실패: {main_result.get('error', 'Unknown error')}")
            return
    
    # 전체 메시지 히스토리 표시
    if "full_message_history" in result:
        message_history = result["full_message_history"]
        if message_history:
            print(f"\n 전체 메시지 히스토리 ({len(message_history)}개 메시지):")
            print("-" * 60)
            for i, msg in enumerate(message_history, 1):
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                timestamp = msg.get('timestamp', 'N/A')

                # 역할 이모지
                role_emoji = {"user": "", "agent": "🤖", "system": "️"}.get(role, "")

                print(f"{role_emoji} 메시지 {i} ({role}) - {timestamp}")
                if content:
                    # 긴 내용은 줄임
                    content_preview = content[:100] + "..." if len(content) > 100 else content
                    print(f"   내용: {content_preview}")

                # 데이터가 있다면 표시
                if 'data' in msg:
                    data_keys = list(msg['data'].keys()) if isinstance(msg['data'], dict) else ['data']
                    print(f"   데이터: {data_keys}")
                print()
    
    # 스트리밍 텍스트 표시
    if "streaming_text" in result:
        streaming_text = result["streaming_text"]
        if streaming_text:
            print("\n 스트리밍 텍스트:")
            print("-" * 50)
            # 스트리밍 텍스트를 줄 단위로 출력
            for line in streaming_text.split("\n")[:15]:  # 처음 15줄만
                if line.strip():
                    print(f"  {line}")
            if len(streaming_text.split("\n")) > 15:
                print("  ... (전체 스트리밍 텍스트는 JSON 파일 참조)")
    
    # 이벤트 카운트 표시
    if "event_count" in result:
        print(f"\n 처리된 이벤트 수: {result['event_count']}")
    
    print("\n Analysis Agent A2A 호출 성공!")


async def main():
    """메인 실행 함수"""
    
    print_section("Analysis Agent - A2A 프로토콜 예제")
    print("A2A 프로토콜을 통해 원격 Analysis Agent와 통신합니다.")
    
    # 1. A2A 서버 상태 확인
    if not await check_a2a_server():
        print("\n️ A2A 서버가 실행되지 않았습니다.")
        print("위의 해결 방법을 따라 서버를 먼저 실행해주세요.")
        return
    
    # 2. 통합 테스트 초기화
    test_result = AnalysisIntegrationTestResult()
    test_result.start_time = datetime.now()
    
    # 2. 분석 테스트 케이스 준비
    print_section("분석 요청 준비")
    
    # 기본 데이터 템플릿
    base_collected_data = {
        "price_data": {
            "current_price": 71000,
            "change_rate": 2.5,
            "volume": 15000000
        },
        "stock_info": {
            "name": "삼성전자",
            "sector": "반도체",
            "market_cap": "430조원"
        },
        "news_data": {
            "article_count": 15,
            "sentiment_score": 0.65
        },
        "financial_data": {
            "per": 12.5,
            "pbr": 1.2,
            "roe": 15.8
        }
    }

    test_cases = [
        {
            "name": "삼성전자 종합 분석",
            "symbols": ["005930"],
            "collected_data": base_collected_data,
            "question": "삼성전자의 현재 투자 매력도를 깊이 분석해주세요",
            "test_type": "standard"
        },
    ]

    # 3. 각 테스트 케이스 실행
    for i, test_case in enumerate(test_cases, 1):
        print_section(f"테스트 {i}: {test_case['name']}")
        test_type = test_case.get("test_type", "standard")

        try:
            if test_type == "standard":
                # 기본 분석 테스트
                print("\n A2A 프로토콜을 통해 분석 중...")
                result = await call_analysis_via_a2a(
                    symbols=test_case["symbols"],
                    collected_data=test_case["collected_data"],
                    user_question=test_case["question"]
                )
                
                # 결과 출력
                print_section("분석 결과")
                format_analysis_result(result)
                
                # 테스트 성공 기록
                test_result.add_test_result(
                    test_case["name"],
                    True,
                    {"result_type": "standard_analysis", "status": "completed"}
                )
                
            elif test_type == "category_signal_consistency":
                # Category-based Signal 일관성 테스트
                print_section("Category-based Signal 일관성 테스트")
                consistency_result = await test_category_signal_consistency(
                    symbols=test_case["symbols"],
                    collected_data=test_case["collected_data"],
                    user_question=test_case["question"]
                )
                
                # 일관성 점수 기준 (0.6 이상이면 성공)
                consistency_score = consistency_result["consistency_analysis"]["consistency_score"]
                success = consistency_score >= 0.6
                
                test_result.add_test_result(
                    test_case["name"],
                    success,
                    consistency_result
                )
                
                result = consistency_result  # 저장을 위해
                
            elif test_type == "four_dimension_analysis":
                # 4차원 분석 커버리지 테스트
                print_section("4차원 분석 커버리지 테스트")
                dimension_result = await test_four_dimension_analysis(
                    symbols=test_case["symbols"],
                    collected_data=test_case["collected_data"],
                    user_question=test_case["question"]
                )
                
                test_result.add_test_result(
                    test_case["name"],
                    dimension_result["success"],
                    dimension_result
                )
                
                result = dimension_result  # 저장을 위해
                
            elif test_type == "output_validation":
                # A2AOutput 형식 및 신호 검증 테스트
                print_section("A2AOutput 형식 및 신호 검증")
                result = await call_analysis_via_a2a(
                    symbols=test_case["symbols"],
                    collected_data=test_case["collected_data"],
                    user_question=test_case["question"]
                )
                
                # A2AOutput 검증 및 Category signal 검증
                if isinstance(result, list) and result:
                    final_result = result[-1]
                else:
                    final_result = result
                    
                validation = validate_analysis_output(final_result, "analysis")
                
                print(f"   A2AOutput 검증 결과:")
                print(f"    - 유효성: {' 통과' if validation['valid'] else ' 실패'}")
                print(f"    - 발견된 필드: {', '.join(validation['found_fields'])}")
                if validation.get('category_signals_found'):
                    print(f"    - Category 신호: {', '.join(validation['category_signals_found'])}")
                if validation['errors']:
                    print(f"    - 오류: {', '.join(validation['errors'])}")
                if validation['warnings']:
                    print(f"    - 경고: {', '.join(validation['warnings'])}")
                
                # Category signal이 있으면 성공으로 판단
                has_category_signals = len(validation.get('category_signals_found', [])) > 0
                overall_success = validation['valid'] and has_category_signals
                
                test_result.add_test_result(
                    test_case["name"],
                    overall_success,
                    validation
                )
            
            # JSON 파일로 저장
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = Path("logs/examples/a2a")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"a2a_analysis_{test_type}_result_{timestamp}.json"
            
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            print(f"\n 전체 결과가 {output_file}에 저장되었습니다.")
            
        except Exception as e:
            print(f"\n 테스트 실행 중 오류 발생: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # 실패한 테스트 기록
            test_result.add_test_result(
                test_case["name"],
                False,
                {"error": str(e), "traceback": traceback.format_exc()}
            )
    
    # 4. 통합 테스트 보고서 생성
    test_result.end_time = datetime.now()
    
    print_section("Analysis Agent 통합 테스트 보고서")
    report = test_result.generate_report()
    print(report)
    
    # 5. 보고서 파일 저장
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = Path("logs/examples/a2a")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / f"analysis_integration_test_report_{timestamp}.txt"
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n 통합 테스트 보고서가 {report_file}에 저장되었습니다.")
    
    print_section("Analysis Agent A2A 통합 테스트 완료")
    print(" 모든 Analysis Agent 통합 테스트가 완료되었습니다.")
    print(f" 테스트 성공률: {test_result.passed_tests}/{test_result.total_tests} ({test_result.passed_tests/test_result.total_tests*100:.1f}%)")
    
    # 테스트 실패 시 종료 코드 반환
    return test_result.failed_tests == 0


if __name__ == "__main__":
    # 이벤트 루프 실행
    asyncio.run(main())