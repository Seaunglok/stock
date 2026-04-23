"""
공통 서버 체크 모듈

이 모듈은 examples 폴더 내의 모든 예제에서 사용할 수 있는
서버 상태 확인 기능을 제공합니다.
"""

import asyncio
from typing import Dict

import aiohttp
import httpx


def get_mcp_servers_config(agent_type: str) -> Dict[str, str]:
    """
    Agent 타입에 따른 MCP 서버 설정 반환

    Args:
        agent_type: Agent 타입 ("analysis", "data_collector", "trading")

    Returns:
        Dict[str, str]: 서버명과 URL 매핑
    """
    configs = {
        "analysis": {
            "Stock Analysis MCP": "http://localhost:8040/health",
            "Financial Analysis MCP": "http://localhost:8041/health",
            "Macroeconomic MCP": "http://localhost:8042/health",
            "News MCP": "http://localhost:8050/health",
        },
        "data_collector": {
            "Market MCP": "http://localhost:8031/health",
            "Info MCP": "http://localhost:8032/health",
            "News MCP": "http://localhost:8050/health",
        },
        "trading": {
            "Trading Domain MCP": "http://localhost:8030/health",
            "Portfolio Domain MCP": "http://localhost:8034/health",
        }
    }

    return configs.get(agent_type, {})


def get_a2a_servers_config() -> Dict[str, str]:
    """
    A2A 서버 설정 반환 (Supervisor용)

    Returns:
        Dict[str, str]: 서버명과 URL 매핑
    """
    return {
        "DataCollectorAgent": "http://localhost:8001",
        "AnalysisAgent": "http://localhost:8002",
        "TradingAgent": "http://localhost:8003"
    }


async def check_mcp_servers(agent_type: str) -> bool:
    """
    MCP 서버 상태 확인 (httpx 사용)

    Args:
        agent_type: Agent 타입

    Returns:
        bool: 모든 서버가 정상 작동하는지 여부
    """
    servers = get_mcp_servers_config(agent_type)

    if not servers:
        print(f"️ {agent_type}에 대한 서버 설정을 찾을 수 없습니다.")
        return False

    print(f"\n{'='*60}")
    print(f"  {agent_type.upper()} MCP 서버 상태 확인")
    print("="*60)

    all_healthy = True

    async with httpx.AsyncClient() as client:
        for name, url in servers.items():
            try:
                response = await client.get(url, timeout=2.0)
                if response.status_code == 200:
                    print(f" {name}: 정상 작동")
                else:
                    print(f"️ {name}: 응답 이상 (status: {response.status_code})")
                    all_healthy = False
            except Exception as e:
                print(f" {name}: 연결 실패 ({str(e)[:50]})")
                all_healthy = False

    return all_healthy


async def check_a2a_servers() -> bool:
    """
    A2A 서버 상태 확인 (aiohttp 사용)

    Returns:
        bool: 모든 서버가 정상 작동하는지 여부
    """
    servers = get_a2a_servers_config()

    print("=" * 60)
    print("  A2A 서버 상태 확인")
    print("=" * 60)

    all_healthy = True

    for name, url in servers.items():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{url}/health", timeout=3) as response:
                    if response.status == 200:
                        print(f" {name}: 정상 작동 ({url})")
                    else:
                        print(f"️ {name}: 응답 코드 {response.status} ({url})")
                        all_healthy = False
        except aiohttp.ClientConnectorError:
            print(f" {name}: 연결 실패 - 서버 미실행 ({url})")
            all_healthy = False
        except asyncio.TimeoutError:
            print(f"⏳ {name}: 응답 시간 초과 ({url})")
            all_healthy = False
        except Exception as e:
            print(f" {name}: 오류 - {str(e)} ({url})")
            all_healthy = False

    print()
    return all_healthy


def print_server_status(servers: Dict[str, str], title: str = "서버 상태 확인"):
    """
    서버 상태를 보기 좋게 출력하는 함수

    Args:
        servers: 서버명과 상태 매핑
        title: 출력 제목
    """
    print(f"\n{'='*60}")
    print(f"  {title}")
    print("="*60)

    for name, status in servers.items():
        if "정상" in status or "" in status:
            print(f" {name}: {status}")
        elif "️" in status or "⏳" in status:
            print(f"️ {name}: {status}")
        else:
            print(f" {name}: {status}")
