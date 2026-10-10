from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import ApplicationStatus, MerchantApplication, Role, User
from app.schemas import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    Paginated,
)

router = APIRouter(prefix="/applications", tags=["Applications"])


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
    List applications with pagination, filtering, and search.

    - SALES: only their own applications
    - REVIEWER: all applications
    - ADMIN: all applications
    """
    query = db.query(MerchantApplication)

    if current_user.role == Role.SALES:
        query = query.filter(MerchantApplication.sales_rep_id == current_user.id)

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


@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.get(MerchantApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == Role.SALES and app.sales_rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return app


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
    if current_user.role == Role.SALES and app.sales_rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if app.status != ApplicationStatus.DRAFT and current_user.role != Role.ADMIN:
        raise HTTPException(
            status_code=403, detail="Only draft applications can be edited"
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(app, field, value)
    db.commit()
    db.refresh(app)
    return app


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