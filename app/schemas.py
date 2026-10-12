from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    ApplicationStatus,
    ReviewAction,
    RiskDecision,
    Role,
)

T = TypeVar("T")


# ---------- Auth ----------
class UserSignup(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: str = Field(min_length=2, max_length=255)
    role: Role = Role.SALES


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    role: Role
    created_at: datetime


class UserRoleUpdate(BaseModel):
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- Pagination ----------
class PaginationMeta(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool


class Paginated(BaseModel, Generic[T]):
    data: list[T]
    meta: PaginationMeta


# ---------- Applications ----------
class ApplicationCreate(BaseModel):
    merchant_name: str = Field(min_length=2, max_length=255)
    business_type: str = Field(min_length=2, max_length=100)
    annual_revenue: float = Field(gt=0)
    contact_email: EmailStr
    contact_phone: str = Field(min_length=7, max_length=50)


class ApplicationUpdate(BaseModel):
    merchant_name: str | None = Field(default=None, min_length=2, max_length=255)
    business_type: str | None = Field(default=None, min_length=2, max_length=100)
    annual_revenue: float | None = Field(default=None, gt=0)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, min_length=7, max_length=50)


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    merchant_name: str
    business_type: str
    annual_revenue: float
    contact_email: str
    contact_phone: str
    status: ApplicationStatus
    risk_score: float | None
    risk_decision: RiskDecision | None
    submitted_at: datetime | None
    sales_rep_id: str
    created_at: datetime
    updated_at: datetime


# ---------- Reviews ----------
class ReviewCreate(BaseModel):
    action: ReviewAction
    decision: RiskDecision
    comment: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    reviewer_id: str
    action: ReviewAction
    decision: RiskDecision
    comment: str | None
    created_at: datetime