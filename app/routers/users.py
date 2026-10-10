from math import ceil

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_roles
from app.models import Role, User
from app.schemas import Paginated, UserOut

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=Paginated[UserOut])
def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    role_filter: Role | None = Query(None, alias="role"),
    current_user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """List users (ADMIN only). Supports pagination and role filtering."""
    query = db.query(User)
    if role_filter is not None:
        query = query.filter(User.role == role_filter)

    total = query.count()
    rows = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    total_pages = ceil(total / limit) if total else 0

    return Paginated[UserOut](
        data=[UserOut.model_validate(r) for r in rows],
        meta={
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    )