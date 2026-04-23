# docker/run-mcp-server.ps1
Set-Location $PSScriptRoot

if (Test-Path ".env") {
    Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } | ForEach-Object {
        $parts = $_ -split '=', 2
        [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1])
    }
    Write-Host ".env 환경변수 로드 완료"
} else {
    Write-Host ".env 파일이 없습니다. 환경변수를 직접 설정하거나 .env를 생성하세요."
}

Write-Host "기존 MCP docker-compose 인스턴스가 있으면 종료(down)합니다..."
docker compose -f docker/mcp_servers/docker-compose.yml down

Write-Host "MCP docker-compose 인스턴스를 새로 실행합니다..."
docker compose -f docker/mcp_servers/docker-compose.yml up -d --build