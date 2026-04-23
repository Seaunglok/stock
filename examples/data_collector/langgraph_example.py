#!/usr/bin/env python3
"""
DataCollector Agent - LangGraph 레벨 직접 호출 예제

ReactDataCollectorAgent를 직접 import하여 사용하는 예제입니다.
MCP 도구들을 초기화하고 삼성전자 데이터를 수집합니다.

실행 전제 조건:
- MCP 서버들이 실행 중이어야 함 (./1-run-all-services.sh)
- 특히 포트 8031(market), 8032(info), 8050(news)가 활성화되어 있어야 함
"""

import asyncio
import json
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 공통 모듈 import
from examples.common.logging import (  # noqa: E402
    LogCapture,
    get_log_filename,
    get_result_filename,
)
from examples.common.server_checks import check_mcp_servers  # noqa: E402
from src.lg_agents.data_collector_agent import (  # noqa: E402
    collect_data,
    create_data_collector_agent,
)


def print_section(title: str):
    """섹션 구분선 출력"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


async def main():
    """메인 실행 함수"""

    # 로그 캡처 시작
    log_capture = LogCapture()
    log_capture.start_capture()

    try:
        print_section("DataCollector Agent - LangGraph 예제")
        print("React Agent를 직접 사용하여 데이터를 수집합니다.")

        # 1. MCP 서버 상태 확인
        if not await check_mcp_servers("data_collector"):
            print("\n일부 MCP 서버가 실행되지 않았습니다.")
            print("해결 방법: ./1-run-all-services.sh 실행")

        # 2. DataCollector Agent 초기화
        print("create_react_agent 기반 DataCollector 생성 중...")
        agent = await create_data_collector_agent(is_debug=True)

        if not agent:
            print(" DataCollector Agent 생성 실패")
            return

        # 3. 데이터 수집 요청 실행
        print_section("데이터 수집 실행")

        # 테스트할 종목 및 요청 데이터 - 구체적인 도구 사용 요청
        test_request = {
            "symbols": ["005930"],  # 삼성전자 종목코드
            "data_types": ["price", "info", "news", "chart", "investor"],
            "user_question": """005930 종목에 대해 다음 도구들을 모두 사용해서 종합적인 데이터를 수집해주세요:
1. get_stock_execution_info로 체결 정보 확인
2. get_stock_basic_info로 기본 정보 수집
3. get_stock_orderbook으로 호가 현황 파악
4. get_stock_news로 최신 뉴스 수집 (7일, 10건)
5. get_stock_chart로 차트 데이터 수집

모든 도구를 빠짐없이 호출하고 실제 데이터를 수집해주세요.""",
            "quality_threshold": 0.8,
        }

        print(f"요청 종목: {test_request['symbols']}")
        print(f"요청 데이터: {test_request['data_types']}")
        print(f"질문: {test_request['user_question']}")

        print("\n 데이터 수집 중... (최대 60초 소요)")
        print("⏳ 여러 도구를 호출하므로 시간이 걸릴 수 있습니다...")
        print(" 예상 도구 호출: 5개 이상")

        try:
            result = await asyncio.wait_for(
                collect_data(
                    agent=agent,
                    symbols=test_request["symbols"],
                    data_types=test_request["data_types"],
                    user_question=test_request["user_question"]
                ),
                timeout=60.0
            )
            print("\n모든 도구 호출 완료")
        except asyncio.TimeoutError:
            print("\n데이터 수집 타임아웃 (60초)")
            result = {
                "success": False,
                "error": "Collection timeout after 60 seconds",
                "messages": []
            }

        # 4. 결과 출력
        print_section("수집 결과")

        if isinstance(result, dict) and result.get("success"):
            print("데이터 수집 성공!")

            # 수집된 데이터 요약
            collected_data = result.get("result", {})

            tool_calls = collected_data.get('tool_calls_made', 0)
            print("\n도구 호출 검증:")
            print(f"  - 도구 호출 횟수: {tool_calls}회")

        # 5. 전체 결과를 JSON 파일로 저장
        output_dir = Path("../../logs/examples/langgraph")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / get_result_filename("data_collection_result")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n전체 결과가 {output_file}에 저장되었습니다.")

        print_section("테스트 완료")

    except Exception as e:
        print(f"\n실행 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        try:
            log_capture.stop_capture()
            log_dir = Path("../../logs/examples/langgraph")
            log_dir.mkdir(parents=True, exist_ok=True)
            log_filename = log_dir / get_log_filename("datacollector_langgraph_log")
            log_capture.save_log(str(log_filename))
            print(f"\n실행 로그가 {log_filename}에 저장되었습니다.")
        except Exception as log_error:
            print(f"\n로그 저장 실패: {log_error}")


if __name__ == "__main__":
    asyncio.run(main())