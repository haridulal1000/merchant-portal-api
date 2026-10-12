from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_roles
from app.models import (
    MerchantApplication,
    Review,
    Role,
    User,
)
from app.schemas import Paginated, UserOut, UserRoleUpdate

router = APIRouter(prefix="/users", tags=["Users"])


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("", response_model=Paginated[UserOut])
def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    role_filter: Role | None = Query(None, alias="role"),
    _current_user: User = Depends(require_roles(Role.ADMIN)),
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


# ---------------------------------------------------------------------------
# Change role
# ---------------------------------------------------------------------------

@router.patch("/{user_id}/role", response_model=UserOut)
def update_user_role(
    user_id: str,
    payload: UserRoleUpdate,
    current_user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Change another user's role.

    Safety rules:
      - An admin cannot change their own role. Prevents accidental self-lockout
        and forces a deliberate peer action when transferring admin privileges.
      - The last remaining admin cannot be demoted. Without this, a fresh
        deployment with a single admin would have no way to recover.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot change your own role.",
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.role == payload.role:
        return user  # idempotent no-op

    if user.role == Role.ADMIN and payload.role != Role.ADMIN:
        admin_count = db.query(User).filter(User.role == Role.ADMIN).count()
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last remaining admin.",
            )

    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    current_user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Delete another user.

    Safety rules:
      - An admin cannot delete themselves.
      - The last remaining admin cannot be deleted.
      - A user who owns applications or has recorded reviews cannot be
        deleted. The FK constraints on `merchant_applications.sales_rep_id`
        and `reviews.reviewer_id` are restrictive, so this is enforced at
        the DB level too — but we check up front to return a clear 400
        instead of a 500.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your own account.",
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.role == Role.ADMIN:
        admin_count = db.query(User).filter(User.role == Role.ADMIN).count()
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last remaining admin.",
            )

    app_count = (
        db.query(MerchantApplication)
        .filter(MerchantApplication.sales_rep_id == user_id)
        .count()
    )
    review_count = (
        db.query(Review).filter(Review.reviewer_id == user_id).count()
    )

    if app_count > 0 or review_count > 0:
        parts: list[str] = []
        if app_count:
            parts.append(f"{app_count} application{'s' if app_count != 1 else ''}")
        if review_count:
            parts.append(f"{review_count} review{'s' if review_count != 1 else ''}")
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot delete this user: they own "
                f"{' and '.join(parts)}. Reassign or remove those first."
            ),
        )

    db.delete(user)
    db.commit()