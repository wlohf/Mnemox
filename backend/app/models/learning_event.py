"""学习行为事件模型"""
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from sqlalchemy.sql import func
from app.database import Base


class LearningEvent(Base):
    """学习行为事件表（时序数据）"""
    __tablename__ = "learning_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, default=1, comment="用户ID（多用户支持）")
    
    # 事件基本信息
    event_type = Column(String(50), nullable=False, comment="事件类型")
    event_category = Column(String(20), comment="事件分类: study/practice/review/goal")
    
    # 事件详情（JSON格式存储灵活数据）
    event_data = Column(JSON, comment="事件详细数据")
    
    # 时间信息
    timestamp = Column(DateTime, server_default=func.now(), comment="事件发生时间")
    duration = Column(Integer, comment="持续时长（秒）")
    
    # 关联信息
    material_id = Column(Integer, comment="关联资料ID")
    chapter_id = Column(Integer, comment="关联章节ID")
    session_id = Column(String(50), comment="会话ID（同一学习会话）")
    
    # 元数据
    metadata = Column(JSON, comment="额外元数据")


# 事件类型枚举
class EventType:
    """学习事件类型"""
    
    # 学习会话
    STUDY_START = "study_start"  # 开始学习
    STUDY_END = "study_end"  # 结束学习
    STUDY_PAUSE = "study_pause"  # 暂停学习
    
    # 番茄钟
    POMODORO_START = "pomodoro_start"  # 开始番茄钟
    POMODORO_COMPLETE = "pomodoro_complete"  # 完成番茄钟
    POMODORO_BREAK = "pomodoro_break"  # 番茄钟休息
    POMODORO_INTERRUPT = "pomodoro_interrupt"  # 番茄钟中断
    
    # 练习答题
    QUESTION_START = "question_start"  # 开始答题
    QUESTION_ANSWERED = "question_answered"  # 提交答案
    QUESTION_CORRECT = "question_correct"  # 答对
    QUESTION_WRONG = "question_wrong"  # 答错
    
    # 笔记
    NOTE_CREATED = "note_created"  # 创建笔记
    NOTE_UPDATED = "note_updated"  # 更新笔记
    NOTE_REVIEWED = "note_reviewed"  # 复习笔记
    
    # 目标
    GOAL_SET = "goal_set"  # 设置目标
    GOAL_UPDATED = "goal_updated"  # 更新目标
    GOAL_ACHIEVED = "goal_achieved"  # 完成目标
    GOAL_FAILED = "goal_failed"  # 目标失败
    
    # 复习
    REVIEW_START = "review_start"  # 开始复习
    REVIEW_COMPLETE = "review_complete"  # 完成复习
    
    # 资料
    MATERIAL_UPLOADED = "material_uploaded"  # 上传资料
    MATERIAL_VIEWED = "material_viewed"  # 查看资料
    MATERIAL_SEARCHED = "material_searched"  # 搜索资料
    
    # AI交互
    AI_QUESTION_ASKED = "ai_question_asked"  # 向AI提问
    AI_ADVICE_RECEIVED = "ai_advice_received"  # 收到AI建议


class EventCategory:
    """事件分类"""
    STUDY = "study"  # 学习相关
    PRACTICE = "practice"  # 练习相关
    REVIEW = "review"  # 复习相关
    GOAL = "goal"  # 目标相关
    INTERACTION = "interaction"  # 交互相关
