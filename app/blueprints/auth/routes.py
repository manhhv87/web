"""
Authentication routes for VNU-UET Research Hours Web Application.
"""

import os
import time

from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename

MAX_FAILED_LOGIN_ATTEMPTS = 5
ACCOUNT_LOCKOUT_MINUTES = 15


def _is_safe_redirect_url(target):
    """Kiểm tra URL redirect có an toàn không (chỉ cho phép relative path)."""
    if not target:
        return False
    parsed = urlparse(target)
    return parsed.scheme == "" and parsed.netloc == "" and target.startswith("/")

from app.db_models import (
    db,
    User,
    AdminRole,
    OrganizationUnit,
    Division,
    validate_email,
    validate_password,
    validate_employee_id,
)
from app.extensions import limiter
from app.services.approval import ACT_AS_SESSION_KEY, ACT_AS_USER_MODE_KEY

auth_bp = Blueprint("auth", __name__)

ALLOWED_AVATAR_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}


def _allowed_avatar_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS


def _save_avatar(file, user_id: int) -> str | None:
    """Validate, resize and save avatar image. Returns filename or None."""
    if not file or not file.filename:
        return None
    if not _allowed_avatar_file(file.filename):
        return None

    try:
        from PIL import Image

        img = Image.open(file.stream)
        img.verify()  # ensure it's a real image
        file.stream.seek(0)
        img = Image.open(file.stream)
    except Exception:
        return None

    # Resize to max 256x256, keeping aspect ratio
    img.thumbnail((256, 256), Image.LANCZOS)

    # Convert RGBA to RGB for JPEG
    ext = file.filename.rsplit(".", 1)[1].lower()
    if ext in ("jpg", "jpeg") and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    filename = f"user_{user_id}_{int(time.time())}.{ext}"
    save_path = os.path.join(current_app.config["AVATAR_UPLOAD_FOLDER"], filename)
    img.save(save_path, quality=85)
    return filename


def _delete_avatar(filename: str) -> None:
    """Delete an avatar file from disk."""
    if not filename:
        return
    path = os.path.join(current_app.config["AVATAR_UPLOAD_FOLDER"], filename)
    try:
        os.remove(path)
    except OSError:
        pass


@auth_bp.route("/setup", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def setup():
    """Tạo tài khoản admin đầu tiên - chỉ hoạt động khi chưa có admin nào"""
    # Kiểm tra đã có admin chưa (ưu tiên AdminRole)
    admin_exists = AdminRole.query.filter_by(is_active=True).first()
    if not admin_exists:
        admin_exists = User.query.filter(
            User.admin_level.in_(["department", "faculty", "university"])
        ).first()
    if admin_exists:
        flash("Hệ thống đã có admin. Vui lòng đăng nhập.", "info")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        full_name = request.form.get("full_name", "").strip()
        department = request.form.get("department", "").strip()

        # Validation
        errors = []
        email_err = validate_email(email)
        if email_err:
            errors.append(email_err)
        pw_err = validate_password(password)
        if pw_err:
            errors.append(pw_err)
        if password != confirm_password:
            errors.append("Mật khẩu xác nhận không khớp.")
        if not full_name:
            errors.append("Họ tên không được để trống.")
        if User.query.filter_by(email=email).first():
            errors.append("Email đã được sử dụng.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("auth/setup.html")

        # Tạo admin Trường (cấp cao nhất)
        user = User(
            email=email,
            full_name=full_name,
            department=department or None,
            admin_level="university",  # Admin Trường - cap cao nhat
            is_active=True,
        )
        user.set_password(password)

        db.session.add(user)
        db.session.flush()
        db.session.add(
            AdminRole(
                user_id=user.id,
                role_level="university",
                is_active=True,
                notes="Setup initial admin",
            )
        )
        db.session.commit()

        flash(f"Đã tạo tài khoản admin: {full_name}. Vui lòng đăng nhập.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/setup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    """Đăng nhập"""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        # Kiểm tra account lockout
        if user and user.locked_until and user.locked_until > datetime.utcnow():
            remaining = int((user.locked_until - datetime.utcnow()).total_seconds() / 60) + 1
            flash(
                f"Tài khoản tạm khóa do đăng nhập sai nhiều lần. Thử lại sau {remaining} phút.",
                "error",
            )
            return render_template("auth/login.html")

        if user and user.check_password(password):
            if not user.is_active:
                flash("Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên.", "error")
                return render_template("auth/login.html")

            # Reset failed login counter
            user.failed_login_count = 0
            user.locked_until = None
            db.session.commit()

            remember = request.form.get("remember") in ("1", "on", "true", "True")
            login_user(user, remember=remember)
            session.pop(ACT_AS_USER_MODE_KEY, None)
            session.pop(ACT_AS_SESSION_KEY, None)
            next_page = request.args.get("next")
            if not _is_safe_redirect_url(next_page):
                next_page = None
            return redirect(next_page or url_for("main.dashboard"))

        # Login thất bại - tăng counter
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_FAILED_LOGIN_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=ACCOUNT_LOCKOUT_MINUTES)
                user.failed_login_count = 0
                db.session.commit()
                flash(
                    f"Tài khoản tạm khóa {ACCOUNT_LOCKOUT_MINUTES} phút do đăng nhập sai nhiều lần.",
                    "error",
                )
                return render_template("auth/login.html")
            db.session.commit()

        flash("Email hoặc mật khẩu không đúng.", "error")

    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def register():
    """Đăng ký tài khoản mới"""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    # Lấy danh sách Khoa/Phòng ban
    org_units = (
        OrganizationUnit.query.filter_by(is_active=True)
        .order_by(OrganizationUnit.unit_type, OrganizationUnit.name)
        .all()
    )

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        full_name = request.form.get("full_name", "").strip()
        organization_unit_id = request.form.get("organization_unit_id", type=int)
        division_id = request.form.get("division_id", type=int)
        employee_id = request.form.get("employee_id", "").strip()

        # Validation
        errors = []

        email_err = validate_email(email)
        if email_err:
            errors.append(email_err)

        pw_err = validate_password(password)
        if pw_err:
            errors.append(pw_err)

        if password != confirm_password:
            errors.append("Mật khẩu xác nhận không khớp.")

        if not full_name:
            errors.append("Họ tên không được để trống.")

        if User.query.filter_by(email=email).first():
            errors.append("Email đã được sử dụng.")

        # Kiểm tra mã cán bộ
        eid_err = validate_employee_id(employee_id)
        if eid_err:
            errors.append(eid_err)
        elif employee_id:
            if User.query.filter_by(employee_id=employee_id).first():
                errors.append("Mã cán bộ đã được sử dụng bởi tài khoản khác.")

        # Kiểm tra Khoa/Phòng ban bắt buộc
        if not organization_unit_id:
            errors.append("Vui lòng chọn Khoa/Phòng ban.")
        else:
            org_unit = OrganizationUnit.query.get(organization_unit_id)
            if not org_unit:
                errors.append("Khoa/Phòng ban không hợp lệ.")
            elif org_unit.unit_type == "faculty" and not division_id:
                errors.append("Vui lòng chọn Bộ môn (bắt buộc đối với Khoa).")

        # Kiểm tra Bộ môn hợp lệ
        if division_id:
            division = Division.query.get(division_id)
            if not division:
                errors.append("Bộ môn không hợp lệ.")
            elif division.organization_unit_id != organization_unit_id:
                errors.append("Bộ môn không thuộc Khoa/Phòng ban đã chọn.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "auth/register.html",
                org_units=org_units,
                selected_org_unit_id=organization_unit_id,
                selected_division_id=division_id,
            )

        # Lấy tên đơn vị để lưu vào trường department (backwards compatibility)
        department_name = None
        if organization_unit_id:
            org_unit = OrganizationUnit.query.get(organization_unit_id)
            if org_unit:
                department_name = org_unit.name

        # Create user
        user = User(
            email=email,
            full_name=full_name,
            department=department_name,  # Legacy field
            organization_unit_id=organization_unit_id,
            division_id=division_id if division_id else None,
            employee_id=employee_id or None,
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Đăng ký thành công! Vui lòng đăng nhập.", "success")
        return redirect(url_for("auth.login", email=email))

    return render_template("auth/register.html", org_units=org_units)


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    """Đăng xuất - ưu tiên POST để chống CSRF, hỗ trợ GET cho backward compat."""
    session.pop(ACT_AS_USER_MODE_KEY, None)
    session.pop(ACT_AS_SESSION_KEY, None)
    logout_user()
    flash("Bạn đã đăng xuất.", "info")
    return redirect(url_for("main.index"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Cập nhật thông tin cá nhân"""
    # Lấy danh sách Khoa/Phòng ban
    org_units = (
        OrganizationUnit.query.filter_by(is_active=True)
        .order_by(OrganizationUnit.unit_type, OrganizationUnit.name)
        .all()
    )

    if request.method == "POST":
        action = request.form.get("action", "update_profile")

        # Handle avatar removal
        if action == "remove_avatar":
            _delete_avatar(current_user.avatar_filename)
            current_user.avatar_filename = None
            db.session.commit()
            flash("Đã xóa ảnh đại diện.", "success")
            return redirect(url_for("auth.profile"))

        full_name = request.form.get("full_name", "").strip()
        organization_unit_id = request.form.get("organization_unit_id", type=int)
        division_id = request.form.get("division_id", type=int)
        employee_id = request.form.get("employee_id", "").strip()

        errors = []

        if not full_name:
            errors.append("Họ tên không được để trống.")

        # Kiểm tra Khoa/Phòng ban
        if organization_unit_id:
            org_unit = OrganizationUnit.query.get(organization_unit_id)
            if not org_unit:
                errors.append("Khoa/Phòng ban không hợp lệ.")
            elif org_unit.unit_type == "faculty" and not division_id:
                errors.append("Vui lòng chọn Bộ môn (bắt buộc đối với Khoa).")

        # Kiểm tra Bộ môn hợp lệ
        if division_id:
            division = Division.query.get(division_id)
            if not division:
                errors.append("Bộ môn không hợp lệ.")
            elif (
                organization_unit_id
                and division.organization_unit_id != organization_unit_id
            ):
                errors.append("Bộ môn không thuộc Khoa/Phòng ban đã chọn.")

        # Kiểm tra mã cán bộ
        eid_err = validate_employee_id(employee_id)
        if eid_err:
            errors.append(eid_err)
        elif employee_id:
            existing_user = User.query.filter(
                User.employee_id == employee_id, User.id != current_user.id
            ).first()
            if existing_user:
                errors.append("Mã cán bộ đã được sử dụng bởi tài khoản khác.")

        # Handle avatar upload
        avatar_file = request.files.get("avatar")
        if avatar_file and avatar_file.filename:
            if not _allowed_avatar_file(avatar_file.filename):
                errors.append("Ảnh đại diện chỉ chấp nhận định dạng: JPG, PNG, GIF, WebP.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("auth/profile.html", org_units=org_units)

        # Save avatar if provided
        if avatar_file and avatar_file.filename:
            new_filename = _save_avatar(avatar_file, current_user.id)
            if new_filename:
                _delete_avatar(current_user.avatar_filename)
                current_user.avatar_filename = new_filename
            else:
                flash("Không thể xử lý ảnh đại diện. Vui lòng thử file khác.", "warning")

        # Lấy tên đơn vị để lưu vào trường department (backwards compatibility)
        department_name = None
        if organization_unit_id:
            org_unit = OrganizationUnit.query.get(organization_unit_id)
            if org_unit:
                department_name = org_unit.name

        current_user.full_name = full_name
        current_user.department = department_name  # Legacy field
        current_user.organization_unit_id = organization_unit_id
        current_user.division_id = division_id if division_id else None
        current_user.employee_id = employee_id or None

        db.session.commit()
        flash("Cập nhật thông tin thành công!", "success")
        return redirect(url_for("auth.profile"))

    return render_template("auth/profile.html", org_units=org_units)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Đổi mật khẩu"""
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_user.check_password(current_password):
            flash("Mật khẩu hiện tại không đúng.", "error")
            return render_template("auth/change_password.html")

        pw_err = validate_password(new_password)
        if pw_err:
            flash(pw_err, "error")
            return render_template("auth/change_password.html")

        if new_password != confirm_password:
            flash("Mật khẩu xác nhận không khớp.", "error")
            return render_template("auth/change_password.html")

        current_user.set_password(new_password)
        db.session.commit()

        flash("Đổi mật khẩu thành công!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/change_password.html")
