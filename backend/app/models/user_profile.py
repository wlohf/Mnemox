"""用户画像模型"""
from sqlalchemy import Column, Integer, Float, String, DateTime, JSON, Text
from sqlalchemy.sql import func
from app.database import Base


class UserProfile(Base):
    """用户学习画像表"""
    __tablename__ = "user_profiles"
    
    user_id = Column(Integer, primary_key=True, comment="用户ID")
    
    # ========== 基础统计 ==========
    total_study_hours = Column(Float, default=0, comment="总学习时长（小时）")
    total_study_days = Column(Integer, default=0, comment="累计学习天数")
    total_pomodoros = Column(Integer, default=0, comment="完成番茄钟数")
    total_questions = Column(Integer, default=0, comment="答题总数")
    total_correct = Column(Integer, default=0, comment="答对总数")
    correct_rate = Column(Float, default=0, comment="总体正确率")
    
    # ========== 学习特征 ==========
    learning_style = Column(
        String(20), 
        default="unknown",
        comment="学习风格: visual(视觉)/auditory(听觉)/kinesthetic(实践)"
    )
    avg_session_duration = Column(Integer, default=0, comment="平均学习时长（分钟）")
    avg_pomodoro_per_day = Column(Float, default=0, comment="日均番茄钟数")
    
    # 偏好学习时段（JSON: {"morning": 0.2, "afternoon": 0.3, "evening": 0.5}）
    preferred_time_slots = Column(JSON, comment="偏好学习时段分布")
    
    # 最佳学习时段（格式: "20:00-22:00"）
    optimal_hours = Column(String(20), comment="最佳学习时段")
    
    # ========== 个性特征评分 (0-100) ==========
    self_control_score = Column(
        Float, 
        default=50, 
        comment="自控力评分：计划执行能力"
    )
    consistency_score = Column(
        Float, 
        default=50, 
        comment="坚持度评分：是否三天打鱼两天晒网"
    )
    planning_score = Column(
        Float, 
        default=50, 
        comment="计划能力评分：目标设定和完成能力"
    )
    focus_score = Column(
        Float, 
        default=50, 
        comment="专注度评分：番茄钟完成率和中断率"
    )
    
    # ========== 动态数据 ==========
    # 近期表现趋势（JSON格式）
    recent_performance = Column(
        JSON,
        comment="近期表现: {daily_hours: [], correct_rates: [], dates: []}"
    )
    
    # 薄弱知识点（JSON数组）
    weak_points = Column(
        JSON,
        comment="薄弱知识点: [{name: '', mastery: 0.3, error_count: 5}, ...]"
    )
    
    # 擅长领域（JSON数组）
    strong_points = Column(
        JSON,
        comment="擅长领域: [{name: '', mastery: 0.9}, ...]"
    )
    
    # 学习模式（JSON）
    learning_patterns = Column(
        JSON,
        comment="学习模式分析: {max_streak: 5, avg_streak: 3, gap_frequency: 0.2}"
    )
    
    # ========== AI 评估 ==========
    ai_assessment = Column(Text, comment="AI教练的综合评价")
    personality_analysis = Column(JSON, comment="性格分析详情")
    coaching_suggestions = Column(JSON, comment="当前建议")
    
    # ========== 时间戳 ==========
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    last_updated = Column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now(), 
        comment="最后更新时间"
    )
    last_study_date = Column(DateTime, comment="最后学习日期")
    
    # ========== 统计周期 ==========
    stats_period_days = Column(Integer, default=30, comment="统计周期（天）")


class LearningStyle:
    """学习风格枚举"""
    VISUAL = "visual"  # 视觉型：喜欢看图、视频
    AUDITORY = "auditory"  # 听觉型：喜欢听讲、讨论
    KINESTHETIC = "kinesthetic"  # 实践型：喜欢动手、实验
    MIXED = "mixed"  # 混合型
    UNKNOWN = "unknown"  # 未知


class PersonalityTrait:
    """性格特征阈值"""
    
    # 坚持度等级
    CONSISTENCY_EXCELLENT = 80  # 优秀
    CONSISTENCY_GOOD = 60  # 良好
    CONSISTENCY_FAIR = 40  # 一般
    CONSISTENCY_POOR = 20  # 较差（三天打鱼两天晒网）
    
    # 自控力等级
    SELF_CONTROL_HIGH = 75
    SELF_CONTROL_MEDIUM = 50
    SELF_CONTROL_LOW = 30
    
    # 专注度等级
    FOCUS_HIGH = 75
    FOCUS_MEDIUM = 50
    FOCUS_LOW = 30
