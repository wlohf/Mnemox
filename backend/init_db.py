"""数据库初始化脚本"""
import asyncio
from app.database import Base, engine
from app.models import material, goal, session, question, pomodoro, note


async def init_database():
    """初始化数据库（创建所有表）"""
    print("=> 开始初始化数据库...")
    
    async with engine.begin() as conn:
        # 删除所有表（谨慎使用！）
        # await conn.run_sync(Base.metadata.drop_all)
        # print("[OK] 已删除所有表")
        
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        print("[OK] 数据库表创建完成")
    
    print("[SUCCESS] 数据库初始化完成！")


if __name__ == "__main__":
    asyncio.run(init_database())
