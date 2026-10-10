"""
Demo data seeder for the Merchant Portal.

Generates 120+ merchant applications (60 per sales rep) across every status,
with matching review history, so the dashboard's pagination, filtering, and
search have realistic data to work against.

Safe to re-run: applications and reviews are truncated before seeding,
users and refresh tokens are left untouched.

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
    RiskDecision,
    Role,
    User,
)
from app.security import hash_password

DEFAULT_PASSWORD = "password123"

# ---------------------------------------------------------------------------
# Static user roster
# ---------------------------------------------------------------------------

EXTRA_USERS = [
    ("sales2@example.com", "Sales Rep Two", Role.SALES),
]

SALES_REPS = ["sales@example.com", "sales2@example.com"]
REVIEWER_EMAIL = "reviewer@example.com"

# ---------------------------------------------------------------------------
# Name generators for realistic-looking merchant data
# ---------------------------------------------------------------------------

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
    "Retail",
    "E-commerce",
    "Hospitality",
    "Professional Services",
    "Food & Beverage",
    "Other",
]

# Roughly reflects a realistic pipeline split.
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

# Total applications to generate across all sales reps.
TOTAL_APPLICATIONS = 120

# Seed the RNG so runs are reproducible.
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


# ---------------------------------------------------------------------------
# Truncation and user bootstrap
# ---------------------------------------------------------------------------

def _truncate_business_data(db: Session) -> None:
    """Wipe applications and reviews. Keeps users and their sessions intact."""
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


# ---------------------------------------------------------------------------
# Application generation
# ---------------------------------------------------------------------------

def _generate_applications(db: Session) -> list[MerchantApplication]:
    now = datetime.now(timezone.utc)

    # Resolve sales reps up front so we do not query per row.
    reps = {
        email: db.query(User).filter(User.email == email).first()
        for email in SALES_REPS
    }
    for email, rep in reps.items():
        if rep is None:
            raise RuntimeError(f"Missing sales rep: {email}. Run `python -m app.seed` first.")

    created: list[MerchantApplication] = []
    # Precompute the status sequence so distribution is exact.
    statuses = _status_sequence(TOTAL_APPLICATIONS)

    for index in range(TOTAL_APPLICATIONS):
        rep_email = SALES_REPS[index % len(SALES_REPS)]
        rep = reps[rep_email]
        status = statuses[index]

        merchant_name = _merchant_name(index)
        business_type = RNG.choice(BUSINESS_TYPES)
        annual_revenue = RNG.randint(60_000, 2_500_000)
        slug = merchant_name.lower().replace(" ", "").replace("&", "and").replace(".", "")
        contact_email = f"contact@{slug}.test"
        contact_phone = f"+1-555-{RNG.randint(1000, 9999)}"

        # Backdate creation time so sorting produces a plausible order.
        days_ago = RNG.randint(0, 90)
        created_at = now - timedelta(days=days_ago, hours=RNG.randint(0, 23))
        submitted_at = (
            created_at + timedelta(hours=RNG.randint(1, 48))
            if status != ApplicationStatus.DRAFT
            else None
        )

        app = MerchantApplication(
            merchant_name=merchant_name,
            business_type=business_type,
            annual_revenue=annual_revenue,
            contact_email=contact_email,
            contact_phone=contact_phone,
            status=status,
            sales_rep_id=rep.id,
            submitted_at=submitted_at,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(app)
        created.append(app)

    db.flush()
    return created


def _merchant_name(index: int) -> str:
    """Deterministic unique merchant name so filtering is predictable."""
    prefix = NAME_PREFIXES[index % len(NAME_PREFIXES)]
    suffix = NAME_SUFFIXES[(index * 7) % len(NAME_SUFFIXES)]
    return f"{prefix} {suffix}"


def _status_sequence(total: int) -> list[ApplicationStatus]:
    """Produce a deterministic list of statuses matching the distribution."""
    sequence: list[ApplicationStatus] = []
    for status, ratio in STATUS_DISTRIBUTION:
        count = int(round(total * ratio))
        sequence.extend([status] * count)

    # Pad / trim to exactly `total`.
    while len(sequence) < total:
        sequence.append(ApplicationStatus.SUBMITTED)
    sequence = sequence[:total]

    # Shuffle so statuses are interleaved, not blocked by group.
    RNG.shuffle(sequence)
    return sequence


# ---------------------------------------------------------------------------
# Review generation
# ---------------------------------------------------------------------------

def _insert_reviews(db: Session, apps: list[MerchantApplication]) -> None:
    reviewer = db.query(User).filter(User.email == REVIEWER_EMAIL).first()
    if reviewer is None:
        raise RuntimeError(f"Missing reviewer: {REVIEWER_EMAIL}")

    for app in apps:
        decision, comment = _review_for_status(app.status)
        if decision is None:
            continue

        review_created = (app.submitted_at or app.created_at) + timedelta(
            days=RNG.randint(0, 5), hours=RNG.randint(1, 20)
        )
        db.add(
            Review(
                application_id=app.id,
                reviewer_id=reviewer.id,
                decision=decision,
                comment=comment,
                created_at=review_created,
            )
        )
        app.risk_decision = decision
        app.updated_at = review_created


def _review_for_status(
    status: ApplicationStatus,
) -> tuple[RiskDecision | None, str | None]:
    """Return the appropriate risk decision and comment for a status, if any."""
    if status == ApplicationStatus.APPROVED:
        return RNG.choice([RiskDecision.LOW, RiskDecision.LOW, RiskDecision.MEDIUM]), RNG.choice(APPROVED_COMMENTS)
    if status == ApplicationStatus.REJECTED:
        return RiskDecision.REJECTED, RNG.choice(REJECTED_COMMENTS)
    if status == ApplicationStatus.UNDER_REVIEW:
        return RNG.choice([RiskDecision.MEDIUM, RiskDecision.HIGH]), RNG.choice(UNDER_REVIEW_COMMENTS)
    return None, None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

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