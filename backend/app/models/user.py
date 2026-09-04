"""用户模型"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True, comment="用户名")
    email = Column(String(200), unique=True, nullable=False, index=True, comment="邮箱")
    hashed_password = Column(String(200), nullable=False, comment="哈希密码")
    is_active = Column(Boolean, default=True, comment="是否激活")
    # Incrementing this invalidates every previously issued access token for
    # the account (logout-all / incident response).
    token_version = Column(Integer, nullable=False, default=0, server_default="0", comment="JWT 会话版本")
    # Stored in the database (rather than only process memory) so account
    # throttling still works when the public API runs multiple workers.
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0", comment="连续登录失败次数")
    login_failed_window_started_at = Column(DateTime, nullable=True, comment="登录失败窗口开始时间")
    login_locked_until = Column(DateTime, nullable=True, comment="登录锁定截止时间")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
