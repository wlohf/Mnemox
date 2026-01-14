"""学习事件追踪服务"""
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.learning_event import LearningEvent, EventType, EventCategory


class EventTracker:
    """学习事件追踪器"""
    
    def __init__(self, db: AsyncSession, user_id: int = 1):
        self.db = db
        self.user_id = user_id
    
    async def track(
        self,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None,
        material_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        session_id: Optional[str] = None,
        duration: Optional[int] = None
    ) -> LearningEvent:
        """
        追踪学习事件
        
        Args:
            event_type: 事件类型（使用 EventType 枚举）
            event_data: 事件详细数据
            category: 事件分类
            material_id: 关联资料ID
            chapter_id: 关联章节ID
            session_id: 学习会话ID
            duration: 持续时长（秒）
        
        Returns:
            创建的事件记录
        """
        # 自动推断分类
        if not category:
            category = self._infer_category(event_type)
        
        # 创建事件
        event = LearningEvent(
            user_id=self.user_id,
            event_type=event_type,
            event_category=category,
            event_data=event_data or {},
            material_id=material_id,
            chapter_id=chapter_id,
            session_id=session_id,
            duration=duration,
            timestamp=datetime.now()
        )
        
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        
        return event
    
    def _infer_category(self, event_type: str) -> str:
        """根据事件类型推断分类"""
        if event_type.startswith("study_"):
            return EventCategory.STUDY
        elif event_type.startswith("question_") or event_type.startswith("pomodoro_"):
            return EventCategory.PRACTICE
        elif event_type.startswith("review_"):
            return EventCategory.REVIEW
        elif event_type.startswith("goal_"):
            return EventCategory.GOAL
        elif event_type.startswith("ai_"):
            return EventCategory.INTERACTION
        else:
            return EventCategory.STUDY
    
    # ========== 便捷方法 ==========
    
    async def track_study_start(
        self, 
        material_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        session_id: Optional[str] = None
    ):
        """追踪学习开始"""
        return await self.track(
            event_type=EventType.STUDY_START,
            event_data={
                "action": "开始学习",
                "material_id": material_id,
                "chapter_id": chapter_id
            },
            material_id=material_id,
            chapter_id=chapter_id,
            session_id=session_id
        )
    
    async def track_study_end(
        self,
        session_id: str,
        duration: int,
        material_id: Optional[int] = None
    ):
        """追踪学习结束"""
        return await self.track(
            event_type=EventType.STUDY_END,
            event_data={
                "action": "结束学习",
                "duration_minutes": duration // 60
            },
            session_id=session_id,
            duration=duration,
            material_id=material_id
        )
    
    async def track_pomodoro_complete(
        self,
        pomodoro_duration: int = 25,
        material_id: Optional[int] = None
    ):
        """追踪番茄钟完成"""
        return await self.track(
            event_type=EventType.POMODORO_COMPLETE,
            event_data={
                "duration_minutes": pomodoro_duration,
                "completed": True
            },
            duration=pomodoro_duration * 60,
            material_id=material_id
        )
    
    async def track_question_answered(
        self,
        question_id: int,
        is_correct: bool,
        time_spent: int,
        material_id: Optional[int] = None,
        chapter_id: Optional[int] = None
    ):
        """追踪答题"""
        event_type = (
            EventType.QUESTION_CORRECT if is_correct 
            else EventType.QUESTION_WRONG
        )
        
        return await self.track(
            event_type=event_type,
            event_data={
                "question_id": question_id,
                "is_correct": is_correct,
                "time_spent_seconds": time_spent
            },
            duration=time_spent,
            material_id=material_id,
            chapter_id=chapter_id
        )
    
    async def track_note_created(
        self,
        note_id: int,
        content_length: int,
        material_id: Optional[int] = None,
        chapter_id: Optional[int] = None
    ):
        """追踪笔记创建"""
        return await self.track(
            event_type=EventType.NOTE_CREATED,
            event_data={
                "note_id": note_id,
                "content_length": content_length
            },
            material_id=material_id,
            chapter_id=chapter_id
        )
    
    async def track_goal_set(
        self,
        goal_id: int,
        goal_type: str,
        target_date: str,
        material_id: Optional[int] = None
    ):
        """追踪目标设置"""
        return await self.track(
            event_type=EventType.GOAL_SET,
            event_data={
                "goal_id": goal_id,
                "goal_type": goal_type,
                "target_date": target_date
            },
            material_id=material_id
        )
    
    async def track_goal_achieved(
        self,
        goal_id: int,
        completion_rate: float
    ):
        """追踪目标完成"""
        return await self.track(
            event_type=EventType.GOAL_ACHIEVED,
            event_data={
                "goal_id": goal_id,
                "completion_rate": completion_rate
            }
        )
    
    async def track_material_uploaded(
        self,
        material_id: int,
        file_type: str,
        file_size: int
    ):
        """追踪资料上传"""
        return await self.track(
            event_type=EventType.MATERIAL_UPLOADED,
            event_data={
                "material_id": material_id,
                "file_type": file_type,
                "file_size": file_size
            },
            material_id=material_id
        )
    
    async def track_ai_question(
        self,
        question: str,
        material_id: Optional[int] = None
    ):
        """追踪AI提问"""
        return await self.track(
            event_type=EventType.AI_QUESTION_ASKED,
            event_data={
                "question": question[:200],  # 只存储前200字符
                "question_length": len(question)
            },
            material_id=material_id
        )
    
    # ========== 查询方法 ==========
    
    async def get_recent_events(
        self,
        days: int = 7,
        event_type: Optional[str] = None,
        category: Optional[str] = None
    ):
        """获取最近的事件"""
        from datetime import timedelta
        
        query = select(LearningEvent).where(
            LearningEvent.user_id == self.user_id,
            LearningEvent.timestamp >= datetime.now() - timedelta(days=days)
        )
        
        if event_type:
            query = query.where(LearningEvent.event_type == event_type)
        
        if category:
            query = query.where(LearningEvent.event_category == category)
        
        query = query.order_by(LearningEvent.timestamp.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_event_count(
        self,
        event_type: Optional[str] = None,
        days: Optional[int] = None
    ) -> int:
        """统计事件数量"""
        from datetime import timedelta
        
        query = select(func.count(LearningEvent.id)).where(
            LearningEvent.user_id == self.user_id
        )
        
        if event_type:
            query = query.where(LearningEvent.event_type == event_type)
        
        if days:
            query = query.where(
                LearningEvent.timestamp >= datetime.now() - timedelta(days=days)
            )
        
        result = await self.db.execute(query)
        return result.scalar() or 0


def get_event_tracker(db: AsyncSession, user_id: int = 1) -> EventTracker:
    """获取事件追踪器实例"""
    return EventTracker(db, user_id)
