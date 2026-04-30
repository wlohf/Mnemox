"""题目和答题记录相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Question(Base):
    """题目表"""
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False, index=True, comment="所属章节")
    question_type = Column(String(20), comment="题型: choice, fill_blank, short_answer, essay")
    content = Column(Text, nullable=False, comment="题目内容")
    options = Column(JSON, comment="选择题选项")
    answer = Column(Text, comment="正确答案")
    explanation = Column(Text, comment="答案解析")
    difficulty = Column(Integer, default=1, comment="难度 1-5")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    
    # 关联关系
    chapter = relationship("Chapter", back_populates="questions")
    quiz_records = relationship("QuizRecord", back_populates="question")
    wrong_questions = relationship("WrongQuestion", back_populates="question", uselist=False)


class QuizRecord(Base):
    """答题记录表"""
    __tablename__ = "quiz_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, comment="题目ID")
    session_id = Column(Integer, ForeignKey("study_sessions.id"), comment="所属学习会话")
    user_answer = Column(Text, comment="用户答案")
    is_correct = Column(Boolean, comment="是否正确")
    time_spent = Column(Integer, comment="答题耗时（秒）")
    created_at = Column(DateTime, server_default=func.now(), comment="答题时间")
    
    # 关联关系
    question = relationship("Question", back_populates="quiz_records")
    session = relationship("StudySession", back_populates="quiz_records")


class WrongQuestion(Base):
    """错题本表"""
    __tablename__ = "wrong_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, unique=True, comment="题目ID")
    first_wrong_at = Column(DateTime, comment="首次做错时间")
    last_wrong_at = Column(DateTime, comment="最近做错时间")
    wrong_count = Column(Integer, default=1, comment="错误次数")
    mastery_status = Column(String(20), default="not_mastered", comment="掌握状态: not_mastered, partial, mastered")
    next_review_at = Column(DateTime, index=True, comment="下次复习时间")
    review_count = Column(Integer, default=0, comment="复习次数")
    knowledge_point = Column(String(100), comment="知识点标签")
    recall_difficulty = Column(
        String(20),
        comment="回忆难度标签: easy(很快做出来) / hard(有点卡但能做出来) / forgot(完全想不起来)"
    )
    mastery_score = Column(Float, default=0.0, comment="掌握度评分 0-100，基于回忆难度+复习次数+间隔天数综合计算")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    
    # 关联关系
    question = relationship("Question", back_populates="wrong_questions")


class ReviewSchedule(Base):
    """复习计划表（SM-2 算法）"""
    __tablename__ = "review_schedule"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    item_type = Column(String(20), comment="复习项类型: chapter, question")
    item_id = Column(Integer, comment="复习项ID")
    scheduled_date = Column(DateTime, index=True, comment="计划复习日期")
    interval_days = Column(Integer, comment="当前间隔天数")
    ease_factor = Column(Integer, default=2.5, comment="SM-2 难度因子")
    repetitions = Column(Integer, default=0, comment="复习次数")
    last_quality = Column(Integer, comment="上次复习质量 0-5")
    status = Column(String(20), default="pending", index=True, comment="状态: pending, completed, skipped")
    completed_at = Column(DateTime, comment="完成时间")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    is_archived = Column(Boolean, default=False, nullable=False, comment="是否已归档（用户手动删除）")
