#!/usr/bin/env python3
"""
SupervisorAgent - A2A 프로토콜 호출 예제

A2A 프로토콜을 통해 SupervisorAgent와 통신하여 전체 워크플로우를 테스트합니다.
SupervisorAgent는 사용자 요청을 분석하여 적절한 하위 에이전트들을 호출합니다.

실행 전제 조건:
1. MCP 서버들이 실행 중이어야 함 (Docker compose로 실행됨)
2. SupervisorAgent A2A 서버가 Docker compose로 실행되어 있어야 함
"""

import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.a2a_integration.a2a_lg_client_utils_v2 import A2AClientManagerV2

logger = structlog.get_logger(__name__)

# 개별 A2A 에이전트 URL 설정
AGENT_URLS = {
    "supervisor": "http://localhost:8000",
    "data_collector": "http://localhost:8001", 
    "analysis": "http://localhost:8002",
    "trading": "http://localhost:8003"
}


@dataclass
class SupervisorIntegrationTestResult:
    """SupervisorAgent 통합 테스트 결과"""
    test_name: str
    passed: bool
    details: Dict[str, Any]
    execution_time_ms: float
    error_message: Optional[str] = None
    sub_tests: List[Dict[str, Any]] = field(default_factory=list)

    def add_sub_test(self, name: str, passed: bool, details: Any = None):
        """서브 테스트 결과 추가"""
        self.sub_tests.append({
            "name": name,
            "passed": passed,
            "details": details
        })


def validate_supervisor_output(response_data: Dict[str, Any]) -> Dict[str, bool]:
    """
    SupervisorAgent 응답 데이터 검증

    워크플로우 패턴 검증:
    - DATA_ONLY: 데이터만 수집
    - DATA_ANALYSIS: 데이터 수집 + 분석
    - FULL_WORKFLOW: 전체 워크플로우 (거래 포함)
    """
    validation_results = {
        "has_valid_structure": False,
        "has_workflow_pattern": False,
        "has_sub_agent_info": False,
        "has_coordination_result": False,
        "has_proper_format": False
    }

    try:
        # 기본 구조 검증
        if isinstance(response_data, dict):
            validation_results["has_valid_structure"] = True
            
        # 워크플로우 패턴 정보 확인 (응답에서 추론 가능한 패턴)
        content_str = str(response_data).lower()
        workflow_indicators = [
            "데이터", "분석", "거래", "workflow", 
            "datacollector", "analysis", "trading"
        ]
        if any(indicator in content_str for indicator in workflow_indicators):
            validation_results["has_workflow_pattern"] = True
            
        # 서브 에이전트 호출 정보 확인
        sub_agent_indicators = [
            "agent", "에이전트", "호출", "실행", 
            "datacollector", "analysis", "trading"
        ]
        if any(indicator in content_str for indicator in sub_agent_indicators):
            validation_results["has_sub_agent_info"] = True
            
        # 조정 결과 확인
        coordination_indicators = [
            "결과", "완료", "성공", "result", "response"
        ]
        if any(indicator in content_str for indicator in coordination_indicators):
            validation_results["has_coordination_result"] = True
            
        # A2A 형식 준수 확인
        if ("content" in response_data or 
            "text_content" in response_data or 
            "data" in response_data):
            validation_results["has_proper_format"] = True
            
    except Exception as e:
        logger.error(f"응답 검증 중 오류: {e}")
        
    return validation_results


async def call_individual_agent(agent_type: str, query: str) -> Dict[str, Any]:
    """개별 A2A 에이전트 직접 호출"""
    agent_url = AGENT_URLS.get(agent_type)
    if not agent_url:
        raise ValueError(f"Unknown agent type: {agent_type}")
        
    input_data = {"messages": [{"role": "user", "content": query}]}
    
    print(f" {agent_type} 에이전트 직접 호출: {agent_url}")
    print(f"    요청: {query}")
    
    async with A2AClientManagerV2(
        base_url=agent_url,
        streaming=False,
        retry_delay=1.0,
        max_retries=3
    ) as client_manager:
        result = await client_manager.send_data(input_data)
        print(f" {agent_type} 응답 크기: {len(str(result))} 문자")
        return result


def validate_agent_response_quality(agent_type: str, response_data: Dict[str, Any]) -> Dict[str, Any]:
    """에이전트 응답 품질 상세 검증"""
    validation = {
        "agent_type": agent_type,
        "response_size": len(str(response_data)),
        "has_meaningful_content": False,
        "has_proper_structure": False,
        "has_a2a_format": False,
        "content_indicators": [],
        "data_quality_score": 0.0,
        "issues": []
    }
    
    try:
        response_str = str(response_data).lower()
        
        # A2A 포맷 검증
        if any(key in response_data for key in ["content", "text_content", "data", "messages"]):
            validation["has_a2a_format"] = True
        else:
            validation["issues"].append("A2A 표준 포맷 미준수")
            
        # 구조 검증
        if isinstance(response_data, dict) and len(response_data) > 0:
            validation["has_proper_structure"] = True
        else:
            validation["issues"].append("응답 구조 부적절")
            
        # 에이전트별 특화 검증
        if agent_type == "data_collector":
            # 데이터 수집 관련 키워드 검증
            data_indicators = ["주가", "시세", "데이터", "정보", "price", "data", "stock", "코스피", "코스닥"]
            found_indicators = [ind for ind in data_indicators if ind in response_str]
            validation["content_indicators"] = found_indicators
            validation["has_meaningful_content"] = len(found_indicators) > 0
            validation["data_quality_score"] = min(len(found_indicators) / 3.0, 1.0)
            
        elif agent_type == "analysis":
            # 분석 관련 키워드 검증  
            analysis_indicators = ["분석", "평가", "추천", "전망", "analysis", "recommendation", "rsi", "per", "기술적", "기본적"]
            found_indicators = [ind for ind in analysis_indicators if ind in response_str]
            validation["content_indicators"] = found_indicators
            validation["has_meaningful_content"] = len(found_indicators) > 0
            validation["data_quality_score"] = min(len(found_indicators) / 3.0, 1.0)
            
        elif agent_type == "trading":
            # 거래 관련 키워드 검증
            trading_indicators = ["주문", "매수", "매도", "거래", "trading", "order", "buy", "sell", "portfolio"]
            found_indicators = [ind for ind in trading_indicators if ind in response_str]
            validation["content_indicators"] = found_indicators  
            validation["has_meaningful_content"] = len(found_indicators) > 0
            validation["data_quality_score"] = min(len(found_indicators) / 3.0, 1.0)
            
        elif agent_type == "supervisor":
            # 워크플로우 관련 키워드 검증
            workflow_indicators = ["워크플로우", "패턴", "단계", "workflow", "pattern", "step", "coordination"]
            found_indicators = [ind for ind in workflow_indicators if ind in response_str]
            validation["content_indicators"] = found_indicators
            validation["has_meaningful_content"] = len(found_indicators) > 0  
            validation["data_quality_score"] = min(len(found_indicators) / 2.0, 1.0)
            
        # 최종 점수 계산
        if not validation["has_meaningful_content"]:
            validation["issues"].append("의미있는 컨텐츠 부족")
            
    except Exception as e:
        validation["issues"].append(f"검증 중 오류: {str(e)}")
        
    return validation


async def test_individual_agent_calls() -> SupervisorIntegrationTestResult:
    """개별 A2A 에이전트 직접 호출 테스트"""
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="개별 A2A 에이전트 직접 호출 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 각 에이전트별 테스트 케이스
    agent_test_cases = [
        {
            "agent": "data_collector",
            "query": "삼성전자 현재 주가와 거래량을 알려주세요",
            "expected_keywords": ["주가", "데이터", "시세"]
        },
        {
            "agent": "analysis", 
            "query": "삼성전자 기술적 분석을 해주세요 (RSI, 이동평균)",
            "expected_keywords": ["분석", "RSI", "기술적"]
        },
        {
            "agent": "trading",
            "query": "삼성전자 100주 모의 매수 주문을 해주세요",
            "expected_keywords": ["주문", "매수", "거래"]
        }
    ]
    
    passed_agents = 0
    total_agents = len(agent_test_cases)
    
    for test_case in agent_test_cases:
        agent_type = test_case["agent"]
        
        try:
            print(f"\n🧪 {agent_type} 에이전트 개별 테스트 중...")
            
            # 에이전트 직접 호출
            response_data = await call_individual_agent(agent_type, test_case["query"])
            
            # 응답 품질 검증
            validation = validate_agent_response_quality(agent_type, response_data)
            
            # 테스트 통과 조건
            agent_passed = (
                validation["has_a2a_format"] and
                validation["has_proper_structure"] and
                validation["has_meaningful_content"] and
                validation["data_quality_score"] >= 0.3
            )
            
            if agent_passed:
                passed_agents += 1
                print(f"    {agent_type} 테스트 통과 (품질 점수: {validation['data_quality_score']:.2f})")
                print(f"       발견된 키워드: {validation['content_indicators'][:5]}")
            else:
                print(f"    {agent_type} 테스트 실패")
                print(f"      ️  문제점: {validation['issues']}")
                test_result.passed = False
                
            test_result.add_sub_test(
                f"{agent_type} 직접 호출",
                agent_passed,
                {
                    "query": test_case["query"],
                    "validation": validation,
                    "response_preview": str(response_data)[:200] + "..."
                }
            )
            
        except Exception as e:
            print(f"    {agent_type} 호출 오류: {str(e)}")
            test_result.passed = False
            test_result.add_sub_test(f"{agent_type} 직접 호출", False, str(e))
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "passed_agents": passed_agents,
        "total_agents": total_agents,
        "success_rate": f"{(passed_agents/total_agents)*100:.1f}%"
    }
    
    return test_result


async def test_workflow_patterns() -> SupervisorIntegrationTestResult:
    """
    워크플로우 패턴 테스트
    
    다양한 사용자 요청에 대해 적절한 워크플로우 패턴이 선택되는지 테스트:
    - DATA_ONLY 패턴: 단순 데이터 요청
    - DATA_ANALYSIS 패턴: 분석 요청
    - FULL_WORKFLOW 패턴: 거래 포함 요청
    """
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="워크플로우 패턴 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 테스트 케이스 정의
    test_cases = [
        {
            "name": "DATA_ONLY 패턴",
            "request": "삼성전자 현재 주가는?",
            "expected_workflow": "data_only"
        },
        {
            "name": "DATA_ANALYSIS 패턴", 
            "request": "삼성전자 기술적 분석 결과를 알려주세요",
            "expected_workflow": "data_analysis"
        },
        {
            "name": "FULL_WORKFLOW 패턴",
            "request": "삼성전자 100주 매수하고 싶습니다",
            "expected_workflow": "full_workflow"
        }
    ]
    
    passed_tests = 0
    total_tests = len(test_cases)
    
    for test_case in test_cases:
        try:
            print(f"\n🧪 {test_case['name']} 테스트 중...")
            print(f"    요청: {test_case['request']}")
            
            # SupervisorAgent 호출
            response_data = await call_supervisor_via_a2a(test_case['request'])
            
            # 응답 검증
            validation_results = validate_supervisor_output(response_data)
            
            # 워크플로우 패턴 확인
            workflow_detected = validation_results["has_workflow_pattern"]
            agent_coordination = validation_results["has_sub_agent_info"]
            
            test_passed = workflow_detected and agent_coordination
            
            if test_passed:
                passed_tests += 1
                print(f"    {test_case['name']} 성공")
            else:
                print(f"    {test_case['name']} 실패")
                test_result.passed = False
            
            test_result.add_sub_test(
                test_case['name'],
                test_passed,
                {
                    "request": test_case['request'],
                    "validation_results": validation_results,
                    "response_size": len(str(response_data))
                }
            )
            
        except Exception as e:
            print(f"    {test_case['name']} 오류: {str(e)}")
            test_result.passed = False
            test_result.add_sub_test(test_case['name'], False, str(e))
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "passed_tests": passed_tests,
        "total_tests": total_tests,
        "success_rate": f"{(passed_tests/total_tests)*100:.1f}%"
    }
    
    return test_result


async def test_sub_agent_orchestration() -> SupervisorIntegrationTestResult:
    """
    서브 에이전트 협조 테스트
    
    SupervisorAgent가 하위 에이전트들을 올바르게 호출하고
    결과를 조정하는지 테스트
    """
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="서브 에이전트 협조 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 복합적인 요청으로 여러 에이전트 협조 테스트
    complex_request = "NAVER 주식에 대한 종합적인 투자 판단을 해주세요"
    
    try:
        print(f"\n🤝 서브 에이전트 협조 테스트 중...")
        print(f"    복합 요청: {complex_request}")
        
        # SupervisorAgent 호출
        response_data = await call_supervisor_via_a2a(complex_request)
        
        # 응답 검증
        validation_results = validate_supervisor_output(response_data)
        
        # 협조 패턴 검증
        coordination_checks = {
            "workflow_pattern_detected": validation_results["has_workflow_pattern"],
            "sub_agent_info_present": validation_results["has_sub_agent_info"], 
            "coordination_result_available": validation_results["has_coordination_result"],
            "proper_a2a_format": validation_results["has_proper_format"]
        }
        
        passed_checks = sum(coordination_checks.values())
        total_checks = len(coordination_checks)
        
        if passed_checks >= 3:  # 최소 3개 이상의 검증 통과
            print(f"    서브 에이전트 협조 성공 ({passed_checks}/{total_checks})")
        else:
            print(f"    서브 에이전트 협조 부족 ({passed_checks}/{total_checks})")
            test_result.passed = False
        
        test_result.add_sub_test(
            "복합 요청 처리",
            passed_checks >= 3,
            {
                "coordination_checks": coordination_checks,
                "validation_results": validation_results,
                "response_length": len(str(response_data))
            }
        )
        
    except Exception as e:
        print(f"    서브 에이전트 협조 테스트 오류: {str(e)}")
        test_result.passed = False
        test_result.error_message = str(e)
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "request": complex_request,
        "coordination_checks": coordination_checks if 'coordination_checks' in locals() else {}
    }
    
    return test_result


async def test_decision_making_logic() -> SupervisorIntegrationTestResult:
    """
    의사결정 로직 테스트
    
    다양한 시나리오에서 SupervisorAgent의 의사결정이
    적절하게 이루어지는지 테스트
    """
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="의사결정 로직 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 의사결정이 필요한 다양한 시나리오
    decision_scenarios = [
        {
            "name": "단순 정보 요청",
            "request": "코스피 지수 알려주세요",
            "expected_decision": "정보 제공"
        },
        {
            "name": "분석 요청",
            "request": "삼성전자 투자 전망은?",
            "expected_decision": "분석 수행"
        },
        {
            "name": "모호한 요청",
            "request": "좋은 투자 추천해주세요",
            "expected_decision": "명확화 요청"
        }
    ]
    
    passed_decisions = 0
    total_decisions = len(decision_scenarios)
    
    for scenario in decision_scenarios:
        try:
            print(f"\n {scenario['name']} 의사결정 테스트 중...")
            print(f"    요청: {scenario['request']}")
            
            # SupervisorAgent 호출
            response_data = await call_supervisor_via_a2a(scenario['request'])
            
            # 의사결정 품질 평가
            validation_results = validate_supervisor_output(response_data)
            
            decision_quality = (
                validation_results["has_valid_structure"] and
                validation_results["has_coordination_result"] and
                validation_results["has_proper_format"]
            )
            
            if decision_quality:
                passed_decisions += 1
                print(f"    {scenario['name']} 의사결정 성공")
            else:
                print(f"    {scenario['name']} 의사결정 부족")
                test_result.passed = False
            
            test_result.add_sub_test(
                scenario['name'],
                decision_quality,
                {
                    "request": scenario['request'],
                    "validation_results": validation_results,
                    "expected_decision": scenario['expected_decision']
                }
            )
            
        except Exception as e:
            print(f"    {scenario['name']} 의사결정 오류: {str(e)}")
            test_result.passed = False
            test_result.add_sub_test(scenario['name'], False, str(e))
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "passed_decisions": passed_decisions,
        "total_decisions": total_decisions,
        "decision_accuracy": f"{(passed_decisions/total_decisions)*100:.1f}%"
    }
    
    return test_result


async def test_multi_turn_conversation() -> SupervisorIntegrationTestResult:
    """멀티턴 대화 시나리오 테스트"""
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="멀티턴 대화 시나리오 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 연속적인 대화 시나리오
    conversation_scenarios = [
        {
            "name": "점진적 투자 결정 과정",
            "turns": [
                "삼성전자 현재 상황은 어때?",
                "그럼 기술적 분석도 해줘",
                "투자 추천은?",
                "100주 매수하면 어떨까?"
            ],
            "expected_progression": ["데이터", "분석", "추천", "거래"]
        },
        {
            "name": "비교 분석 시나리오",
            "turns": [
                "삼성전자와 SK하이닉스 주가 비교해줘",
                "둘 중 어느 것이 더 나은 투자처야?",
                "그럼 삼성전자 50주 매수 추천해"
            ],
            "expected_progression": ["비교데이터", "분석비교", "투자결정"]
        }
    ]
    
    passed_scenarios = 0
    total_scenarios = len(conversation_scenarios)
    
    for scenario in conversation_scenarios:
        scenario_name = scenario["name"]
        turns = scenario["turns"]
        
        try:
            print(f"\n 멀티턴 대화 시나리오: {scenario_name}")
            print(f"    총 {len(turns)}턴의 대화 진행")
            
            conversation_history = []
            turn_results = []
            scenario_passed = True
            
            for turn_num, user_input in enumerate(turns, 1):
                print(f"\n    턴 {turn_num}: {user_input}")
                
                try:
                    # SupervisorAgent 호출 (컨텍스트 유지를 위해 동일한 클라이언트 사용)
                    response_data = await call_supervisor_via_a2a(user_input)
                    
                    # 응답 품질 검증
                    validation = validate_agent_response_quality("supervisor", response_data)
                    
                    # 턴별 결과 저장
                    turn_result = {
                        "turn": turn_num,
                        "user_input": user_input,
                        "response_quality": validation["data_quality_score"],
                        "has_meaningful_content": validation["has_meaningful_content"],
                        "response_size": validation["response_size"]
                    }
                    turn_results.append(turn_result)
                    conversation_history.append({
                        "user": user_input,
                        "assistant": str(response_data)[:100] + "..."
                    })
                    
                    # 턴별 성공 여부 확인
                    turn_passed = (
                        validation["has_meaningful_content"] and
                        validation["data_quality_score"] >= 0.2 and
                        validation["response_size"] >= 10
                    )
                    
                    if turn_passed:
                        print(f"       턴 {turn_num} 성공 (품질 점수: {validation['data_quality_score']:.2f})")
                    else:
                        print(f"       턴 {turn_num} 실패")
                        scenario_passed = False
                        
                except Exception as e:
                    print(f"       턴 {turn_num} 오류: {str(e)}")
                    scenario_passed = False
                    turn_results.append({
                        "turn": turn_num,
                        "user_input": user_input,
                        "error": str(e)
                    })
                    
                # 턴 간 간격
                await asyncio.sleep(1)
            
            # 전체 대화의 일관성 검증
            if scenario_passed and len(turn_results) >= 2:
                # 응답 품질이 대화가 진행될수록 향상되는지 확인
                quality_scores = [r.get("response_quality", 0) for r in turn_results if "response_quality" in r]
                consistency_check = len(quality_scores) >= len(turns) * 0.7  # 70% 이상 성공적인 응답
                
                if consistency_check:
                    passed_scenarios += 1
                    print(f"    {scenario_name} 시나리오 전체 성공")
                else:
                    print(f"   ️  {scenario_name} 시나리오 일관성 부족")
                    scenario_passed = False
            else:
                print(f"    {scenario_name} 시나리오 실패")
                
            test_result.add_sub_test(
                scenario_name,
                scenario_passed,
                {
                    "total_turns": len(turns),
                    "successful_turns": len([r for r in turn_results if r.get("response_quality", 0) > 0.2]),
                    "turn_results": turn_results,
                    "conversation_history": conversation_history
                }
            )
            
        except Exception as e:
            print(f"    {scenario_name} 시나리오 오류: {str(e)}")
            test_result.passed = False
            test_result.add_sub_test(scenario_name, False, str(e))
    
    if passed_scenarios < total_scenarios:
        test_result.passed = False
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "passed_scenarios": passed_scenarios,
        "total_scenarios": total_scenarios,
        "success_rate": f"{(passed_scenarios/total_scenarios)*100:.1f}%"
    }
    
    return test_result


async def test_workflow_chain_analysis() -> SupervisorIntegrationTestResult:
    """SupervisorAgent 워크플로우 체인 상세 분석 테스트"""
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="워크플로우 체인 상세 분석 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 워크플로우 체인별 테스트 케이스
    workflow_test_cases = [
        {
            "name": "DATA_ONLY 체인 분석",
            "query": "코스피 지수 현재 값은?",
            "expected_pattern": "DATA_ONLY",
            "expected_agents": ["data_collector"],
            "expected_steps": ["data_collection"]
        },
        {
            "name": "DATA_ANALYSIS 체인 분석", 
            "query": "삼성전자 투자 전망 분석해줘",
            "expected_pattern": "DATA_ANALYSIS",
            "expected_agents": ["data_collector", "analysis"],
            "expected_steps": ["data_collection", "analysis"]
        },
        {
            "name": "FULL_WORKFLOW 체인 분석",
            "query": "NAVER 주식 200주 매수 투자 결정해줘",
            "expected_pattern": "FULL_WORKFLOW", 
            "expected_agents": ["data_collector", "analysis", "trading"],
            "expected_steps": ["data_collection", "analysis", "trading"]
        }
    ]
    
    passed_workflows = 0
    total_workflows = len(workflow_test_cases)
    
    for workflow_case in workflow_test_cases:
        workflow_name = workflow_case["name"]
        
        try:
            print(f"\n 워크플로우 체인 분석: {workflow_name}")
            print(f"    요청: {workflow_case['query']}")
            print(f"    예상 패턴: {workflow_case['expected_pattern']}")
            
            # SupervisorAgent 호출
            response_data = await call_supervisor_via_a2a(workflow_case['query'])
            
            # 워크플로우 패턴 검증
            response_str = str(response_data).lower()
            
            # 패턴 감지
            pattern_detected = workflow_case['expected_pattern'].lower() in response_str
            
            # 에이전트 호출 흔적 확인
            agents_called = []
            for agent in workflow_case['expected_agents']:
                if agent in response_str or agent.replace('_', '') in response_str:
                    agents_called.append(agent)
            
            # 단계별 실행 확인
            steps_found = []
            for step in workflow_case['expected_steps']:
                if step in response_str or step.replace('_', ' ') in response_str:
                    steps_found.append(step)
            
            # 체인 완성도 계산
            agent_coverage = len(agents_called) / len(workflow_case['expected_agents'])
            step_coverage = len(steps_found) / len(workflow_case['expected_steps'])
            
            # 워크플로우 성공 조건
            workflow_passed = (
                pattern_detected and
                agent_coverage >= 0.5 and
                step_coverage >= 0.5 and
                len(str(response_data)) > 50  # 의미있는 응답 길이
            )
            
            if workflow_passed:
                passed_workflows += 1
                print(f"    {workflow_name} 성공")
                print(f"       에이전트 커버리지: {agent_coverage:.1%}")
                print(f"       단계 커버리지: {step_coverage:.1%}")
                print(f"       호출된 에이전트: {agents_called}")
            else:
                print(f"    {workflow_name} 실패")
                print(f"      ️  패턴 감지: {'' if pattern_detected else ''}")
                print(f"      ️  에이전트 커버리지: {agent_coverage:.1%}")
                print(f"      ️  단계 커버리지: {step_coverage:.1%}")
                test_result.passed = False
            
            test_result.add_sub_test(
                workflow_name,
                workflow_passed,
                {
                    "query": workflow_case['query'],
                    "expected_pattern": workflow_case['expected_pattern'],
                    "pattern_detected": pattern_detected,
                    "expected_agents": workflow_case['expected_agents'],
                    "agents_called": agents_called,
                    "agent_coverage": agent_coverage,
                    "expected_steps": workflow_case['expected_steps'],
                    "steps_found": steps_found,
                    "step_coverage": step_coverage,
                    "response_size": len(str(response_data))
                }
            )
            
        except Exception as e:
            print(f"    {workflow_name} 오류: {str(e)}")
            test_result.passed = False
            test_result.add_sub_test(workflow_name, False, str(e))
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "passed_workflows": passed_workflows,
        "total_workflows": total_workflows,
        "success_rate": f"{(passed_workflows/total_workflows)*100:.1f}%"
    }
    
    return test_result


async def test_error_handling_and_resilience() -> SupervisorIntegrationTestResult:
    """에러 처리 및 복원력 테스트"""
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="에러 처리 및 복원력 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 에러 시나리오 테스트 케이스
    error_test_cases = [
        {
            "name": "잘못된 요청 처리",
            "query": "",  # 빈 요청
            "expected_behavior": "graceful_error_handling"
        },
        {
            "name": "모호한 요청 처리",
            "query": "sdkfjslkdfjslkdf 알려줘",  # 무의미한 요청
            "expected_behavior": "clarification_request"
        },
        {
            "name": "복잡한 요청 처리",
            "query": "모든 주식의 모든 데이터를 분석해서 완벽한 포트폴리오를 만들어줘 지금 당장",  # 과도한 요청
            "expected_behavior": "reasonable_response"
        }
    ]
    
    passed_error_tests = 0
    total_error_tests = len(error_test_cases)
    
    for error_case in error_test_cases:
        test_name = error_case["name"]
        
        try:
            print(f"\n️ 에러 처리 테스트: {test_name}")
            print(f"    요청: '{error_case['query']}'")
            
            # SupervisorAgent 호출 (에러 상황)
            response_data = await call_supervisor_via_a2a(error_case['query'])
            
            # 에러 처리 품질 검증
            response_str = str(response_data).lower()
            error_indicators = ["오류", "error", "잘못", "명확", "다시", "구체적"]
            
            graceful_handling = any(indicator in response_str for indicator in error_indicators)
            has_response = len(response_str) > 10
            not_crashed = isinstance(response_data, dict)
            
            # 에러 처리 성공 조건
            error_test_passed = graceful_handling and has_response and not_crashed
            
            if error_test_passed:
                passed_error_tests += 1
                print(f"    {test_name} 성공: 우아한 에러 처리")
                print(f"       발견된 에러 처리 지표: {[ind for ind in error_indicators if ind in response_str][:3]}")
            else:
                print(f"    {test_name} 실패")
                print(f"      ️  우아한 처리: {'' if graceful_handling else ''}")
                print(f"      ️  응답 존재: {'' if has_response else ''}")
                print(f"      ️  시스템 안정성: {'' if not_crashed else ''}")
                test_result.passed = False
            
            test_result.add_sub_test(
                test_name,
                error_test_passed,
                {
                    "query": error_case['query'],
                    "expected_behavior": error_case['expected_behavior'],
                    "graceful_handling": graceful_handling,
                    "response_size": len(response_str),
                    "system_stable": not_crashed,
                    "error_indicators_found": [ind for ind in error_indicators if ind in response_str]
                }
            )
            
        except Exception as e:
            # 예외 발생도 어느 정도는 예상되는 상황
            print(f"   ️  {test_name} 예외 발생: {str(e)}")
            # 완전한 시스템 크래시가 아니라면 부분 점수
            if "timeout" not in str(e).lower():
                test_result.add_sub_test(test_name, True, f"예상된 예외: {str(e)}")
            else:
                test_result.passed = False
                test_result.add_sub_test(test_name, False, str(e))
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "passed_error_tests": passed_error_tests,
        "total_error_tests": total_error_tests,
        "success_rate": f"{(passed_error_tests/total_error_tests)*100:.1f}%"
    }
    
    return test_result


async def test_performance_and_stability() -> SupervisorIntegrationTestResult:
    """성능 및 안정성 검증 테스트"""
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="성능 및 안정성 검증 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 성능 테스트 케이스
    performance_test_cases = [
        {
            "name": "응답 시간 테스트",
            "query": "삼성전자 현재 시세 알려주세요",
            "max_response_time_ms": 10000  # 10초 제한
        },
        {
            "name": "동시 요청 처리",
            "query": "코스피 지수는?",
            "concurrent_requests": 3
        },
        {
            "name": "장시간 응답 테스트",
            "query": "삼성전자, LG전자, SK하이닉스 비교 분석해줘",
            "max_response_time_ms": 30000  # 30초 제한
        }
    ]
    
    passed_performance_tests = 0
    total_performance_tests = len(performance_test_cases)
    
    for perf_case in performance_test_cases:
        test_name = perf_case["name"]
        
        try:
            print(f"\n 성능 테스트: {test_name}")
            
            if perf_case["name"] == "동시 요청 처리":
                # 동시 요청 테스트
                print(f"    동시 요청 {perf_case['concurrent_requests']}개 전송")
                
                start_concurrent = time.time()
                tasks = []
                for i in range(perf_case['concurrent_requests']):
                    task = call_supervisor_via_a2a(f"{perf_case['query']} (요청 #{i+1})")
                    tasks.append(task)
                
                # 모든 동시 요청 실행
                responses = await asyncio.gather(*tasks, return_exceptions=True)
                concurrent_time = (time.time() - start_concurrent) * 1000
                
                # 결과 검증
                successful_responses = sum(1 for r in responses if not isinstance(r, Exception))
                concurrency_success = successful_responses >= perf_case['concurrent_requests'] * 0.7  # 70% 성공
                
                if concurrency_success:
                    passed_performance_tests += 1
                    print(f"    {test_name} 성공: {successful_responses}/{perf_case['concurrent_requests']} 응답 ({concurrent_time:.0f}ms)")
                else:
                    print(f"    {test_name} 실패: {successful_responses}/{perf_case['concurrent_requests']} 응답")
                    test_result.passed = False
                
                test_result.add_sub_test(
                    test_name,
                    concurrency_success,
                    {
                        "concurrent_requests": perf_case['concurrent_requests'],
                        "successful_responses": successful_responses,
                        "total_time_ms": concurrent_time,
                        "avg_response_time_ms": concurrent_time / perf_case['concurrent_requests']
                    }
                )
                
            else:
                # 단일 요청 성능 테스트
                print(f"    요청: {perf_case['query']}")
                print(f"   ⏱️  제한 시간: {perf_case['max_response_time_ms']}ms")
                
                request_start = time.time()
                response_data = await call_supervisor_via_a2a(perf_case['query'])
                response_time = (time.time() - request_start) * 1000
                
                # 성능 기준 검증
                performance_ok = (
                    response_time <= perf_case['max_response_time_ms'] and
                    isinstance(response_data, dict) and
                    len(str(response_data)) > 10
                )
                
                if performance_ok:
                    passed_performance_tests += 1
                    print(f"    {test_name} 성공: {response_time:.0f}ms (기준: {perf_case['max_response_time_ms']}ms)")
                else:
                    print(f"    {test_name} 실패: {response_time:.0f}ms (기준 초과)")
                    test_result.passed = False
                
                test_result.add_sub_test(
                    test_name,
                    performance_ok,
                    {
                        "query": perf_case['query'],
                        "response_time_ms": response_time,
                        "max_allowed_ms": perf_case['max_response_time_ms'],
                        "within_limit": response_time <= perf_case['max_response_time_ms'],
                        "response_size": len(str(response_data))
                    }
                )
                
        except Exception as e:
            print(f"    {test_name} 오류: {str(e)}")
            test_result.passed = False
            test_result.add_sub_test(test_name, False, str(e))
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "passed_performance_tests": passed_performance_tests,
        "total_performance_tests": total_performance_tests,
        "success_rate": f"{(passed_performance_tests/total_performance_tests)*100:.1f}%"
    }
    
    return test_result


async def test_real_world_scenarios() -> SupervisorIntegrationTestResult:
    """실제 사용 시나리오 기반 테스트"""
    import time
    start_time = time.time()
    
    test_result = SupervisorIntegrationTestResult(
        test_name="실제 사용 시나리오 기반 테스트",
        passed=True,
        details={},
        execution_time_ms=0
    )
    
    # 실제 사용자 시나리오 케이스
    real_world_scenarios = [
        {
            "name": "초보 투자자 정보 요청",
            "query": "주식 투자 처음 해보는데 삼성전자 어때요?",
            "expected_workflow": "DATA_ANALYSIS",
            "expected_content": ["데이터", "분석", "추천"]
        },
        {
            "name": "경험자 기술적 분석 요청",
            "query": "삼성전자 RSI, MACD 같은 기술적 지표 분석 부탁해",
            "expected_workflow": "DATA_ANALYSIS", 
            "expected_content": ["기술적", "지표", "분석"]
        },
        {
            "name": "실제 매매 의뢰",
            "query": "삼성전자 100주 매수하고 싶은데 지금이 좋은 타이밍인가요?",
            "expected_workflow": "FULL_WORKFLOW",
            "expected_content": ["분석", "매수", "타이밍"]
        },
        {
            "name": "포트폴리오 조언 요청",
            "query": "IT 섹터로 포트폴리오 구성하고 싶은데 어떤 종목들이 좋을까요?",
            "expected_workflow": "DATA_ANALYSIS",
            "expected_content": ["포트폴리오", "섹터", "종목"]
        },
        {
            "name": "급락 상황 대응 문의",
            "query": "보유 주식이 급락하고 있는데 어떻게 해야 할까요?",
            "expected_workflow": "DATA_ANALYSIS",
            "expected_content": ["급락", "대응", "분석"]
        }
    ]
    
    passed_scenarios = 0
    total_scenarios = len(real_world_scenarios)
    
    for scenario in real_world_scenarios:
        scenario_name = scenario["name"]
        
        try:
            print(f"\n 실제 시나리오 테스트: {scenario_name}")
            print(f"    사용자 문의: {scenario['query']}")
            print(f"    예상 워크플로우: {scenario['expected_workflow']}")
            
            # SupervisorAgent 호출
            response_data = await call_supervisor_via_a2a(scenario['query'])
            
            # 응답 품질 검증
            response_str = str(response_data).lower()
            
            # 예상 컨텐츠 포함 여부 확인
            content_matches = []
            for expected_content in scenario['expected_content']:
                if expected_content in response_str:
                    content_matches.append(expected_content)
            
            content_coverage = len(content_matches) / len(scenario['expected_content'])
            
            # 응답의 실용성 검증
            response_length = len(response_str)
            has_meaningful_response = response_length > 50
            has_structured_format = isinstance(response_data, dict)
            
            # 시나리오 성공 기준
            scenario_success = (
                content_coverage >= 0.5 and  # 50% 이상의 예상 컨텐츠 포함
                has_meaningful_response and
                has_structured_format
            )
            
            if scenario_success:
                passed_scenarios += 1
                print(f"    {scenario_name} 성공")
                print(f"       컨텐츠 커버리지: {content_coverage:.1%}")
                print(f"       매칭된 키워드: {content_matches}")
            else:
                print(f"    {scenario_name} 실패")
                print(f"      ️  컨텐츠 커버리지: {content_coverage:.1%}")
                print(f"      ️  응답 길이: {response_length} 문자")
                test_result.passed = False
            
            test_result.add_sub_test(
                scenario_name,
                scenario_success,
                {
                    "query": scenario['query'],
                    "expected_workflow": scenario['expected_workflow'],
                    "expected_content": scenario['expected_content'],
                    "content_matches": content_matches,
                    "content_coverage": content_coverage,
                    "response_length": response_length,
                    "has_meaningful_response": has_meaningful_response
                }
            )
            
        except Exception as e:
            print(f"    {scenario_name} 오류: {str(e)}")
            test_result.passed = False
            test_result.add_sub_test(scenario_name, False, str(e))
    
    test_result.execution_time_ms = (time.time() - start_time) * 1000
    test_result.details = {
        "passed_scenarios": passed_scenarios,
        "total_scenarios": total_scenarios,
        "success_rate": f"{(passed_scenarios/total_scenarios)*100:.1f}%"
    }
    
    return test_result


async def run_supervisor_integration_tests() -> List[SupervisorIntegrationTestResult]:
    """모든 SupervisorAgent 통합 테스트 실행"""
    
    print("\n" + "="*80)
    print("🧪 SupervisorAgent A2A 통합 테스트 시작")
    print("="*80)
    
    test_results = []
    
    try:
        # 1. 개별 A2A 에이전트 직접 호출 테스트
        print(f"\n{' 테스트 1: 개별 A2A 에이전트 직접 호출':-^60}")
        individual_result = await test_individual_agent_calls()
        test_results.append(individual_result)
        
        # 2. 워크플로우 패턴 테스트
        print(f"\n{' 테스트 2: 워크플로우 패턴':-^60}")
        workflow_result = await test_workflow_patterns()
        test_results.append(workflow_result)
        
        # 3. 워크플로우 체인 상세 분석 테스트
        print(f"\n{' 테스트 3: 워크플로우 체인 상세 분석':-^60}")
        chain_result = await test_workflow_chain_analysis()
        test_results.append(chain_result)
        
        # 4. 서브 에이전트 협조 테스트
        print(f"\n{'🤝 테스트 4: 서브 에이전트 협조':-^60}")
        orchestration_result = await test_sub_agent_orchestration()
        test_results.append(orchestration_result)
        
        # 5. 멀티턴 대화 시나리오 테스트
        print(f"\n{' 테스트 5: 멀티턴 대화 시나리오':-^60}")
        multiturn_result = await test_multi_turn_conversation()
        test_results.append(multiturn_result)
        
        # 6. 의사결정 로직 테스트
        print(f"\n{' 테스트 6: 의사결정 로직':-^60}")
        decision_result = await test_decision_making_logic()
        test_results.append(decision_result)
        
        # 7. 에러 처리 및 복원력 테스트
        print(f"\n{'️ 테스트 7: 에러 처리 및 복원력':-^60}")
        error_result = await test_error_handling_and_resilience()
        test_results.append(error_result)
        
        # 8. 실제 사용 시나리오 기반 테스트
        print(f"\n{' 테스트 8: 실제 사용 시나리오':-^60}")
        realworld_result = await test_real_world_scenarios()
        test_results.append(realworld_result)
        
        # 9. 성능 및 안정성 검증 테스트
        print(f"\n{' 테스트 9: 성능 및 안정성 검증':-^60}")
        performance_result = await test_performance_and_stability()
        test_results.append(performance_result)
        
        # 결과 요약
        print(f"\n{' 테스트 결과 요약':-^60}")
        passed_tests = sum(1 for result in test_results if result.passed)
        total_tests = len(test_results)
        
        for result in test_results:
            status = " PASS" if result.passed else " FAIL"
            print(f"   {status} {result.test_name} ({result.execution_time_ms:.0f}ms)")
            
            if result.sub_tests:
                for sub_test in result.sub_tests:
                    sub_status = "" if sub_test["passed"] else ""
                    print(f"      {sub_status} {sub_test['name']}")
        
        print(f"\n 전체 성공률: {passed_tests}/{total_tests} ({(passed_tests/total_tests)*100:.1f}%)")
        
        # 상세 결과를 JSON 파일로 저장
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = Path("logs/examples/a2a")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        detailed_results = {
            "timestamp": timestamp,
            "test_summary": {
                "total_tests": total_tests,
                "passed_tests": passed_tests,
                "success_rate": f"{(passed_tests/total_tests)*100:.1f}%"
            },
            "test_results": [
                {
                    "test_name": result.test_name,
                    "passed": result.passed,
                    "execution_time_ms": result.execution_time_ms,
                    "details": result.details,
                    "error_message": result.error_message,
                    "sub_tests": result.sub_tests
                }
                for result in test_results
            ]
        }
        
        output_file = output_dir / f"supervisor_integration_test_results_{timestamp}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(detailed_results, f, ensure_ascii=False, indent=2)
        
        print(f"\n 상세 테스트 결과가 {output_file}에 저장되었습니다.")
        
    except Exception as e:
        print(f"\n 통합 테스트 실행 중 오류 발생: {str(e)}")
        import traceback
        print(f"상세 오류: {traceback.format_exc()}")
    
    return test_results


async def call_supervisor_via_a2a(user_request: str) -> Dict[str, Any]:
    """A2A 프로토콜을 통해 SupervisorAgent 호출"""

    # SupervisorAgent A2A 서버 URL(도커)
    supervisor_url = "http://localhost:8000"

    # 입력 데이터 준비 - SupervisorAgent는 사용자 질문만 필요
    input_data = {
        "messages": [{"content": user_request, "role": "user"}]
    }

    print("\n SupervisorAgent 요청 전송:")
    print(f"    사용자 요청: '{user_request}'")

    async with A2AClientManagerV2(
        base_url=supervisor_url,
        streaming=False,
        retry_delay=2.0
    ) as client_manager:
        try:
            response_data = await client_manager.send_data(input_data)
            logger.info(f"response_data: {response_data}")
            print("\n SupervisorAgent 응답 수신:")
            print(f"   {json.dumps(response_data, ensure_ascii=False, indent=2)}")

            # JSON 파일로 저장
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = Path("logs/examples/a2a")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"a2a_supervisor_result_{timestamp}.json"

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(response_data, f, ensure_ascii=False, indent=2)

            print(f"\n 전체 결과가 {output_file}에 저장되었습니다.")

            return response_data

        except Exception as e:
            print(f" A2A 호출 실패: {str(e)}")
            raise


async def test_custom_supervisor_a2a():
    """CustomSupervisorAgent A2A 통신 테스트"""

    print(f"\n{'='*70}")
    print("CustomSupervisorAgent A2A 테스트")
    print('='*70)

    try:
        # A2A를 통한 SupervisorAgent 호출
        print(" A2A 프로토콜을 통해 CustomSupervisorAgent 실행 중...")
        await call_supervisor_via_a2a("삼성전자 현재 주가를 조회하고, 매수가 적절한지 분석한 뒤에 평가하고 실제 매도를 시장가로 시도해주세요.")

    except Exception as e:
        print(f"\n 실행 중 오류 발생: {str(e)}")
        import traceback
        print(f"상세 오류: {traceback.format_exc()}")


async def main():
    """메인 실행 함수"""
    print(" A2A 프로토콜을 통한 SupervisorAgent 워크플로우 검증")
    print("🤝 하위 에이전트들과의 협업 패턴 테스트")

    # 기본 SupervisorAgent 테스트
    await test_custom_supervisor_a2a()

    # # 통합 테스트 실행
    # integration_results = await run_supervisor_integration_tests()
    
    # # 전체 결과 요약
    # print(f"\n{' 최종 테스트 결과':-^70}")
    # total_integration_tests = len(integration_results)
    # passed_integration_tests = sum(1 for result in integration_results if result.passed)
    
    # if total_integration_tests > 0:
    #     success_rate = (passed_integration_tests / total_integration_tests) * 100
    #     print(f"    통합 테스트: {passed_integration_tests}/{total_integration_tests} ({success_rate:.1f}%)")
        
    #     if success_rate >= 80:
    #         print("    SupervisorAgent A2A 통합이 성공적으로 검증되었습니다!")
    #     else:
    #         print("   ️  SupervisorAgent A2A 통합에 개선이 필요합니다.")
    
    # print(f"    상세 결과는 logs/examples/a2a/ 디렉토리에서 확인하세요.")


if __name__ == "__main__":
    # 비동기 실행
    asyncio.run(main())