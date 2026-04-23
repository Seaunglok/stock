#!/usr/bin/env python3
"""
A2A Integration Test Runner

모든 에이전트의 A2A 통합 테스트를 한 번에 실행하는 통합 테스트 러너입니다.
각 에이전트별 example 파일의 integration test를 순차적으로 실행하고
전체 결과를 종합하여 리포트를 생성합니다.

실행 전제 조건:
1. MCP 서버들이 실행 중이어야 함 (Docker compose로 실행됨)
2. 모든 A2A Agent 서버들이 Docker compose로 실행되어 있어야 함
   - SupervisorAgent: localhost:8000
   - DataCollectorAgent: localhost:8001
   - AnalysisAgent: localhost:8002
   - TradingAgent: localhost:8003

사용법:
    python examples/run_integration_tests.py
    python examples/run_integration_tests.py --agent supervisor
    python examples/run_integration_tests.py --parallel
"""

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logger = structlog.get_logger(__name__)


@dataclass 
class AgentTestSuite:
    """에이전트 테스트 스위트 정보"""
    name: str
    module_path: str
    test_function: str
    port: int
    description: str


@dataclass
class IntegratedTestResult:
    """통합 테스트 결과"""
    agent_name: str
    passed: bool
    execution_time_ms: float
    total_tests: int = 0
    passed_tests: int = 0
    error_message: Optional[str] = None
    detailed_results: Optional[List[Any]] = None
    
    @property
    def success_rate(self) -> float:
        """성공률 계산"""
        if self.total_tests == 0:
            return 0.0
        return (self.passed_tests / self.total_tests) * 100


class A2AIntegrationTestRunner:
    """A2A 통합 테스트 러너"""
    
    def __init__(self):
        self.test_suites = self._initialize_test_suites()
        self.results: List[IntegratedTestResult] = []
    
    def _initialize_test_suites(self) -> List[AgentTestSuite]:
        """테스트 스위트 초기화"""
        return [
            AgentTestSuite(
                name="SupervisorAgent",
                module_path="examples/supervisor/a2a_example.py",
                test_function="run_supervisor_integration_tests",
                port=8000,
                description="워크플로우 조정 및 서브 에이전트 협조"
            ),
            AgentTestSuite(
                name="DataCollectorAgent", 
                module_path="examples/data_collector/a2a_example.py",
                test_function="run_a2a_interface_tests",
                port=8001,
                description="시장 데이터 수집 및 A2A 인터페이스"
            ),
            AgentTestSuite(
                name="AnalysisAgent",
                module_path="examples/analysis/a2a_example.py", 
                test_function="run_analysis_integration_tests",
                port=8002,
                description="4차원 분석 및 카테고리 신호 생성"
            ),
            AgentTestSuite(
                name="TradingAgent",
                module_path="examples/trading/a2a_example.py",
                test_function="run_trading_integration_tests", 
                port=8003,
                description="HITL 승인 워크플로우 및 거래 실행"
            )
        ]
    
    async def check_agent_health(self, suite: AgentTestSuite) -> bool:
        """에이전트 서버 헬스 체크"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"http://localhost:{suite.port}/.well-known/agent-card.json"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        logger.info(f" {suite.name} 서버 응답 정상 (포트 {suite.port})")
                        return True
                    else:
                        logger.warning(f"️ {suite.name} 서버 응답 이상: {response.status}")
                        return False
        except Exception as e:
            logger.error(f" {suite.name} 헬스 체크 실패 (포트 {suite.port}): {e}")
            return False
    
    def _load_test_module(self, module_path: str):
        """테스트 모듈 동적 로드"""
        try:
            # 절대 경로로 변환
            absolute_path = project_root / module_path
            spec = importlib.util.spec_from_file_location("test_module", absolute_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.error(f"모듈 로드 실패 {module_path}: {e}")
            return None
    
    async def run_single_agent_test(self, suite: AgentTestSuite) -> IntegratedTestResult:
        """단일 에이전트 테스트 실행"""
        start_time = time.time()
        
        print(f"\n{'='*80}")
        print(f"🧪 {suite.name} 통합 테스트 시작")
        print(f"    포트: {suite.port}")
        print(f"    설명: {suite.description}")
        print('='*80)
        
        try:
            # 헬스 체크
            if not await self.check_agent_health(suite):
                return IntegratedTestResult(
                    agent_name=suite.name,
                    passed=False,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error_message=f"에이전트 서버 응답 없음 (포트 {suite.port})"
                )
            
            # 테스트 모듈 로드
            test_module = self._load_test_module(suite.module_path)
            if not test_module:
                return IntegratedTestResult(
                    agent_name=suite.name,
                    passed=False,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error_message="테스트 모듈 로드 실패"
                )
            
            # 테스트 함수 실행
            test_function = getattr(test_module, suite.test_function, None)
            if not test_function:
                return IntegratedTestResult(
                    agent_name=suite.name,
                    passed=False,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error_message=f"테스트 함수 '{suite.test_function}' 없음"
                )
            
            # 테스트 실행
            detailed_results = await test_function()
            
            # 결과 분석
            total_tests = len(detailed_results)
            passed_tests = sum(1 for result in detailed_results if result.passed)
            overall_passed = passed_tests == total_tests
            
            print(f"\n {suite.name} 테스트 완료: {passed_tests}/{total_tests} 성공")
            
            return IntegratedTestResult(
                agent_name=suite.name,
                passed=overall_passed,
                execution_time_ms=(time.time() - start_time) * 1000,
                total_tests=total_tests,
                passed_tests=passed_tests,
                detailed_results=detailed_results
            )
            
        except Exception as e:
            error_msg = f"테스트 실행 중 오류: {str(e)}"
            logger.error(f" {suite.name} 테스트 실패: {error_msg}")
            
            return IntegratedTestResult(
                agent_name=suite.name,
                passed=False,
                execution_time_ms=(time.time() - start_time) * 1000,
                error_message=error_msg
            )
    
    async def run_all_tests(self, selected_agents: Optional[List[str]] = None, 
                           parallel: bool = False) -> List[IntegratedTestResult]:
        """모든 에이전트 테스트 실행"""
        
        print(" A2A 통합 테스트 러너 시작")
        print("="*80)
        
        # 선택된 에이전트 필터링
        test_suites = self.test_suites
        if selected_agents:
            test_suites = [s for s in test_suites if s.name.lower() in 
                          [name.lower() for name in selected_agents]]
        
        print(f" 실행할 테스트: {len(test_suites)}개")
        for suite in test_suites:
            print(f"   • {suite.name} (포트 {suite.port})")
        
        # 테스트 실행
        if parallel:
            print("\n 병렬 실행 모드")
            tasks = [self.run_single_agent_test(suite) for suite in test_suites]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 예외 처리
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append(IntegratedTestResult(
                        agent_name=test_suites[i].name,
                        passed=False,
                        execution_time_ms=0,
                        error_message=str(result)
                    ))
                else:
                    processed_results.append(result)
            results = processed_results
        else:
            print("\n 순차 실행 모드")
            results = []
            for suite in test_suites:
                result = await self.run_single_agent_test(suite)
                results.append(result)
                
                # 실패 시 계속할지 확인 (순차 모드에서만)
                if not result.passed:
                    print(f"️ {suite.name} 테스트가 실패했습니다. 계속 진행합니다...")
        
        self.results = results
        return results
    
    def generate_report(self) -> Dict[str, Any]:
        """통합 테스트 리포트 생성"""
        if not self.results:
            return {"error": "테스트 결과가 없습니다"}
        
        total_agents = len(self.results)
        passed_agents = sum(1 for result in self.results if result.passed)
        overall_success_rate = (passed_agents / total_agents) * 100
        
        # 상세 통계
        total_individual_tests = sum(result.total_tests for result in self.results)
        passed_individual_tests = sum(result.passed_tests for result in self.results)
        individual_success_rate = ((passed_individual_tests / total_individual_tests) * 100 
                                 if total_individual_tests > 0 else 0)
        
        # 성능 통계
        execution_times = [result.execution_time_ms for result in self.results]
        total_time = sum(execution_times)
        avg_time = total_time / len(execution_times) if execution_times else 0
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_agents": total_agents,
                "passed_agents": passed_agents,
                "overall_success_rate": f"{overall_success_rate:.1f}%",
                "total_individual_tests": total_individual_tests,
                "passed_individual_tests": passed_individual_tests,
                "individual_success_rate": f"{individual_success_rate:.1f}%"
            },
            "performance": {
                "total_execution_time_ms": total_time,
                "average_execution_time_ms": avg_time,
                "max_execution_time_ms": max(execution_times) if execution_times else 0,
                "min_execution_time_ms": min(execution_times) if execution_times else 0
            },
            "agent_results": [
                {
                    "agent_name": result.agent_name,
                    "passed": result.passed,
                    "success_rate": f"{result.success_rate:.1f}%",
                    "execution_time_ms": result.execution_time_ms,
                    "total_tests": result.total_tests,
                    "passed_tests": result.passed_tests,
                    "error_message": result.error_message
                }
                for result in self.results
            ]
        }
        
        return report
    
    def print_summary(self, report: Dict[str, Any]):
        """테스트 결과 요약 출력"""
        print(f"\n{' 통합 테스트 결과 요약':-^80}")
        
        summary = report["summary"]
        performance = report["performance"]
        
        print(f"    에이전트 성공률: {summary['passed_agents']}/{summary['total_agents']} ({summary['overall_success_rate']})")
        print(f"    개별 테스트 성공률: {summary['passed_individual_tests']}/{summary['total_individual_tests']} ({summary['individual_success_rate']})")
        print(f"   ⏱️ 총 실행 시간: {performance['total_execution_time_ms']:.0f}ms")
        print(f"    평균 실행 시간: {performance['average_execution_time_ms']:.0f}ms/agent")
        
        print(f"\n{' 에이전트별 상세 결과':-^60}")
        for agent_result in report["agent_results"]:
            status = " PASS" if agent_result["passed"] else " FAIL"
            print(f"   {status} {agent_result['agent_name']:<20} "
                  f"{agent_result['success_rate']:>8} "
                  f"({agent_result['execution_time_ms']:>6.0f}ms)")
            
            if agent_result["error_message"]:
                print(f"       오류: {agent_result['error_message']}")
        
        # 전체 평가
        overall_rate = float(summary['overall_success_rate'].rstrip('%'))
        print(f"\n{' 최종 평가':-^60}")
        if overall_rate >= 90:
            print("    A2A 통합이 완벽하게 검증되었습니다!")
        elif overall_rate >= 80:
            print("    A2A 통합이 성공적으로 검증되었습니다.")
        elif overall_rate >= 60:
            print("   ️  A2A 통합에 일부 개선이 필요합니다.")
        else:
            print("    A2A 통합에 대폭적인 개선이 필요합니다.")
    
    async def save_report(self, report: Dict[str, Any]) -> Path:
        """테스트 리포트 파일 저장"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = Path("logs/integration_tests")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        report_file = output_dir / f"a2a_integration_test_report_{timestamp}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n 상세 테스트 리포트가 {report_file}에 저장되었습니다.")
        return report_file


async def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='A2A Integration Test Runner')
    parser.add_argument('--agent', action='append', 
                       help='특정 에이전트만 테스트 (multiple times for multiple agents)')
    parser.add_argument('--parallel', action='store_true',
                       help='병렬 실행 모드 (더 빠르지만 로그가 섞일 수 있음)')
    parser.add_argument('--no-save', action='store_true',
                       help='리포트 파일 저장하지 않음')
    
    args = parser.parse_args()
    
    # 테스트 러너 초기화
    runner = A2AIntegrationTestRunner()
    
    try:
        # 테스트 실행
        results = await runner.run_all_tests(
            selected_agents=args.agent,
            parallel=args.parallel
        )
        
        # 리포트 생성
        report = runner.generate_report()
        
        # 결과 출력
        runner.print_summary(report)
        
        # 리포트 저장
        if not args.no_save:
            await runner.save_report(report)
        
        # 종료 코드 결정
        overall_rate = float(report["summary"]["overall_success_rate"].rstrip('%'))
        exit_code = 0 if overall_rate >= 80 else 1
        
        print(f"\n 테스트 완료 (Exit Code: {exit_code})")
        return exit_code
        
    except KeyboardInterrupt:
        print("\n 사용자에 의해 테스트가 중단되었습니다.")
        return 130
    except Exception as e:
        print(f"\n 치명적 오류: {str(e)}")
        import traceback
        print(f"상세 오류: {traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)