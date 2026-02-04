#!/usr/bin/env python3
"""
One-off backfill/sync: legacy users.admin_level -> admin_roles.

Usage:
    python scripts/backfill_admin_roles.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import create_app  # noqa: E402
from app.db_models import db, User, AdminRole  # noqa: E402


def backfill_admin_roles():
    created = 0
    skipped = 0
    updated = 0

    # 1) Ensure roles exist for legacy admin_level
    admin_users = User.query.filter(
        User.admin_level.in_(["department", "faculty", "university"])
    ).all()
    for user in admin_users:
        role_level = user.admin_level
        if role_level == "faculty" and not user.organization_unit_id:
            skipped += 1
            continue
        if role_level == "department" and not user.division_id:
            skipped += 1
            continue

        existing = AdminRole.query.filter_by(
            user_id=user.id,
            role_level=role_level,
            organization_unit_id=(
                user.organization_unit_id if role_level in ["faculty", "department"] else None
            ),
            division_id=(user.division_id if role_level == "department" else None),
            is_active=True,
        ).first()
        if existing:
            continue

        AdminRole.grant_role(
            user_id=user.id,
            role_level=role_level,
            organization_unit_id=(
                user.organization_unit_id if role_level in ["faculty", "department"] else None
            ),
            division_id=(user.division_id if role_level == "department" else None),
            notes="Backfilled from users.admin_level",
        )
        created += 1

    # 2) Sync admin_level from roles (source of truth)
    role_user_ids = [
        row[0]
        for row in db.session.query(AdminRole.user_id)
        .filter(AdminRole.is_active == True)
        .distinct()
        .all()
    ]
    for user_id in role_user_ids:
        user = User.query.get(user_id)
        if not user:
            continue
        highest = AdminRole.get_highest_level(user_id)
        if user.admin_level != highest:
            user.admin_level = highest
            updated += 1

    db.session.commit()

    print(f">>> Backfill done. Created roles: {created}, updated admin_level: {updated}, skipped: {skipped}")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        backfill_admin_roles()
