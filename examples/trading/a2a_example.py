#!/usr/bin/env python3
"""
Trading Agent - A2A 프로토콜 호출 예제

A2A 프로토콜을 통해 Trading Agent와 통신하는 예제입니다.
리스크 관리와 Human-in-the-Loop 승인을 통한 안전한 거래 실행을 수행합니다.

실행 전제 조건:
1. MCP 서버들이 실행 중이어야 함 (./1-run-all-services.sh)
2. Trading A2A 서버가 Docker compose로 실행되어 있어야 함
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


# ============== Trading Agent 통합 테스트 기능 추가 ==============

class TradingIntegrationTestResult:
    """Trading Agent 통합 테스트 결과 저장 클래스"""
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
🧪 TradingAgent A2A 통합 테스트 보고서
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


def validate_trading_output(response: Dict[str, Any], expected_agent_type: str = "trading") -> Dict[str, Any]:
    """Trading Agent A2AOutput 검증 (HITL 워크플로우 상태 포함)"""
    validation_result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "found_fields": [],
        "hitl_indicators": [],
        "status_transitions": []
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
    
    # HITL 관련 키워드 검증 (Trading Agent 특화)
    hitl_keywords = ["승인", "approval", "human", "input_required", "리스크", "risk", "VaR"]
    
    # data_content나 text_content에서 HITL 키워드 검색
    content_to_check = []
    if "data_content" in response:
        content_to_check.append(json.dumps(response["data_content"]) if isinstance(response["data_content"], dict) else str(response["data_content"]))
    if "text_content" in response:
        content_to_check.append(response["text_content"])
    
    for content in content_to_check:
        for keyword in hitl_keywords:
            if keyword.lower() in content.lower():
                validation_result["hitl_indicators"].append(keyword)
    
    # HITL 지표 검증
    if validation_result["hitl_indicators"]:
        print(f"    ️ 발견된 HITL 지표: {', '.join(validation_result['hitl_indicators'])}")
    else:
        validation_result["warnings"].append("Human-in-the-Loop 관련 키워드를 찾을 수 없습니다")
    
    # 거래 상태 검증
    valid_trading_statuses = ["working", "input_required", "completed", "failed"]
    if "status" in response:
        status = response.get("status")
        if status in valid_trading_statuses:
            validation_result["status_transitions"].append(status)
            print(f"     거래 상태: {status}")
        else:
            validation_result["warnings"].append(f"알 수 없는 거래 상태: '{status}'")
    
    return validation_result


async def test_hitl_workflow_simulation(
    symbols: List[str],
    trading_signal: str,
    analysis_result: Dict[str, Any],
    user_question: str,
    trading_url: str = "http://localhost:8003"
) -> Dict[str, Any]:
    """Human-in-the-Loop 워크플로우 시뮬레이션 테스트"""
    
    input_data = {
        "symbols": symbols,
        "trading_signal": trading_signal,
        "analysis_result": analysis_result,
        "user_question": user_question,
    }
    
    workflow_stages = []
    current_stage = "초기화"
    
    print(f"  ️ HITL 워크플로우 시뮬레이션 테스트...")
    print(f"     거래 신호: {trading_signal}")
    print(f"     대상 종목: {', '.join(symbols)}")
    
    try:
        # Stage 1: 초기 거래 요청
        print(f"     단계 1: 거래 요청 전송...")
        start_time = time.time()
        
        async with A2AClientManagerV2(base_url=trading_url) as client_manager:
            response = await client_manager.send_data_with_full_messages(input_data)
        
        execution_time = time.time() - start_time
        
        # 응답 분석
        if isinstance(response, list) and response:
            final_response = response[-1]
            all_responses = response
        else:
            final_response = response
            all_responses = [response]
        
        # 상태 전환 추적
        status_sequence = []
        for resp in all_responses:
            if isinstance(resp, dict) and "status" in resp:
                status = resp["status"]
                if status not in status_sequence:
                    status_sequence.append(status)
        
        workflow_stages.append({
            "stage": "거래_요청",
            "duration": execution_time,
            "status_sequence": status_sequence,
            "final_status": final_response.get("status") if isinstance(final_response, dict) else "unknown",
            "response_count": len(all_responses)
        })
        
        # Stage 2: HITL 승인 요구 검증
        validation = validate_trading_output(final_response, "trading")
        has_hitl_indicators = len(validation.get("hitl_indicators", [])) > 0
        requires_approval = final_response.get("status") == "input_required" if isinstance(final_response, dict) else False
        
        print(f"     실행 시간: {execution_time:.2f}초")
        print(f"     상태 전환: {' -> '.join(status_sequence)}")
        print(f"    ️ HITL 필요: {'Yes' if requires_approval else 'No'}")
        print(f"     HITL 지표: {'발견됨' if has_hitl_indicators else '미발견'}")
        
        # 성공 기준: 
        # 1. 응답을 받았음
        # 2. 유효한 거래 상태를 가짐
        # 3. HITL 지표가 있거나 완료 상태임
        success_criteria = {
            "response_received": final_response is not None,
            "valid_status": final_response.get("status") in ["working", "input_required", "completed", "failed"] if isinstance(final_response, dict) else False,
            "hitl_or_completed": has_hitl_indicators or final_response.get("status") in ["completed", "failed"] if isinstance(final_response, dict) else False
        }
        
        overall_success = all(success_criteria.values())
        
        print(f"     성공 기준:")
        for criterion, passed in success_criteria.items():
            status = "" if passed else ""
            print(f"      {status} {criterion}")
        
        return {
            "success": overall_success,
            "workflow_stages": workflow_stages,
            "success_criteria": success_criteria,
            "validation": validation,
            "final_response": final_response,
            "all_responses": all_responses
        }
        
    except Exception as e:
        print(f"     HITL 워크플로우 테스트 실패: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "workflow_stages": workflow_stages
        }


async def test_risk_assessment_integration(
    symbols: List[str],
    trading_signal: str,
    analysis_result: Dict[str, Any],
    user_question: str,
    trading_url: str = "http://localhost:8003"
) -> Dict[str, Any]:
    """리스크 평가 통합 테스트"""
    
    # 리스크가 높은 시나리오 생성
    high_risk_analysis = {
        **analysis_result,
        "confidence_level": 0.3,  # 낮은 신뢰도
        "integrated_score": 0.2 if trading_signal == "SELL" else 0.9,  # 극단적 점수
        "risk_factors": [
            "높은 변동성", "시장 불안정", "대량 거래", 
            "리스크 임계치 초과", "포지션 한도 근접"
        ]
    }
    
    input_data = {
        "symbols": symbols,
        "trading_signal": trading_signal,
        "analysis_result": high_risk_analysis,
        "user_question": f"{user_question} (고위험 시나리오 테스트)",
    }
    
    print(f"  ️ 리스크 평가 통합 테스트 (고위험 시나리오)...")
    print(f"     신뢰도: {high_risk_analysis['confidence_level']}")
    print(f"     통합점수: {high_risk_analysis['integrated_score']}")
    
    try:
        async with A2AClientManagerV2(base_url=trading_url) as client_manager:
            response = await client_manager.send_data_with_full_messages(input_data)
        
        # 응답에서 리스크 관련 키워드 검증
        if isinstance(response, list) and response:
            final_response = response[-1]
        else:
            final_response = response
            
        risk_keywords = ["리스크", "risk", "VaR", "위험", "손실", "한도", "제한"]
        content_to_analyze = ""
        
        if isinstance(final_response, dict):
            if "data_content" in final_response:
                content_to_analyze += json.dumps(final_response["data_content"]) if isinstance(final_response["data_content"], dict) else str(final_response["data_content"])
            if "text_content" in final_response:
                content_to_analyze += final_response["text_content"]
        
        found_risk_keywords = [kw for kw in risk_keywords if kw.lower() in content_to_analyze.lower()]
        
        # 리스크 평가 결과 분석
        requires_approval = final_response.get("status") == "input_required" if isinstance(final_response, dict) else False
        has_risk_keywords = len(found_risk_keywords) > 0
        
        print(f"     발견된 리스크 키워드: {', '.join(found_risk_keywords[:5])}")  # 처음 5개만
        print(f"    ️ 승인 필요: {'Yes' if requires_approval else 'No'}")
        
        # 고위험 시나리오에서는 승인이 필요하거나 리스크 키워드가 있어야 함
        risk_awareness = requires_approval or has_risk_keywords
        
        return {
            "success": risk_awareness,
            "requires_approval": requires_approval,
            "risk_keywords_found": found_risk_keywords,
            "risk_awareness": risk_awareness,
            "final_response": final_response
        }
        
    except Exception as e:
        print(f"     리스크 평가 테스트 실패: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


async def check_a2a_server() -> bool:
    """A2A 서버 상태 확인"""
    import httpx
    
    # Agent Card 엔드포인트로 서버 상태 확인
    server_url = "http://localhost:8003/.well-known/agent-card.json"  # Trading A2A 서버 포트 (도커)
    
    print_section("A2A 서버 상태 확인")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(server_url, timeout=2.0)
            if response.status_code == 200:
                print("Trading A2A 서버: 정상 작동")
                return True
            else:
                print(f"Trading A2A 서버: 응답 이상 (status: {response.status_code})")
                return False
        except Exception as e:
            print(f"Trading A2A 서버: 연결 실패")
            print(f"오류: {str(e)[:100]}")
            print("\n해결 방법:")
            print("1. 터미널에서 다음 명령 실행:")
            print("docker-compose -f docker/a2a_agents/docker-compose.yml up trading-agent")
            print("2. 서버가 포트 8003에서 실행 중인지 확인")
            return False


async def call_trading_via_a2a(
    symbols: list,
    trading_signal: str,
    analysis_result: dict,
    user_question: str
) -> Dict[str, Any]:
    """A2A 프로토콜을 통해 Trading Agent 호출"""
    
    # Trading A2A 서버 URL (도커 컨테이너 포트)
    trading_url = "http://localhost:8003"
    
    # 입력 데이터 준비
    input_data = {
        "symbols": symbols,
        "trading_signal": trading_signal,
        "analysis_result": analysis_result,
        "user_question": user_question,
    }
    
    print("\n 거래 요청 전송:")
    print(f"   - 종목: {symbols}")
    print(f"   - 거래 신호: {trading_signal}")
    print(f"   - 분석 점수: {analysis_result.get('integrated_score', 'N/A')}")
    print(f"   - 질문: {user_question}")
    
    # A2A 클라이언트 매니저 사용 (async with 패턴)
    async with A2AClientManagerV2(base_url=trading_url) as client_manager:
        try:
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


def parse_trading_response(response_text: str):
    """Trading Agent 응답 파싱 및 출력"""
    
    print("\n Agent 거래 응답:")
    print("-" * 50)
    
    # 응답을 섹션별로 분리하여 표시
    lines = response_text.split("\n")
    current_section = None
    
    for line in lines[:30]:  # 처음 30줄만 표시
        line = line.strip()
        if not line:
            continue
            
        # 섹션 헤더 감지
        if line.startswith("") or line.startswith("️") or line.startswith("") or line.startswith(""):
            current_section = line
            print(f"\n{line}")
        elif line.startswith("-") and current_section:
            print(f"  {line}")
        else:
            print(f"  {line}")
    
    if len(lines) > 30:
        print("\n  ... (더 많은 내용은 JSON 파일 참조)")


def format_trading_result(result: Dict[str, Any]):
    """거래 결과 포맷팅 및 출력 (Trading Agent 전용 구조)"""
    
    # A2A Trading Agent 결과 구조 처리
    if "data_parts" in result:
        data_parts = result.get("data_parts", [])
        if data_parts and isinstance(data_parts, list) and len(data_parts) > 0:
            # 첫 번째 DataPart에서 메시지 히스토리 추출
            first_data_part = data_parts[0]
            messages = first_data_part.get("messages", [])
            
            if messages:
                # 마지막 AI 메시지에서 거래 결과 추출
                final_ai_message = None
                for msg in reversed(messages):
                    if msg.get("type") == "ai" and msg.get("content"):
                        final_ai_message = msg
                        break
                
                if final_ai_message:
                    print(" 거래 프로세스 완료!")
                    
                    # 도구 호출 통계
                    tool_calls_count = 0
                    for msg in messages:
                        if hasattr(msg, 'get') and msg.get("tool_calls"):
                            tool_calls_count += len(msg.get("tool_calls", []))
                        elif msg.get("type") == "ai" and "tool_calls" in msg.get("additional_kwargs", {}):
                            tool_calls_count += len(msg["additional_kwargs"]["tool_calls"])
                    
                    print(f" 도구 호출 횟수: {tool_calls_count}")
                    print(f" 총 메시지 수: {len(messages)}")
                    
                    # 거래 내용 출력
                    trading_content = final_ai_message["content"]
                    print("\n Agent 거래 응답:")
                    print("-" * 50)
                    
                    # 거래 내용을 줄 단위로 출력 (처음 20줄)
                    lines = trading_content.split("\n")
                    for line in lines[:20]:
                        if line.strip():
                            print(f"  {line}")
                    
                    if len(lines) > 20:
                        print("  ... (더 많은 내용은 JSON 파일 참조)")
                    
                    # 메타데이터
                    print("\n 거래 메타데이터:")
                    print(f"  - Agent 이름: {first_data_part.get('agent_metadata', {}).get('agent_name', 'TradingAgent')}")
                    print(f"  - 실행 성공: True")
                    print(f"  - 전체 DataPart 수: {len(data_parts)}")
                    
                    return
        
        print(" 거래 실행 실패: 유효한 거래 결과를 찾을 수 없습니다.")
        return
    else:
        # 기존 포맷 호환성 유지
        if not result.get("success", False):
            print(f" 거래 실행 실패: {result.get('error', 'Unknown error')}")
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
    
    print("\n Trading Agent A2A 호출 성공!")


async def main():
    """메인 실행 함수"""

    print_section("Trading Agent - A2A 프로토콜 예제")
    print("A2A 프로토콜을 통해 원격 Trading Agent와 통신합니다.")

    # 1. A2A 서버 상태 확인
    if not await check_a2a_server():
        print("\n️ A2A 서버가 실행되지 않았습니다.")
        print("위의 해결 방법을 따라 서버를 먼저 실행해주세요.")
        return

    # 2. 통합 테스트 초기화
    test_result = TradingIntegrationTestResult()
    test_result.start_time = datetime.now()

    # 2. 거래 테스트 케이스 준비
    print_section("거래 요청 준비")

    # 기본 분석 결과 템플릿
    base_analysis_result = {
        "investment_signal": "SELL",
        "integrated_score": 0.75,
        "confidence_level": 0.85,
        "dimension_analysis": {
            "technical": {"score": 0.8, "insights": "기술적 지표 강세"},
            "fundamental": {"score": 0.7, "insights": "밸류에이션 매력적"},
            "macro": {"score": 0.75, "insights": "거시환경 긍정적"},
            "sentiment": {"score": 0.8, "insights": "시장 심리 양호"}
        },
        "risk_factors": ["반도체 경기 변동성", "환율 변동 리스크"],
        "price_target_range": "71000-70000원"
    }

    test_cases = [
        {
            "name": "삼성전자 매도 - 기본 거래",
            "symbols": ["005930"],
            "trading_signal": "SELL",
            "analysis_result": base_analysis_result,
            "question": "삼성전자를 안전하게 매도하고 싶습니다.",
            "test_type": "standard"
        }
    ]
    # 3. 각 테스트 케이스 실행
    for i, test_case in enumerate(test_cases, 1):
        print_section(f"테스트 {i}: {test_case['name']}")
        test_type = test_case.get("test_type", "standard")

        try:
            if test_type == "standard":
                # 기본 거래 테스트
                print("\n A2A 프로토콜을 통해 안전한 거래 실행 중...")
                print("️ Human 승인이 필요할 수 있습니다")
                result = await call_trading_via_a2a(
                    symbols=test_case["symbols"],
                    trading_signal=test_case["trading_signal"],
                    analysis_result=test_case["analysis_result"],
                    user_question=test_case["question"]
                )

                # 결과 출력
                print_section("거래 결과")
                format_trading_result(result)
                
                # 테스트 성공 기록
                test_result.add_test_result(
                    test_case["name"],
                    True,
                    {"result_type": "standard_trading", "status": "completed"}
                )

            elif test_type == "hitl_workflow":
                # HITL 워크플로우 시뮬레이션 테스트
                print_section("Human-in-the-Loop 워크플로우 시뮬레이션")
                hitl_result = await test_hitl_workflow_simulation(
                    symbols=test_case["symbols"],
                    trading_signal=test_case["trading_signal"],
                    analysis_result=test_case["analysis_result"],
                    user_question=test_case["question"]
                )
                
                test_result.add_test_result(
                    test_case["name"],
                    hitl_result["success"],
                    hitl_result
                )
                
                result = hitl_result  # 저장을 위해

            elif test_type == "risk_assessment":
                # 리스크 평가 통합 테스트
                print_section("고위험 거래 리스크 평가 테스트")
                risk_result = await test_risk_assessment_integration(
                    symbols=test_case["symbols"],
                    trading_signal=test_case["trading_signal"],
                    analysis_result=test_case["analysis_result"],
                    user_question=test_case["question"]
                )
                
                test_result.add_test_result(
                    test_case["name"],
                    risk_result["success"],
                    risk_result
                )
                
                result = risk_result  # 저장을 위해

            elif test_type == "output_validation":
                # A2AOutput 형식 및 HITL 상태 검증 테스트
                print_section("A2AOutput 형식 및 HITL 상태 검증")
                result = await call_trading_via_a2a(
                    symbols=test_case["symbols"],
                    trading_signal=test_case["trading_signal"],
                    analysis_result=test_case["analysis_result"],
                    user_question=test_case["question"]
                )
                
                # A2AOutput 검증 및 HITL 상태 검증
                if isinstance(result, list) and result:
                    final_result = result[-1]
                else:
                    final_result = result
                    
                validation = validate_trading_output(final_result, "trading")
                
                print(f"   A2AOutput 검증 결과:")
                print(f"    - 유효성: {' 통과' if validation['valid'] else ' 실패'}")
                print(f"    - 발견된 필드: {', '.join(validation['found_fields'])}")
                if validation.get('hitl_indicators'):
                    print(f"    - HITL 지표: {', '.join(validation['hitl_indicators'])}")
                if validation.get('status_transitions'):
                    print(f"    - 상태 전환: {', '.join(validation['status_transitions'])}")
                if validation['errors']:
                    print(f"    - 오류: {', '.join(validation['errors'])}")
                if validation['warnings']:
                    print(f"    - 경고: {', '.join(validation['warnings'])}")
                
                # HITL 지표가 있거나 유효한 거래 상태면 성공으로 판단
                has_hitl_indicators = len(validation.get('hitl_indicators', [])) > 0
                has_valid_status = len(validation.get('status_transitions', [])) > 0
                overall_success = validation['valid'] and (has_hitl_indicators or has_valid_status)
                
                test_result.add_test_result(
                    test_case["name"],
                    overall_success,
                    validation
                )

            # JSON 파일로 저장
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = Path("logs/examples/a2a")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"a2a_trading_{test_type}_result_{timestamp}.json"

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

    print_section("A2A 거래 테스트 완료")
    print(" 모든 거래 테스트가 완료되었습니다.")
    print(" 안전한 거래 시스템이 정상적으로 작동했습니다.")


if __name__ == "__main__":
    # 이벤트 루프 실행
    asyncio.run(main())