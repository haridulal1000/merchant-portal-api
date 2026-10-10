from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import (
    ApplicationStatus,
    MerchantApplication,
    Review,
    RiskDecision,
    Role,
    User,
)
from app.schemas import ReviewCreate, ReviewOut

router = APIRouter(prefix="/applications", tags=["Reviews"])


@router.get("/{application_id}/reviews", response_model=list[ReviewOut])
def list_reviews(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Risk history for an application. SALES can only view their own."""
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == Role.SALES and app.sales_rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return (
        db.query(Review)
        .filter(Review.application_id == application_id)
        .order_by(Review.created_at.desc())
        .all()
    )


@router.post("/{application_id}/reviews", response_model=ReviewOut, status_code=201)
def create_review(
    application_id: str,
    payload: ReviewCreate,
    current_user: User = Depends(require_roles(Role.REVIEWER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """Record a risk decision (REVIEWER or ADMIN only). Updates the application status."""
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    review = Review(
        application_id=application_id,
        reviewer_id=current_user.id,
        decision=payload.decision,
        comment=payload.comment,
    )
    db.add(review)

    app.risk_decision = payload.decision
    app.status = (
        ApplicationStatus.REJECTED
        if payload.decision == RiskDecision.REJECTED
        else ApplicationStatus.APPROVED
    )

    db.commit()
    db.refresh(review)
    return review