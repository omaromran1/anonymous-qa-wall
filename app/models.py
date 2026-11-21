from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def now():
    return datetime.now(timezone.utc)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("vote_count >= 0 AND report_count >= 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    edit_token_hash: Mapped[str] = mapped_column(String(64))
    vote_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    report_count: Mapped[int] = mapped_column(Integer, default=0)


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (CheckConstraint("vote_count >= 0 AND report_count >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    is_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    vote_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    report_count: Mapped[int] = mapped_column(Integer, default=0)


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "voter_hash"),
        CheckConstraint("target_type IN ('question', 'answer')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(8))
    target_id: Mapped[int] = mapped_column(Integer)
    voter_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "voter_hash"),
        CheckConstraint("target_type IN ('question', 'answer')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(8))
    target_id: Mapped[int] = mapped_column(Integer)
    voter_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    __table_args__ = (
        UniqueConstraint("action", "identity_hash", "window_start"),
        CheckConstraint("count >= 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(32))
    identity_hash: Mapped[str] = mapped_column(String(64))
    window_start: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer, default=0)


Index("uq_accepted_per_question", Answer.question_id, unique=True,
      sqlite_where=Answer.is_accepted.is_(True),
      postgresql_where=Answer.is_accepted.is_(True))
