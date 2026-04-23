#!/usr/bin/env python3
"""
DataCollector Agent - A2A 프로토콜 호출 예제

A2A 프로토콜을 통해 DataCollector Agent와 통신하는 예제입니다.
Agent는 별도 프로세스로 실행되며, A2A 클라이언트를 통해 원격 호출합니다.

실행 전제 조건:
1. MCP 서버들이 실행 중이어야 함 (./1-run-all-services.sh)
2. DataCollector A2A 서버가 Docker compose로 실행되어 있어야 함
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


def print_section(title: str) -> None:
    """섹션 구분선 출력"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ============== 통합 테스트 기능 추가 ==============

class IntegrationTestResult:
    """통합 테스트 결과 저장 클래스"""
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
🧪 DataCollector A2A 통합 테스트 보고서
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


def validate_a2a_output(response: Dict[str, Any], expected_agent_type: str = "data_collector") -> Dict[str, Any]:
    """A2AOutput 표준 형식 검증"""
    validation_result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "found_fields": []
    }
    
    # 필수 필드 확인
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
    
    # status 필드 검증
    valid_statuses = ["working", "completed", "failed", "input_required"]
    if "status" in response:
        status = response.get("status")
        if status not in valid_statuses:
            validation_result["warnings"].append(f"알 수 없는 status 값: '{status}'")
    
    # 선택적 필드 확인
    optional_fields = ["text_content", "data_content", "final", "stream_event"]
    for field in optional_fields:
        if field in response:
            validation_result["found_fields"].append(field)
    
    return validation_result


async def test_streaming_vs_polling(
    symbols: List[str], 
    data_types: List[str], 
    user_question: str,
    datacollector_url: str = "http://localhost:8001"
) -> Dict[str, Any]:
    """스트리밍 테스트 제거: 폴링(블로킹)만 수행"""
    input_data = {
        "requested_symbols": symbols,
        "data_types": data_types,
        "user_question": user_question,
    }
    print("   풀링 모드 테스트...")
    start_time = time.time()
    try:
        async with A2AClientManagerV2(base_url=datacollector_url, streaming=False) as client_manager:
            polling_result = await client_manager.send_data_with_full_messages(input_data)
        polling_duration = time.time() - start_time
        print(f"     풀링 완료 ({polling_duration:.2f}초)")
        return {
            "polling": {
                "success": True,
                "duration": polling_duration,
                "result": polling_result if isinstance(polling_result, list) else [polling_result]
            }
        }
    except Exception as e:
        print(f"     풀링 실패: {str(e)}")
        return {
            "polling": {
                "success": False,
                "duration": time.time() - start_time,
                "error": str(e)
            }
        }


async def run_a2a_interface_tests(
    symbols: List[str],
    data_types: List[str], 
    user_question: str,
    datacollector_url: str = "http://localhost:8001"
) -> Dict[str, Any]:
    """A2A 인터페이스 핵심 메서드 테스트"""
    
    test_results = {
        "execute_for_a2a": {"tested": False, "success": False},
        "format_stream_event": {"tested": False, "success": False},
        "extract_final_output": {"tested": False, "success": False},
        "a2a_output_format": {"tested": False, "success": False}
    }
    
    input_data = {
        "requested_symbols": symbols,
        "data_types": data_types,
        "user_question": user_question,
    }
    
    print("  🧪 A2A 인터페이스 메서드 테스트...")
    
    try:
        # execute_for_a2a 간접 테스트 (A2A 호출을 통해)
        async with A2AClientManagerV2(base_url=datacollector_url) as client_manager:
            response = await client_manager.send_data_with_full_messages(input_data)
            
        test_results["execute_for_a2a"]["tested"] = True
        test_results["execute_for_a2a"]["success"] = response is not None
        
        # A2AOutput 형식 검증
        if isinstance(response, list) and response:
            final_response = response[-1]
        else:
            final_response = response
            
        validation = validate_a2a_output(final_response, "data_collector")
        test_results["a2a_output_format"]["tested"] = True
        test_results["a2a_output_format"]["success"] = validation["valid"]
        test_results["a2a_output_format"]["details"] = validation
        
        # 스트리밍 제거: format_stream_event 테스트 제외
        
        # extract_final_output 검증 (최종 결과 추출)
        if final_response and "status" in final_response:
            test_results["extract_final_output"]["tested"] = True
            test_results["extract_final_output"]["success"] = final_response.get("status") in ["completed", "failed"]
            print(f"     extract_final_output: 최종 상태 = {final_response.get('status')}")
            
        print("     A2A 인터페이스 테스트 완료")
        
    except Exception as e:
        print(f"     A2A 인터페이스 테스트 실패: {str(e)}")
        for test_name in test_results:
            if not test_results[test_name]["tested"]:
                test_results[test_name]["error"] = str(e)
    
    return test_results


async def check_a2a_server() -> bool:
    """A2A 서버 상태 확인"""
    import httpx

    # Agent Card 엔드포인트로 상태 확인
    server_url = "http://localhost:8001/.well-known/agent-card.json"

    print_section("A2A 서버 상태 확인")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(server_url, timeout=5.0)
            if response.status_code == 200:
                agent_card = response.json()
                print(" DataCollector A2A 서버: 정상 작동")
                print(f"   Agent: {agent_card.get('name', 'Unknown')}")
                print(f"   설명: {agent_card.get('description', 'No description')}")
                print(f"   스트리밍 지원: {agent_card.get('capabilities', {}).get('streaming', False)}")
                return True
            else:
                print(f"️ DataCollector A2A 서버: 응답 이상 (status: {response.status_code})")
                return False
        except Exception as e:
            print(" DataCollector A2A 서버: 연결 실패")
            print(f"   오류: {str(e)[:100]}")
            print("\n 해결 방법:")
            print("   1. 터미널에서 다음 명령 실행:")
            print("      python -m src.a2a_agents.data_collector.data_collector_agent_a2a")
            print("   2. 서버가 포트 8001에서 실행 중인지 확인")
            return False


async def call_data_collector_via_a2a(
    symbols: list[str],
    data_types: list[str],
    user_question: str
) -> dict[str, Any]:
    """A2A 프로토콜을 통해 DataCollector Agent 호출 (전체 메시지 포함)"""

    # DataCollector A2A 서버 URL (도커 컨테이너 포트)
    datacollector_url = "http://localhost:8001"

    # 입력 데이터 준비
    input_data = {
        "requested_symbols": symbols,
        "data_types": data_types,
        "user_question": user_question,
    }

    print("\n 요청 전송:")
    print(f"   - 종목: {symbols}")
    print(f"   - 데이터: {data_types}")
    print(f"   - 질문: {user_question}")

    # 폴링 모드 사용
    async with A2AClientManagerV2(base_url=datacollector_url) as client_manager:
        try:
            response_data = await client_manager.send_data_with_full_messages(input_data)

            if isinstance(response_data, list) and response_data:
                return response_data[-1]
            else:
                return response_data

        except Exception as e:
            print(f" A2A 호출 실패: {str(e)}")
            raise


def format_collection_result(result: dict[str, Any]) -> None:
    """수집 결과 포맷팅 및 출력 (전체 메시지 히스토리 포함)"""

    # 새로운 포맷의 결과인지 확인 (data_parts 포함)
    if "data_parts" in result:
        # 새로운 포맷: 전체 메시지 히스토리 포함
        data_parts = result.get("data_parts", [])
        if data_parts:
            # 첫 번째 데이터 파트 사용 (기존 호환성 유지)
            main_result = data_parts[0] if isinstance(data_parts, list) else data_parts
        else:
            print(" 데이터 수집 실패: DataPart가 없습니다.")
            return
    else:
        # 기존 포맷: 직접 결과 사용
        main_result = result

    if not main_result.get("success", False):
        print(f" 데이터 수집 실패: {main_result.get('error', 'Unknown error')}")
        return

    print(" 데이터 수집 성공!")

    # 수집된 데이터 파싱
    collected_data = main_result.get("collected_data", {})

    # 처리된 종목
    if "symbols_processed" in collected_data:
        print(f"\n 처리된 종목: {collected_data['symbols_processed']}")

    # 도구 호출 통계
    if "tool_calls_made" in collected_data:
        print(f" 도구 호출 횟수: {collected_data['tool_calls_made']}")

    # 원시 응답 (Agent의 최종 메시지)
    if "raw_response" in collected_data:
        print("\n Agent 최종 응답:")
        print("-" * 50)
        response_text = collected_data["raw_response"]
        # 응답을 줄 단위로 출력 (가독성 향상)
        for line in response_text.split("\n")[:10]:  # 처음 10줄만
            print(f"  {line}")
        if len(response_text.split("\n")) > 10:
            print("  ... (전체 응답은 JSON 파일 참조)")

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
        if streaming_text and streaming_text != collected_data.get("raw_response", ""):
            print("\n 스트리밍 텍스트:")
            print("-" * 50)
            # 스트리밍 텍스트를 줄 단위로 출력
            for line in streaming_text.split("\n")[:15]:  # 처음 15줄만
                print(f"  {line}")
            if len(streaming_text.split("\n")) > 15:
                print("  ... (전체 스트리밍 텍스트는 JSON 파일 참조)")

    # 이벤트 카운트 표시
    if "event_count" in result:
        print(f"\n 처리된 이벤트 수: {result['event_count']}")

    # 메타데이터
    print("\n 메타데이터:")
    print(f"  - 워크플로우 상태: {main_result.get('workflow_status', 'N/A')}")
    print(f"  - Agent 타입: {main_result.get('agent_type', 'N/A')}")
    print(f"  - 성공 여부: {main_result.get('success', False)}")

    # DataParts 추가 정보
    if "data_parts" in result and len(result["data_parts"]) > 1:
        print(f"  - 추가 DataPart 수: {len(result['data_parts']) - 1}")


async def main() -> None:
    """메인 실행 함수"""
    
    print_section("DataCollector Agent - A2A 프로토콜 예제")
    print("A2A 프로토콜을 통해 원격 Agent와 통신합니다.")
    
    # 1. A2A 서버 상태 확인
    if not await check_a2a_server():
        print("\n️ A2A 서버가 실행되지 않았습니다.")
        print("위의 해결 방법을 따라 서버를 먼저 실행해주세요.")
        return
    
    # 2. 통합 테스트 초기화
    test_result = IntegrationTestResult()
    test_result.start_time = datetime.now()
    
    # 2. 테스트 데이터 준비
    print_section("데이터 수집 요청 준비")
    
    test_cases: list[dict[str, Any]] = [
        {
            "name": "삼성전자 종합 데이터 수집 요청",
            "symbols": ["005930"],
            "data_types": ["price", "info", "news", "financial"],
            "question": "삼성전자의 모을 수 있는 모든 데이터를 모아서 전달해주세요.",
            "test_type": "standard"
        },
        # ============== 통합 테스트 케이스 추가 ==============        
        # {
        #     "name": "A2A 인터페이스 메서드 검증 테스트",
        #     "symbols": ["005930"],
        #     "data_types": ["price"],
        #     "question": "삼성전자 현재 가격 정보를 가져와주세요.",
        #     "test_type": "a2a_interface"
        # },
        # {
        #     "name": "A2AOutput 표준 형식 검증 테스트",
        #     "symbols": ["005930"],
        #     "data_types": ["info"],
        #     "question": "삼성전자 기업 정보를 수집해주세요.",
        #     "test_type": "output_validation"
        # }
    ]

    # 3. 각 테스트 케이스 실행
    for i, test_case in enumerate(test_cases, 1):
        print_section(f"테스트 {i}: {test_case['name']}")
        test_type = test_case.get("test_type", "standard")

        try:
            if test_type == "standard":
                # 기본 데이터 수집 테스트
                print("\n A2A 프로토콜을 통해 데이터 수집 중...")
                result = await call_data_collector_via_a2a(
                    symbols=test_case["symbols"],
                    data_types=test_case["data_types"],
                    user_question=test_case["question"]
                )

                # 결과 출력
                print_section("수집 결과")
                format_collection_result(result)
                
                # 테스트 성공 기록
                test_result.add_test_result(
                    test_case["name"], 
                    True, 
                    {"result_type": "standard_collection", "status": "completed"}
                )
                
            elif test_type == "a2a_interface":
                # A2A 인터페이스 메서드 검증 테스트
                print_section("A2A 인터페이스 메서드 검증")
                interface_test_result = await run_a2a_interface_tests(
                    symbols=test_case["symbols"],
                    data_types=test_case["data_types"],
                    user_question=test_case["question"]
                )
                
                # 모든 핵심 메서드가 성공적으로 테스트되었는지 확인
                all_tests_passed = all(
                    test_info.get("success", False) or not test_info.get("tested", False)
                    for test_info in interface_test_result.values()
                )
                
                test_result.add_test_result(
                    test_case["name"],
                    all_tests_passed,
                    interface_test_result
                )
                
                result = interface_test_result  # 저장을 위해
                
            elif test_type == "output_validation":
                # A2AOutput 표준 형식 검증 테스트
                print_section("A2AOutput 표준 형식 검증")
                result = await call_data_collector_via_a2a(
                    symbols=test_case["symbols"],
                    data_types=test_case["data_types"],
                    user_question=test_case["question"]
                )
                
                # A2AOutput 형식 검증
                if isinstance(result, list) and result:
                    final_result = result[-1]
                else:
                    final_result = result
                    
                validation = validate_a2a_output(final_result, "data_collector")
                
                print(f"   A2AOutput 검증 결과:")
                print(f"    - 유효성: {' 통과' if validation['valid'] else ' 실패'}")
                print(f"    - 발견된 필드: {', '.join(validation['found_fields'])}")
                if validation['errors']:
                    print(f"    - 오류: {', '.join(validation['errors'])}")
                if validation['warnings']:
                    print(f"    - 경고: {', '.join(validation['warnings'])}")
                
                test_result.add_test_result(
                    test_case["name"],
                    validation['valid'],
                    validation
                )
            
            # JSON 파일로 저장
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = Path("logs/examples/a2a")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"a2a_{test_type}_result_{timestamp}.json"
            
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
    
    print_section("통합 테스트 보고서")
    report = test_result.generate_report()
    print(report)
    
    # 5. 보고서 파일 저장
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = Path("logs/examples/a2a")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / f"datacollector_integration_test_report_{timestamp}.txt"
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n 통합 테스트 보고서가 {report_file}에 저장되었습니다.")
    
    print_section("DataCollector A2A 통합 테스트 완료")
    print(" 모든 통합 테스트가 완료되었습니다.")
    print(f" 테스트 성공률: {test_result.passed_tests}/{test_result.total_tests} ({test_result.passed_tests/test_result.total_tests*100:.1f}%)")
    
    # 테스트 실패 시 종료 코드 반환
    return test_result.failed_tests == 0


if __name__ == "__main__":
    # 이벤트 루프 실행
    asyncio.run(main())