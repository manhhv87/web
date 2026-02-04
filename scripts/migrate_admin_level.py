#!/usr/bin/env python
"""
Script để migrate hệ thống phân quyền từ is_admin sang admin_level.

Chạy script này sau khi đã tạo các bảng mới trong database:
    python scripts/migrate_admin_level.py

Script sẽ:
1. Cập nhật users có is_admin=True thành admin_level='university'
2. Cập nhật users còn lại thành admin_level='none'
3. Tạo các bảng admin_permission_logs và approval_logs nếu chưa có
"""

import os
import sys

# Thêm thư mục gốc vào path để import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.db_models import db, User, AdminPermissionLog, ApprovalLog


def migrate_admin_levels():
    """Migrate is_admin flag sang admin_level"""
    app = create_app()

    with app.app_context():
        print("=" * 60)
        print("MIGRATE ADMIN LEVEL")
        print("=" * 60)

        # Tạo các bảng mới nếu chưa có
        print("\n1. Kiểm tra và tạo bảng mới...")
        db.create_all()
        print("   ✓ Các bảng đã sẵn sàng")

        # Đếm users hiện tại
        total_users = User.query.count()
        print(f"\n2. Tổng số users: {total_users}")

        # Migrate admin users
        print("\n3. Migrate admin users...")

        # Tìm users có is_admin=True (cũ) hoặc chưa có admin_level
        migrated_count = 0

        # Cập nhật users có admin_level là NULL hoặc rỗng
        users_to_migrate = User.query.filter(
            (User.admin_level == None) | (User.admin_level == "")
        ).all()

        for user in users_to_migrate:
            # Kiểm tra xem user có là admin cũ không (nếu có trường is_admin)
            old_is_admin = getattr(user, '_is_admin', False)

            if old_is_admin:
                user.admin_level = "university"
                print(f"   → {user.email}: is_admin=True → admin_level='university'")
            else:
                user.admin_level = "none"
            migrated_count += 1

        # Commit
        db.session.commit()
        print(f"\n   ✓ Đã migrate {migrated_count} users")

        # Thống kê sau migrate
        print("\n4. Thống kê sau migrate:")
        university_count = User.query.filter_by(admin_level="university").count()
        faculty_count = User.query.filter_by(admin_level="faculty").count()
        department_count = User.query.filter_by(admin_level="department").count()
        none_count = User.query.filter_by(admin_level="none").count()

        print(f"   - Admin Trường (university): {university_count}")
        print(f"   - Admin Khoa (faculty): {faculty_count}")
        print(f"   - Admin Bộ môn (department): {department_count}")
        print(f"   - User thường (none): {none_count}")

        print("\n" + "=" * 60)
        print("MIGRATE HOÀN TẤT!")
        print("=" * 60)


def show_current_admins():
    """Hiển thị danh sách admin hiện tại"""
    app = create_app()

    with app.app_context():
        print("\nDANH SÁCH ADMIN HIỆN TẠI:")
        print("-" * 60)

        admins = User.query.filter(User.admin_level != "none").all()
        if not admins:
            print("Chưa có admin nào.")
        else:
            for admin in admins:
                print(f"  {admin.email}")
                print(f"    - Họ tên: {admin.full_name}")
                print(f"    - Cấp admin: {admin.admin_level_display}")
                print(f"    - Đơn vị: {admin.full_organization_name}")
                print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--show":
        show_current_admins()
    else:
        migrate_admin_levels()
        show_current_admins()
