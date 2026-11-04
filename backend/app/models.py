from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(240), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cpf_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Track(Base):
    __tablename__ = "tracks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    artist: Mapped[str] = mapped_column(String(180), default="", nullable=False)
    musical_key: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(240), default="Multitrack", nullable=False)
    categories_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    time_signature: Mapped[str] = mapped_column(String(12), default="4/4", nullable=False)
    stems_path: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    preview_start_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preview_end_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    cover_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    cover_content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(600), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream", nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RevenueEntry(Base):
    __tablename__ = "revenue_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="Manual", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BRL", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TrackCategory(Base):
    __tablename__ = "track_categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class HomepageFeatureSelection(Base):
    __tablename__ = "homepage_feature_selections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    launches_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    most_downloaded_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
