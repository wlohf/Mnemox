@echo off
chcp 65001 >nul
echo ================================================
echo   StudyAssistant 中转API配置工具
echo ================================================
echo.

echo 正在创建配置文件...

cd backend

REM 创建 .env 文件
(
echo # StudyAssistant 配置文件 - 中转API
echo.
echo # 数据库配置
echo DATABASE_URL=sqlite+aiosqlite:///./data/study.db
echo.
echo # AI 提供商配置
echo DEFAULT_AI_PROVIDER=openai
echo.
echo # 使用中转API
echo OPENAI_API_KEY=sk-rqTCXXlp0rB2inE_rINqZQPJUwvOcKrpoHgYQkpYYbdxtLXOH5AxCXuQJP0
echo OPENAI_MODEL=glm-4.7
echo OPENAI_BASE_URL=https://api.224442.xyz/v1
echo.
echo # AnythingLLM 配置
echo ANYTHINGLLM_ENABLED=true
echo ANYTHINGLLM_BASE_URL=http://localhost:3001
echo ANYTHINGLLM_API_KEY=
echo ANYTHINGLLM_WORKSPACE=study-materials
echo.
echo # 服务器配置
echo HOST=0.0.0.0
echo PORT=8000
echo DEBUG=true
echo CORS_ORIGINS=["http://localhost:5173", "http://localhost:3000"]
echo.
echo # 其他AI提供商（备用）
echo CLAUDE_API_KEY=
echo CLAUDE_MODEL=claude-opus-4-5-20251101
echo GEMINI_API_KEY=
echo GEMINI_MODEL=gemini-pro
) > .env

echo ✅ 配置文件已创建: backend\.env
echo.

REM 创建 AnythingLLM 配置
cd ..\tools\anything-llm\server

echo 正在创建 AnythingLLM 配置文件...

(
echo # AnythingLLM 服务器配置 - 中转API
echo.
echo # LLM 提供商
echo LLM_PROVIDER=openai
echo OPEN_AI_KEY=sk-rqTCXXlp0rB2inE_rINqZQPJUwvOcKrpoHgYQkpYYbdxtLXOH5AxCXuQJP0
echo OPEN_MODEL_PREF=glm-4.7
echo OPEN_AI_BASE_PATH=https://api.224442.xyz/v1
echo.
echo # Embedding 提供商（使用内置，免费）
echo EMBEDDING_ENGINE=native
echo EMBEDDING_MODEL_PREF=nomic-embed-text-v1.5
echo.
echo # 向量数据库
echo VECTOR_DB=lancedb
echo.
echo # 服务器端口
echo SERVER_PORT=3001
echo.
echo # JWT 密钥（可选）
echo JWT_SECRET=your-secret-here
echo.
echo # 禁用遥测
echo DISABLE_TELEMETRY=true
) > .env.development

echo ✅ 配置文件已创建: tools\anything-llm\server\.env.development
echo.

cd ..\..\..

echo ================================================
echo   配置完成！
echo ================================================
echo.
echo 📌 已配置信息:
echo   - API 地址: https://api.224442.xyz/v1
echo   - 模型: glm-4.7
echo   - API Key: sk-rqTCXX...（已设置）
echo.
echo 📝 配置文件位置:
echo   1. StudyAssistant: backend\.env
echo   2. AnythingLLM:    tools\anything-llm\server\.env.development
echo.
echo 🚀 下一步:
echo   1. 运行测试: cd backend ^&^& python test_integration.py
echo   2. 启动服务: start_with_anythingllm.bat
echo   3. 查看文档: 配置中转API指南.md
echo.
echo ⚠️  重要提示:
echo   - 首次启动 AnythingLLM 时，请在 Web 界面确认配置
echo   - 访问 http://localhost:3001 进行配置
echo   - Embedding 建议选择 "Native" (免费)
echo.
pause
