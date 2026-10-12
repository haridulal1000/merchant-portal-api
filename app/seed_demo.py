"""
Demo data seeder for the Merchant Portal.

Generates 120 merchant applications (60 per sales rep) across every status,
assigns non-draft applications to the reviewer, and creates matching review
history.

Run inside the API container:
    docker compose exec api python -m app.seed_demo
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    ApplicationStatus,
    MerchantApplication,
    Review,
    ReviewAction,
    RiskDecision,
    Role,
    User,
)
from app.security import hash_password

DEFAULT_PASSWORD = "password123"

EXTRA_USERS = [
    ("sales2@example.com", "Sales Rep Two", Role.SALES),
]

SALES_REPS = ["sales@example.com", "sales2@example.com"]
REVIEWER_EMAIL = "reviewer@example.com"

NAME_PREFIXES = [
    "Acme", "Blue Harbor", "Nexus", "Sunrise", "Cornerstone", "Summit",
    "Pixel & Pine", "Harborview", "Green Leaf", "Ironclad", "Coastal",
    "Metro", "Verdant", "Luna", "Cascade", "Northern", "Silver", "Maple",
    "Redwood", "Golden", "Crystal", "Aurora", "Pioneer", "Atlantic",
    "Cedar", "Beacon", "Sterling", "Ironwood", "Bright", "Falcon",
    "Phoenix", "Mosaic", "Lighthouse", "Juniper", "Sierra",
]

NAME_SUFFIXES = [
    "Widgets", "Coffee", "Digital", "Bakery", "Legal", "Outdoor Gear",
    "Studio", "Hotels", "Grocers", "Security", "Bikes", "Fitness",
    "Landscaping", "Beauty Supply", "Brewing Co.", "Traders", "Supply Co.",
    "Collective", "Workshops", "Partners", "Solutions", "Foods",
    "Restaurant Group", "Logistics", "Distribution", "Manufacturing",
    "Consulting", "Analytics", "Labs", "Ventures",
]

BUSINESS_TYPES = [
    "Retail", "E-commerce", "Hospitality",
    "Professional Services", "Food & Beverage", "Other",
]

STATUS_DISTRIBUTION = [
    (ApplicationStatus.DRAFT,        0.15),
    (ApplicationStatus.SUBMITTED,    0.25),
    (ApplicationStatus.UNDER_REVIEW, 0.15),
    (ApplicationStatus.APPROVED,     0.35),
    (ApplicationStatus.REJECTED,     0.10),
]

APPROVED_COMMENTS = [
    "Clean history, stable revenue. Approved.",
    "Long-standing business, no red flags.",
    "Moderate risk, approved with monitoring.",
    "Small but consistent. Approved.",
    "Verified registrations. Approved.",
]

REJECTED_COMMENTS = [
    "Adverse credit history and unresolved disputes.",
    "Business registration could not be verified.",
    "Revenue does not support requested exposure.",
    "Multiple prior defaults on record.",
]

UNDER_REVIEW_COMMENTS = [
    "Awaiting updated financial statements.",
    "High exposure. Escalated for senior review.",
    "Requested additional documentation from merchant.",
    "Pending reference checks.",
]

TOTAL_APPLICATIONS = 120
RNG = random.Random(20261011)


def seed_demo() -> None:
    db: Session = SessionLocal()
    try:
        _truncate_business_data(db)
        _ensure_extra_users(db)
        apps = _generate_applications(db)
        _insert_reviews(db, apps)
        db.commit()

        by_status = _count_by_status(db)
        print("")
        print("Demo seed complete.")
        print(f"  Users:        {db.query(User).count()}")
        print(f"  Applications: {db.query(MerchantApplication).count()}")
        print(f"  Reviews:      {db.query(Review).count()}")
        print("  Status breakdown:")
        for status, count in by_status.items():
            print(f"    {status:<14} {count}")
        print("")
        print(f"Password for all users: {DEFAULT_PASSWORD}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _truncate_business_data(db: Session) -> None:
    db.query(Review).delete()
    db.query(MerchantApplication).delete()
    db.flush()


def _ensure_extra_users(db: Session) -> None:
    for email, name, role in EXTRA_USERS:
        exists = db.query(User).filter(User.email == email).first()
        if exists:
            continue
        db.add(
            User(
                email=email,
                name=name,
                role=role,
                password_hash=hash_password(DEFAULT_PASSWORD),
            )
        )
    db.flush()


def _generate_applications(db: Session) -> list[MerchantApplication]:
    now = datetime.now(timezone.utc)

    reps = {
        email: db.query(User).filter(User.email == email).first()
        for email in SALES_REPS
    }
    for email, rep in reps.items():
        if rep is None:
            raise RuntimeError(
                f"Missing sales rep: {email}. Run `python -m app.seed` first."
            )

    reviewer = db.query(User).filter(User.email == REVIEWER_EMAIL).first()
    if reviewer is None:
        raise RuntimeError(f"Missing reviewer: {REVIEWER_EMAIL}")

    created: list[MerchantApplication] = []
    statuses = _status_sequence(TOTAL_APPLICATIONS)

    for index in range(TOTAL_APPLICATIONS):
        rep_email = SALES_REPS[index % len(SALES_REPS)]
        rep = reps[rep_email]
        status = statuses[index]

        merchant_name = _merchant_name(index)
        business_type = RNG.choice(BUSINESS_TYPES)
        annual_revenue = RNG.randint(60_000, 2_500_000)
        slug = (
            merchant_name.lower()
            .replace(" ", "").replace("&", "and").replace(".", "")
        )
        contact_email = f"contact@{slug}.test"
        contact_phone = f"+1-555-{RNG.randint(1000, 9999)}"

        days_ago = RNG.randint(0, 90)
        created_at = now - timedelta(days=days_ago, hours=RNG.randint(0, 23))
        submitted_at = (
            created_at + timedelta(hours=RNG.randint(1, 48))
            if status != ApplicationStatus.DRAFT
            else None
        )

        # Non-draft applications are assigned to the reviewer, matching
        # what a real admin would have done after submission.
        if status == ApplicationStatus.DRAFT:
            assigned_reviewer_id = None
            assigned_at = None
        else:
            assigned_reviewer_id = reviewer.id
            assigned_at = submitted_at

        app = MerchantApplication(
            merchant_name=merchant_name,
            business_type=business_type,
            annual_revenue=annual_revenue,
            contact_email=contact_email,
            contact_phone=contact_phone,
            status=status,
            sales_rep_id=rep.id,
            assigned_reviewer_id=assigned_reviewer_id,
            assigned_at=assigned_at,
            submitted_at=submitted_at,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(app)
        created.append(app)

    db.flush()
    return created


def _merchant_name(index: int) -> str:
    prefix = NAME_PREFIXES[index % len(NAME_PREFIXES)]
    suffix = NAME_SUFFIXES[(index * 7) % len(NAME_SUFFIXES)]
    return f"{prefix} {suffix}"


def _status_sequence(total: int) -> list[ApplicationStatus]:
    sequence: list[ApplicationStatus] = []
    for status, ratio in STATUS_DISTRIBUTION:
        count = int(round(total * ratio))
        sequence.extend([status] * count)
    while len(sequence) < total:
        sequence.append(ApplicationStatus.SUBMITTED)
    sequence = sequence[:total]
    RNG.shuffle(sequence)
    return sequence


def _insert_reviews(db: Session, apps: list[MerchantApplication]) -> None:
    reviewer = db.query(User).filter(User.email == REVIEWER_EMAIL).first()
    if reviewer is None:
        raise RuntimeError(f"Missing reviewer: {REVIEWER_EMAIL}")

    for app in apps:
        action, decision, comment = _review_for_status(app.status)
        if action is None:
            continue

        review_created = (app.submitted_at or app.created_at) + timedelta(
            days=RNG.randint(0, 5), hours=RNG.randint(1, 20)
        )
        db.add(
            Review(
                application_id=app.id,
                reviewer_id=reviewer.id,
                action=action,
                decision=decision,
                comment=comment,
                created_at=review_created,
            )
        )
        app.risk_decision = decision
        app.updated_at = review_created


def _review_for_status(
    status: ApplicationStatus,
) -> tuple[ReviewAction | None, RiskDecision | None, str | None]:
    if status == ApplicationStatus.APPROVED:
        return (
            ReviewAction.APPROVE,
            RNG.choice([RiskDecision.LOW, RiskDecision.LOW, RiskDecision.MEDIUM]),
            RNG.choice(APPROVED_COMMENTS),
        )
    if status == ApplicationStatus.REJECTED:
        return (
            ReviewAction.REJECT,
            RiskDecision.REJECTED,
            RNG.choice(REJECTED_COMMENTS),
        )
    if status == ApplicationStatus.UNDER_REVIEW:
        return (
            ReviewAction.UNDER_REVIEW,
            RNG.choice([RiskDecision.MEDIUM, RiskDecision.HIGH]),
            RNG.choice(UNDER_REVIEW_COMMENTS),
        )
    return None, None, None


def _count_by_status(db: Session) -> dict[str, int]:
    from sqlalchemy import func

    rows = (
        db.query(MerchantApplication.status, func.count(MerchantApplication.id))
        .group_by(MerchantApplication.status)
        .order_by(MerchantApplication.status)
        .all()
    )
    return {status.value: count for status, count in rows}


if __name__ == "__main__":
    seed_demo()