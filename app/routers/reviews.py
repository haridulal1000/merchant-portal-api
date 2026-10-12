from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import (
    ApplicationStatus,
    MerchantApplication,
    Review,
    ReviewAction,
    Role,
    User,
)
from app.schemas import ReviewCreate, ReviewOut

router = APIRouter(prefix="/applications", tags=["Reviews"])

ACTION_TO_STATUS: dict[ReviewAction, ApplicationStatus] = {
    ReviewAction.APPROVE: ApplicationStatus.APPROVED,
    ReviewAction.REJECT: ApplicationStatus.REJECTED,
    ReviewAction.UNDER_REVIEW: ApplicationStatus.UNDER_REVIEW,
}

ACTIONABLE_STATUSES = {
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.UNDER_REVIEW,
}


@router.get("/{application_id}/reviews", response_model=list[ReviewOut])
def list_reviews(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if current_user.role == Role.SALES and app.sales_rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if (
        current_user.role == Role.REVIEWER
        and app.assigned_reviewer_id != current_user.id
    ):
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
    """
    Record a reviewer action + risk decision.

    - REVIEWER: only on applications currently assigned to them.
    - ADMIN:    on any SUBMITTED or UNDER_REVIEW application.
    """
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if current_user.role == Role.REVIEWER:
        if app.assigned_reviewer_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You are not assigned to this application.",
            )

    if app.status not in ACTIONABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot record a decision on an application in status "
                f"{app.status.value}. Only SUBMITTED or UNDER_REVIEW "
                f"applications can be actioned."
            ),
        )

    review = Review(
        application_id=application_id,
        reviewer_id=current_user.id,
        action=payload.action,
        decision=payload.decision,
        comment=payload.comment,
    )
    db.add(review)

    app.status = ACTION_TO_STATUS[payload.action]
    app.risk_decision = payload.decision

    db.commit()
    db.refresh(review)
    return review