import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    SALES = "SALES"
    REVIEWER = "REVIEWER"
    ADMIN = "ADMIN"


class ApplicationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskDecision(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    REJECTED = "REJECTED"


class ReviewAction(str, enum.Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    UNDER_REVIEW = "UNDER_REVIEW"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="role_enum"), default=Role.SALES, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    applications = relationship(
        "MerchantApplication",
        back_populates="sales_rep",
        foreign_keys="MerchantApplication.sales_rep_id",
    )
    assigned_applications = relationship(
        "MerchantApplication",
        back_populates="assigned_reviewer",
        foreign_keys="MerchantApplication.assigned_reviewer_id",
    )
    reviews = relationship("Review", back_populates="reviewer")
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )


class MerchantApplication(Base):
    __tablename__ = "merchant_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    merchant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_type: Mapped[str] = mapped_column(String(100), nullable=False)
    annual_revenue: Mapped[float] = mapped_column(Float, nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(50), nullable=False)

    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus, name="application_status_enum"),
        default=ApplicationStatus.DRAFT,
        nullable=False,
    )
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_decision: Mapped[RiskDecision | None] = mapped_column(
        SAEnum(RiskDecision, name="risk_decision_enum"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sales_rep_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    assigned_reviewer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sales_rep = relationship(
        "User",
        back_populates="applications",
        foreign_keys=[sales_rep_id],
    )
    assigned_reviewer = relationship(
        "User",
        back_populates="assigned_applications",
        foreign_keys=[assigned_reviewer_id],
    )
    reviews = relationship(
        "Review", back_populates="application", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_applications_sales_rep", "sales_rep_id"),
        Index("ix_applications_assigned_reviewer", "assigned_reviewer_id"),
        Index("ix_applications_status", "status"),
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("merchant_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    action: Mapped[ReviewAction] = mapped_column(
        SAEnum(ReviewAction, name="review_action_enum"), nullable=False
    )
    decision: Mapped[RiskDecision] = mapped_column(
        SAEnum(RiskDecision, name="risk_decision_review_enum"), nullable=False
    )
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    application = relationship("MerchantApplication", back_populates="reviews")
    reviewer = relationship("User", back_populates="reviews")

    __table_args__ = (
        Index("ix_reviews_application", "application_id"),
        Index("ix_reviews_reviewer", "reviewer_id"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    token: Mapped[str] = mapped_column(
        String(512), unique=True, index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    user = relationship("User", back_populates="refresh_tokens")