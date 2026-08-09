"""数据库初始化兼容入口。"""
import asyncio

from run_migrations import run_migrations


async def init_database():
    """Initialize through the single supported migration entrypoint."""
    print("=> 开始数据库迁移...")
    await run_migrations()
    print("[SUCCESS] 数据库迁移完成！")


if __name__ == "__main__":
    asyncio.run(init_database())
