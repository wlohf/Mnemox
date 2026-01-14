# AI教练系统 - 快速开始指南

## 🎯 从现在开始构建您的AI教练

这份指南将帮助您**立即开始**第一阶段的开发 - 数据收集基础。

---

## 📦 Phase 1: 数据收集（立即可做）

### 目标

让系统开始收集用户的学习行为数据，为后续的AI分析打下基础。

### 已准备好的代码

✅ `models/learning_event.py` - 事件模型  
✅ `models/user_profile.py` - 用户画像模型  
✅ `services/event_tracker.py` - 事件追踪服务

### 第1步: 更新数据库

```bash
cd StudyAssitant/backend

# 创建数据库迁移（如果使用alembic）
# 或者重新初始化数据库
python init_db.py
```

### 第2步: 在现有功能中埋点

#### 示例1: 在资料上传时追踪

修改 `routers/materials.py`:

```python
from app.services.event_tracker import get_event_tracker

@router.post("/upload")
async def upload_material(
    title: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    # ... 原有的上传逻辑 ...
    
    # 追踪事件
    tracker = get_event_tracker(db)
    await tracker.track_material_uploaded(
        material_id=material.id,
        file_type=material.file_type,
        file_size=file_path.stat().st_size
    )
    
    return material
```

#### 示例2: 在RAG问答时追踪

修改 `routers/materials.py`:

```python
@router.post("/{material_id}/ask")
async def ask_question(
    material_id: int,
    request: QuestionRequest,
    db: AsyncSession = Depends(get_db)
):
    # ... 原有的问答逻辑 ...
    
    # 追踪AI交互
    tracker = get_event_tracker(db)
    await tracker.track_ai_question(
        question=request.question,
        material_id=material_id
    )
    
    answer = await material_service.ask_question_about_material(
        material_id=material_id,
        question=request.question
    )
    
    return {"question": request.question, "answer": answer}
```

#### 示例3: 追踪学习会话

创建新的学习会话路由 `routers/study.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.event_tracker import get_event_tracker
from datetime import datetime
import uuid

router = APIRouter()

# 存储活动会话（实际应该用Redis）
active_sessions = {}

@router.post("/session/start")
async def start_study_session(
    material_id: int,
    chapter_id: int = None,
    db: AsyncSession = Depends(get_db)
):
    """开始学习会话"""
    session_id = str(uuid.uuid4())
    
    # 追踪事件
    tracker = get_event_tracker(db)
    await tracker.track_study_start(
        material_id=material_id,
        chapter_id=chapter_id,
        session_id=session_id
    )
    
    # 记录会话
    active_sessions[session_id] = {
        "start_time": datetime.now(),
        "material_id": material_id,
        "chapter_id": chapter_id
    }
    
    return {"session_id": session_id, "message": "学习会话已开始"}

@router.post("/session/{session_id}/end")
async def end_study_session(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """结束学习会话"""
    if session_id not in active_sessions:
        return {"error": "会话不存在"}
    
    session = active_sessions[session_id]
    duration = int((datetime.now() - session["start_time"]).total_seconds())
    
    # 追踪事件
    tracker = get_event_tracker(db)
    await tracker.track_study_end(
        session_id=session_id,
        duration=duration,
        material_id=session["material_id"]
    )
    
    del active_sessions[session_id]
    
    return {
        "message": "学习会话已结束",
        "duration_minutes": duration // 60
    }
```

### 第3步: 注册新路由

修改 `main.py`:

```python
from app.routers import materials, study

app.include_router(materials.router, prefix="/api/materials", tags=["资料管理"])
app.include_router(study.router, prefix="/api/study", tags=["学习会话"])
```

### 第4步: 测试数据收集

创建测试脚本 `test_event_tracking.py`:

```python
"""测试事件追踪功能"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import async_session_maker
from app.services.event_tracker import EventTracker
from app.models.learning_event import EventType


async def test_tracking():
    """测试事件追踪"""
    print("🧪 测试事件追踪功能")
    print("=" * 50)
    
    async with async_session_maker() as db:
        tracker = EventTracker(db, user_id=1)
        
        # 测试1: 追踪学习开始
        print("\n1️⃣  追踪学习开始...")
        await tracker.track_study_start(
            material_id=1,
            chapter_id=1,
            session_id="test-session-001"
        )
        print("   ✅ 学习开始事件已记录")
        
        # 测试2: 追踪番茄钟
        print("\n2️⃣  追踪番茄钟完成...")
        await tracker.track_pomodoro_complete(
            pomodoro_duration=25,
            material_id=1
        )
        print("   ✅ 番茄钟事件已记录")
        
        # 测试3: 追踪答题
        print("\n3️⃣  追踪答题...")
        await tracker.track_question_answered(
            question_id=1,
            is_correct=True,
            time_spent=60,
            material_id=1
        )
        print("   ✅ 答题事件已记录")
        
        # 测试4: 查询最近事件
        print("\n4️⃣  查询最近事件...")
        events = await tracker.get_recent_events(days=1)
        print(f"   📊 最近有 {len(events)} 个事件")
        
        for event in events[:3]:
            print(f"   - {event.event_type}: {event.event_data}")
    
    print("\n" + "=" * 50)
    print("✅ 测试完成！事件追踪系统工作正常")
    print("\n💡 现在您可以在使用系统时看到数据在积累")


if __name__ == "__main__":
    asyncio.run(test_tracking())
```

运行测试:

```bash
python backend/test_event_tracking.py
```

---

## 📊 查看收集的数据

### 创建简单的数据查看API

在 `routers/analytics.py` 中:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.event_tracker import get_event_tracker

router = APIRouter()

@router.get("/events/recent")
async def get_recent_events(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """获取最近的学习事件"""
    tracker = get_event_tracker(db)
    events = await tracker.get_recent_events(days=days)
    
    return {
        "total": len(events),
        "events": [
            {
                "type": e.event_type,
                "category": e.event_category,
                "data": e.event_data,
                "timestamp": e.timestamp.isoformat()
            }
            for e in events
        ]
    }

@router.get("/stats/summary")
async def get_stats_summary(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """获取学习统计摘要"""
    tracker = get_event_tracker(db)
    
    # 统计各类事件
    from app.models.learning_event import EventType
    
    pomodoros = await tracker.get_event_count(
        event_type=EventType.POMODORO_COMPLETE,
        days=days
    )
    
    questions = await tracker.get_event_count(
        event_type=EventType.QUESTION_ANSWERED,
        days=days
    )
    
    correct = await tracker.get_event_count(
        event_type=EventType.QUESTION_CORRECT,
        days=days
    )
    
    study_sessions = await tracker.get_event_count(
        event_type=EventType.STUDY_START,
        days=days
    )
    
    return {
        "period_days": days,
        "study_sessions": study_sessions,
        "pomodoros_completed": pomodoros,
        "questions_answered": questions,
        "questions_correct": correct,
        "correct_rate": (correct / questions * 100) if questions > 0 else 0
    }
```

注册路由:

```python
from app.routers import analytics

app.include_router(analytics.router, prefix="/api/analytics", tags=["数据分析"])
```

访问统计:

- http://localhost:8000/api/analytics/events/recent
- http://localhost:8000/api/analytics/stats/summary

---

## 🎨 前端展示（可选）

### 创建简单的统计面板

```typescript
// frontend/src/pages/Statistics/index.tsx

import { useEffect, useState } from 'react';

interface Stats {
  study_sessions: number;
  pomodoros_completed: number;
  questions_answered: number;
  correct_rate: number;
}

export function Statistics() {
  const [stats, setStats] = useState<Stats | null>(null);
  
  useEffect(() => {
    fetch('/api/analytics/stats/summary?days=7')
      .then(res => res.json())
      .then(setStats);
  }, []);
  
  if (!stats) return <div>加载中...</div>;
  
  return (
    <div className="statistics-page">
      <h1>我的学习统计</h1>
      
      <div className="stats-grid">
        <div className="stat-card">
          <h3>学习会话</h3>
          <p className="stat-value">{stats.study_sessions}</p>
          <p className="stat-label">次</p>
        </div>
        
        <div className="stat-card">
          <h3>完成番茄钟</h3>
          <p className="stat-value">{stats.pomodoros_completed}</p>
          <p className="stat-label">个</p>
        </div>
        
        <div className="stat-card">
          <h3>练习题目</h3>
          <p className="stat-value">{stats.questions_answered}</p>
          <p className="stat-label">道</p>
        </div>
        
        <div className="stat-card">
          <h3>正确率</h3>
          <p className="stat-value">{stats.correct_rate.toFixed(1)}%</p>
        </div>
      </div>
      
      <p className="hint">
        💡 数据正在积累中，继续使用系统来获得更多洞察！
      </p>
    </div>
  );
}
```

---

## ✅ 检查清单

完成以下任务，Phase 1 就完成了：

- [ ] 数据库添加了 `learning_events` 表
- [ ] 数据库添加了 `user_profiles` 表
- [ ] 在资料上传时追踪事件
- [ ] 在RAG问答时追踪事件
- [ ] 实现了学习会话追踪
- [ ] 创建了数据查看API
- [ ] 运行测试脚本验证功能
- [ ] （可选）前端显示统计数据

---

## 🎯 下一步

完成 Phase 1 后，您将拥有：

✅ 完整的事件追踪系统  
✅ 不断积累的用户行为数据  
✅ 基础的统计展示

然后可以进入 **Phase 2: 用户画像分析**

预览下一阶段的功能：

```python
# Phase 2 预览
@router.get("/profile/personality")
async def get_personality_analysis(db: AsyncSession = Depends(get_db)):
    """获取性格分析"""
    analyzer = PersonalityAnalyzer(db)
    personality = await analyzer.analyze(user_id=1)
    
    return {
        "self_control": personality["self_control"],
        "consistency": personality["consistency"],
        "is_consistent": personality["consistency"] > 60,
        "assessment": (
            "你是一个自控力强、坚持学习的学生！👍"
            if personality["consistency"] > 70 
            else "建议设置更小的目标，逐步建立学习习惯 💪"
        )
    }
```

---

## 💡 实用建议

### 1. 边开发边使用

最好的测试方法就是**自己用自己的系统学习**！

- 上传真实的学习资料
- 使用番茄钟功能（即使现在还没完全实现）
- 记录学习会话
- 定期查看统计数据

### 2. 快速迭代

不要等到完美才上线，先把基础功能跑起来：

**本周**:
- 事件追踪 ✅
- 基础统计 ✅

**下周**:
- 用户画像
- 性格分析

**两周后**:
- AI教练对话
- 个性化建议

### 3. 数据驱动

有了数据后，可以：

- 分析自己的学习模式
- 发现问题和规律
- 优化系统设计

---

## 📚 参考资源

- 完整设计文档: `docs/AI教练系统设计.md`
- 事件模型: `models/learning_event.py`
- 追踪服务: `services/event_tracker.py`
- API文档: http://localhost:8000/docs

---

<div align="center">

**开始构建您的AI教练系统！**

记住：数据是基础，每一个追踪的事件都在让AI更懂您！

</div>
