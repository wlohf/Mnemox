"""执行数据库迁移脚本"""
import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from app.database import engine


async def run_migrations():
    """执行所有待运行的迁移"""
    migrations = [
        {
            "name": "add_goal_plan_fields",
            "description": "添加学习计划字段到 goals 表",
            "sql": """
                -- Add plan fields to goals table
                ALTER TABLE goals ADD COLUMN plan_total_days INTEGER DEFAULT NULL;
                ALTER TABLE goals ADD COLUMN plan_current_chapter_id INTEGER DEFAULT NULL;
                ALTER TABLE goals ADD COLUMN plan_study_days_per_week INTEGER DEFAULT 5;
                ALTER TABLE goals ADD COLUMN plan_start_date DATE DEFAULT NULL;
                ALTER TABLE goals ADD COLUMN plan_last_generated_week DATE DEFAULT NULL;
            """
        },
        {
            "name": "add_daily_plan_task_ids",
            "description": "添加 task_ids 字段到 daily_plans 表",
            "sql": """
                -- Add task_ids field to daily_plans table
                ALTER TABLE daily_plans ADD COLUMN task_ids TEXT DEFAULT NULL;
            """
        }
    ]
    
    async with engine.begin() as conn:
        for migration in migrations:
            print(f"\n{'='*60}")
            print(f"执行迁移: {migration['name']}")
            print(f"描述: {migration['description']}")
            print(f"{'='*60}")
            
            # Split SQL by semicolons and execute each statement
            statements = [s.strip() for s in migration['sql'].split(';') if s.strip()]
            
            for i, statement in enumerate(statements, 1):
                try:
                    print(f"\n[{i}/{len(statements)}] 执行 SQL:")
                    print(f"  {statement[:80]}..." if len(statement) > 80 else f"  {statement}")
                    
                    await conn.execute(text(statement))
                    print(f"  ✅ 成功")
                    
                except Exception as e:
                    error_msg = str(e)
                    # Check if column already exists (not an error)
                    if "duplicate column name" in error_msg.lower() or "already exists" in error_msg.lower():
                        print(f"  ⚠️  字段已存在，跳过")
                    else:
                        print(f"  ❌ 失败: {error_msg}")
                        raise
            
            print(f"\n✅ 迁移 '{migration['name']}' 完成")
    
    print(f"\n{'='*60}")
    print("🎉 所有迁移执行完成！")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(run_migrations())
