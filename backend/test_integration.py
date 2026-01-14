"""AnythingLLM 集成测试脚本"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from app.ai.anythingllm_provider import AnythingLLMProvider


async def test_connection():
    """测试连接"""
    print("=" * 50)
    print("AnythingLLM 集成测试")
    print("=" * 50)
    print()
    
    provider = AnythingLLMProvider()
    
    # 1. 测试服务器连接
    print("1️⃣  测试 AnythingLLM 服务器连接...")
    online = await provider.check_online()
    if online:
        print("   ✅ AnythingLLM 服务器在线")
    else:
        print("   ❌ AnythingLLM 服务器离线")
        print("   💡 请确保已启动 AnythingLLM Server (端口 3001)")
        print("      启动命令: cd tools/anything-llm/server && yarn dev")
        return False
    print()
    
    # 2. 测试文档处理服务
    print("2️⃣  测试文档处理服务连接...")
    collector_online = await provider.check_collector_online()
    if collector_online:
        print("   ✅ 文档处理服务在线")
    else:
        print("   ❌ 文档处理服务离线")
        print("   💡 请确保已启动 Collector 服务 (端口 8888)")
        print("      启动命令: cd tools/anything-llm/collector && yarn dev")
        return False
    print()
    
    # 3. 测试工作空间创建/获取
    print("3️⃣  测试工作空间...")
    try:
        workspace = await provider.ensure_workspace("test-workspace")
        print(f"   ✅ 工作空间已就绪: {workspace.get('name', 'N/A')}")
        print(f"      Slug: {workspace.get('slug', 'N/A')}")
    except Exception as e:
        print(f"   ❌ 工作空间测试失败: {e}")
        return False
    print()
    
    # 4. 测试聊天功能
    print("4️⃣  测试 RAG 聊天...")
    try:
        response = await provider.chat(
            "Hello, this is a test message.",
            workspace_slug=workspace.get('slug')
        )
        if response.get('textResponse'):
            print("   ✅ RAG 聊天功能正常")
            print(f"      响应: {response.get('textResponse')[:100]}...")
        else:
            print("   ⚠️  收到响应但没有文本内容")
            print(f"      响应: {response}")
    except Exception as e:
        print(f"   ❌ 聊天测试失败: {e}")
        return False
    print()
    
    print("=" * 50)
    print("✅ 所有测试通过！")
    print("=" * 50)
    print()
    print("📝 下一步:")
    print("   1. 启动 StudyAssistant 后端: python backend/app/main.py")
    print("   2. 访问 API 文档: http://localhost:8000/docs")
    print("   3. 上传资料并测试 RAG 功能")
    print()
    
    return True


async def main():
    """主函数"""
    try:
        success = await test_connection()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  测试已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
