from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Role, User
from app.security import hash_password

SEED_USERS = [
    ("sales@example.com", "Sales User", Role.SALES),
    ("reviewer@example.com", "Reviewer User", Role.REVIEWER),
    ("admin@example.com", "Admin User", Role.ADMIN),
]

DEFAULT_PASSWORD = "password123"


def seed() -> None:
    db: Session = SessionLocal()
    try:
        for email, name, role in SEED_USERS:
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                print(f"= {email} already exists, skipping")
                continue
            db.add(
                User(
                    email=email,
                    name=name,
                    role=role,
                    password_hash=hash_password(DEFAULT_PASSWORD),
                )
            )
            print(f"+ Created {email} ({role.value})")
        db.commit()
        print(f"\nSeed complete. Password for all users: {DEFAULT_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()