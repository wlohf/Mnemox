"""
AnythingLLM 集成功能演示脚本

这个脚本展示了如何使用 StudyAssistant + AnythingLLM 的各项功能
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from app.ai.anythingllm_provider import AnythingLLMProvider


async def demo():
    """演示各项功能"""
    
    print("=" * 70)
    print("StudyAssistant × AnythingLLM 功能演示")
    print("=" * 70)
    print()
    
    provider = AnythingLLMProvider()
    
    # ========== 1. 检查服务状态 ==========
    print("📡 1. 检查服务状态")
    print("-" * 70)
    
    server_online = await provider.check_online()
    collector_online = await provider.check_collector_online()
    
    print(f"   AnythingLLM Server:  {'✅ 在线' if server_online else '❌ 离线'}")
    print(f"   文档处理服务:         {'✅ 在线' if collector_online else '❌ 离线'}")
    
    if not (server_online and collector_online):
        print("\n⚠️  服务未完全启动，请先启动所有服务:")
        print("   1. cd tools/anything-llm/server && yarn dev")
        print("   2. cd tools/anything-llm/collector && yarn dev")
        return
    
    print("✅ 所有服务正常运行")
    print()
    
    # ========== 2. 创建/获取工作空间 ==========
    print("🗂️  2. 工作空间管理")
    print("-" * 70)
    
    workspace = await provider.ensure_workspace("demo-workspace")
    print(f"   工作空间: {workspace.get('name')}")
    print(f"   Slug: {workspace.get('slug')}")
    print()
    
    # ========== 3. 演示聊天功能 ==========
    print("💬 3. 基础对话功能")
    print("-" * 70)
    
    test_questions = [
        "你好！请介绍一下你自己。",
        "你可以帮我做什么？",
    ]
    
    for question in test_questions:
        print(f"   👤 用户: {question}")
        response = await provider.chat(
            question, 
            workspace_slug=workspace.get('slug'),
            mode="chat"
        )
        answer = response.get('textResponse', '')
        # 截断长回答
        if len(answer) > 150:
            answer = answer[:150] + "..."
        print(f"   🤖 AI: {answer}")
        print()
    
    # ========== 4. 演示文档查询（如果有文档） ==========
    print("📚 4. 文档查询功能 (RAG)")
    print("-" * 70)
    
    # 检查是否有文档
    documents = await provider.get_documents(workspace.get('slug'))
    
    if documents and len(documents) > 0:
        print(f"   发现 {len(documents)} 个文档:")
        for doc in documents[:3]:  # 只显示前3个
            print(f"   - {doc.get('name', 'Unknown')}")
        print()
        
        # 尝试 RAG 查询
        print("   尝试基于文档内容提问...")
        rag_question = "这些文档主要讲了什么内容？"
        print(f"   👤 用户: {rag_question}")
        
        response = await provider.chat(
            rag_question,
            workspace_slug=workspace.get('slug'),
            mode="query"  # RAG 模式
        )
        answer = response.get('textResponse', '')
        if len(answer) > 200:
            answer = answer[:200] + "..."
        print(f"   🤖 AI: {answer}")
        
    else:
        print("   ℹ️  当前工作空间没有文档")
        print("   提示: 使用 API 上传文档后再试:")
        print("   curl -X POST 'http://localhost:8000/api/materials/upload' \\")
        print("     -F 'title=测试资料' \\")
        print("     -F 'file=@your_file.pdf' \\")
        print("     -F 'sync_to_anythingllm=true'")
    
    print()
    
    # ========== 5. 演示文档分析功能 ==========
    print("🔍 5. 文档分析功能演示")
    print("-" * 70)
    
    print("   这个功能可以:")
    print("   ✓ 自动总结文档内容")
    print("   ✓ 提取关键知识点")
    print("   ✓ 生成学习大纲")
    print()
    
    if documents and len(documents) > 0:
        print("   示例: 分析第一个文档")
        print(f"   文档: {documents[0].get('name', 'Unknown')}")
        
        # 简单演示一个分析问题
        analysis_question = "请简要总结这份资料的主要内容（50字以内）"
        print(f"   📋 分析任务: {analysis_question}")
        
        response = await provider.chat(
            analysis_question,
            workspace_slug=workspace.get('slug'),
            mode="query"
        )
        answer = response.get('textResponse', '')
        print(f"   📊 分析结果: {answer[:200]}...")
    else:
        print("   ℹ️  需要先上传文档才能演示此功能")
    
    print()
    
    # ========== 总结 ==========
    print("=" * 70)
    print("✅ 演示完成！")
    print("=" * 70)
    print()
    print("🎯 下一步操作建议:")
    print()
    print("1️⃣  上传您的学习资料:")
    print("   curl -X POST 'http://localhost:8000/api/materials/upload' \\")
    print("     -F 'title=我的学习资料' \\")
    print("     -F 'file=@your_document.pdf' \\")
    print("     -F 'sync_to_anythingllm=true'")
    print()
    print("2️⃣  访问 API 文档查看所有功能:")
    print("   http://localhost:8000/docs")
    print()
    print("3️⃣  访问 AnythingLLM Web 界面:")
    print("   http://localhost:3001")
    print()
    print("4️⃣  查看完整文档:")
    print("   - 快速开始: 快速开始-AnythingLLM集成.md")
    print("   - 详细文档: ANYTHINGLLM_INTEGRATION.md")
    print()
    print("💡 提示: 使用本地 Ollama LLM 完全免费，无需 API Key！")
    print()


async def main():
    """主函数"""
    try:
        await demo()
    except KeyboardInterrupt:
        print("\n\n⚠️  演示已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 演示出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    print()
    print("正在启动演示...")
    print()
    asyncio.run(main())
