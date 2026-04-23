#!/bin/bash

# Frontend 프로덕션 서버 실행 스크립트
echo "🚀 Frontend 프로덕션 서버를 시작합니다..."
echo "📂 Frontend 폴더로 이동 중..."

cd frontend

# npm이 설치되어 있는지 확인
if ! command -v npm &> /dev/null; then
    echo "❌ npm이 설치되어 있지 않습니다."
    echo "Node.js와 npm을 먼저 설치해주세요."
    exit 1
fi

# 빌드된 파일이 있는지 확인
if [ ! -d ".next" ]; then
    echo "⚠️  빌드된 파일이 없습니다."
    echo "🔨 먼저 빌드를 실행합니다..."
    npm run build
    
    if [ $? -ne 0 ]; then
        echo "❌ 빌드에 실패했습니다."
        exit 1
    fi
fi

echo "🎯 프로덕션 서버를 시작합니다 (포트: 3000)..."
echo "🌐 브라우저에서 http://localhost:3000 을 열어주세요"
echo "⏹️  서버를 중지하려면 Ctrl+C를 누르세요"
echo ""

npm run start
