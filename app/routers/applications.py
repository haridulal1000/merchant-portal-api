from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import (
    ApplicationStatus,
    MerchantApplication,
    Role,
    User,
)
from app.schemas import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    AssignReviewerRequest,
    Paginated,
)

router = APIRouter(prefix="/applications", tags=["Applications"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _with_relations(query):
    """Eager-load the sales_rep and assigned_reviewer for every row."""
    return query.options(
        joinedload(MerchantApplication.sales_rep),
        joinedload(MerchantApplication.assigned_reviewer),
    )


def _visibility_filter(query, user: User):
    """
    Restrict the query to what the current user is permitted to see.

    - SALES:    own applications only
    - REVIEWER: applications assigned to them only
    - ADMIN:    no restriction
    """
    if user.role == Role.SALES:
        return query.filter(MerchantApplication.sales_rep_id == user.id)
    if user.role == Role.REVIEWER:
        return query.filter(MerchantApplication.assigned_reviewer_id == user.id)
    return query


def _ensure_can_view(app: MerchantApplication, user: User) -> None:
    """Row-level access check for a single application."""
    if user.role == Role.SALES and app.sales_rep_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if (
        user.role == Role.REVIEWER
        and app.assigned_reviewer_id != user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("", response_model=Paginated[ApplicationOut])
def list_applications(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status_filter: ApplicationStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, min_length=1, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List applications the current user can see.

    - SALES:    own applications
    - REVIEWER: applications assigned to them
    - ADMIN:    all applications
    """
    query = _with_relations(db.query(MerchantApplication))
    query = _visibility_filter(query, current_user)

    if status_filter is not None:
        query = query.filter(MerchantApplication.status == status_filter)

    if search:
        like = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(MerchantApplication.merchant_name).like(like),
                func.lower(MerchantApplication.contact_email).like(like),
            )
        )

    total = query.count()
    rows = (
        query.order_by(MerchantApplication.updated_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    total_pages = ceil(total / limit) if total else 0

    return Paginated[ApplicationOut](
        data=[ApplicationOut.model_validate(r) for r in rows],
        meta={
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    )


# ---------------------------------------------------------------------------
# Read one
# ---------------------------------------------------------------------------

@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = (
        _with_relations(db.query(MerchantApplication))
        .filter(MerchantApplication.id == application_id)
        .first()
    )
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    _ensure_can_view(app, current_user)
    return app


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post("", response_model=ApplicationOut, status_code=201)
def create_application(
    payload: ApplicationCreate,
    current_user: User = Depends(require_roles(Role.SALES, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    app = MerchantApplication(
        merchant_name=payload.merchant_name,
        business_type=payload.business_type,
        annual_revenue=payload.annual_revenue,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        sales_rep_id=current_user.id,
        status=ApplicationStatus.DRAFT,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    current_user: User = Depends(require_roles(Role.SALES, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if current_user.role == Role.SALES:
        if app.sales_rep_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        if app.status != ApplicationStatus.DRAFT:
            raise HTTPException(
                status_code=403,
                detail="Only draft applications can be edited",
            )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(app, field, value)

    db.commit()
    db.refresh(app)
    return app


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@router.patch("/{application_id}/submit", response_model=ApplicationOut)
def submit_application(
    application_id: str,
    current_user: User = Depends(require_roles(Role.SALES, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if current_user.role == Role.SALES and app.sales_rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if app.status != ApplicationStatus.DRAFT:
        raise HTTPException(
            status_code=400, detail="Only draft applications can be submitted"
        )

    app.status = ApplicationStatus.SUBMITTED
    app.submitted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app)
    return app


# ---------------------------------------------------------------------------
# Assign reviewer (ADMIN only)
# ---------------------------------------------------------------------------

@router.patch("/{application_id}/assign", response_model=ApplicationOut)
def assign_reviewer(
    application_id: str,
    payload: AssignReviewerRequest,
    current_user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Assign or unassign a reviewer.

    - Pass `reviewer_id` to assign.
    - Pass `reviewer_id: null` to unassign.
    - DRAFT applications cannot be assigned — they have not been submitted yet.
    """
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if app.status == ApplicationStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Draft applications cannot be assigned. Submit it first.",
        )

    if payload.reviewer_id is None:
        app.assigned_reviewer_id = None
        app.assigned_at = None
    else:
        reviewer = db.get(User, payload.reviewer_id)
        if reviewer is None:
            raise HTTPException(status_code=404, detail="Reviewer not found")
        if reviewer.role != Role.REVIEWER:
            raise HTTPException(
                status_code=400,
                detail="Applications can only be assigned to users with the REVIEWER role.",
            )
        app.assigned_reviewer_id = reviewer.id
        app.assigned_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(app)
    return app


# ---------------------------------------------------------------------------
# Delete (ADMIN only)
# ---------------------------------------------------------------------------

@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: str,
    current_user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """Delete an application. Reviews are removed via ON DELETE CASCADE."""
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    db.delete(app)
    db.commit()