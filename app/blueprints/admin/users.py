"""Admin user management routes."""

from __future__ import annotations

from flask_login import login_required
from urllib.parse import urlencode

from . import admin_bp
from .helpers import *  # noqa: F403


@admin_bp.route("/users")
@login_required
@admin_required
def list_users():
    """Danh sách người dùng (theo phạm vi admin)"""
    effective_level = effective_admin_level(current_user)
    # Lọc users theo phạm vi quyền
    query = filter_users_by_scope(User.query, current_user)
    if effective_level == "faculty":
        query = query.filter(
            db.or_(
                User.admin_level.in_(["none", "department", "faculty"]),
                User.admin_level.is_(None),
            )
        )
    elif effective_level == "department":
        query = query.filter(
            db.or_(User.admin_level.in_(["none", "department"]), User.admin_level.is_(None))
        )

    page = request.args.get("page", type=int, default=1)
    per_page = request.args.get("per_page", type=int, default=20)
    per_page = max(10, min(per_page, 100))

    pagination = db.paginate(
        query.order_by(User.created_at.desc()),
        page=page,
        per_page=per_page,
        error_out=False,
    )
    users = pagination.items

    base_params = request.args.to_dict(flat=True)
    base_params.pop("page", None)
    base_query = urlencode(base_params)
    pagination_base_url = (
        url_for("admin.list_users")
        + (f"?{base_query}&page=" if base_query else "?page=")
    )

    # Tính tổng giờ cho mỗi user
    scoped_users = []
    for user in users:
        user.can_view = can_view_user_scoped(current_user, user)
        if not user.can_view:
            continue
        pubs = Publication.query.filter_by(user_id=user.id, is_approved=True).all()
        projects = Project.query.filter_by(user_id=user.id, is_approved=True).all()
        activities = OtherActivity.query.filter_by(
            user_id=user.id, is_approved=True
        ).all()

        summary = calculate_total_research_hours(pubs, projects, activities)
        user.total_hours = summary["total_hours"]
        user.pub_count = len(pubs)
        user.project_count = len(projects)
        # Kiểm tra có thể quản lý user này không
        user.can_manage = can_manage_user_scoped(current_user, user)
        scoped_users.append(user)

    return render_template(
        "admin/users/list.html",
        users=scoped_users,
        pagination=pagination,
        per_page=per_page,
        pagination_base_url=pagination_base_url,
        admin_level=effective_level,
        can_add_user=(effective_level in ["university", "faculty", "department"]),
    )


@admin_bp.route("/users/<int:user_id>")
@login_required
@admin_required
def view_user(user_id):
    """Xem chi tiết người dùng"""
    user = User.query.get_or_404(user_id)

    # Kiểm tra quyền xem (theo phạm vi)
    if not can_view_user_scoped(current_user, user):
        flash("Bạn không có quyền xem thông tin người dùng này.", "error")
        return redirect(url_for("admin.list_users"))

    scoped_user = (
        filter_users_by_scope(User.query, current_user)
        .filter(User.id == user.id)
        .first()
    )
    if not scoped_user:
        flash("Người dùng này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_users"))

    # Lấy tất cả hoạt động của user
    publications = (
        Publication.query.filter_by(user_id=user.id)
        .order_by(Publication.year.desc())
        .all()
    )
    projects = (
        Project.query.filter_by(user_id=user.id)
        .order_by(Project.start_year.desc())
        .all()
    )
    activities = (
        OtherActivity.query.filter_by(user_id=user.id)
        .order_by(OtherActivity.year.desc())
        .all()
    )

    # Tính giờ
    for pub in publications:
        hours = calculate_publication_hours(pub)
        pub.base_hours = hours["base_hours"]
        pub.author_hours = hours["author_hours"]

    for proj in projects:
        hours = calculate_project_hours_from_model(proj)
        proj.total_hours = hours["total_hours"]
        proj.user_hours = hours["user_hours"]

    for act in activities:
        act.hours = calculate_other_activity_hours_from_model(act)

    # Tổng hợp
    summary = calculate_total_research_hours(publications, projects, activities)

    # Lấy lịch sử gán quyền admin
    admin_logs = (
        AdminPermissionLog.query.filter_by(user_id=user.id)
        .order_by(AdminPermissionLog.performed_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "admin/users/view.html",
        user=user,
        publications=publications,
        projects=projects,
        activities=activities,
        summary=summary,
        admin_logs=admin_logs,
        can_manage=can_manage_user_scoped(current_user, user),
        can_assign_admin=can_assign_admin_level_scoped(
            current_user, user.highest_admin_level
        ),
    )


@admin_bp.route("/users/<int:user_id>/set-admin-level", methods=["POST"])
@login_required
@admin_required
def set_user_admin_level(user_id):
    """
    Gán/thay đổi cấp admin cho user.

    POST params:
        new_level: 'none', 'department', 'faculty', 'university'
        notes: Ghi chú (tùy chọn)
    """
    flash(
        "Chức năng phân quyền cũ đã bị vô hiệu. Vui lòng dùng mục Quản lý Admin.",
        "warning",
    )
    return redirect(url_for("admin.list_admins"))


@admin_bp.route("/users/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
@admin_required
def toggle_user_admin(user_id):
    """
    Cấp/thu hồi quyền admin (backwards compatible).
    Sử dụng admin_level thay vì is_admin.
    """
    flash(
        "Chức năng phân quyền cũ đã bị vô hiệu. Vui lòng dùng mục Quản lý Admin.",
        "warning",
    )
    return redirect(url_for("admin.list_admins"))


@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@login_required
@university_admin_required  # Chỉ Admin Trường mới khóa/mở tài khoản
def toggle_user_active(user_id):
    """Khóa/mở khóa tài khoản - Chỉ Admin Trường"""
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Không thể khóa tài khoản của chính mình.", "error")
        return redirect(url_for("admin.list_users"))

    if user.is_active and user.has_admin_role("university"):
        remaining = count_effective_admins_by_scope(
            "university", exclude_user_id=user.id
        )
        if remaining <= 0:
            flash("Không thể khóa Admin Trường cuối cùng.", "error")
            return redirect(url_for("admin.list_users"))

    user.is_active = not user.is_active
    db.session.commit()

    if user.is_active:
        flash(f"Đã mở khóa tài khoản {user.full_name}.", "success")
    else:
        flash(f"Đã khóa tài khoản {user.full_name}.", "success")

    return redirect(url_for("admin.list_users"))


@admin_bp.route("/users/add", methods=["GET", "POST"])
@login_required
@admin_required  # Admin Trường/Khoa/Bộ môn đều có thể thêm user trong phạm vi
def add_user():
    """Tạo người dùng mới - theo phạm vi admin"""
    effective_level = effective_admin_level(current_user)
    org_units, divisions, _scoped_users, _ = build_scope_filter_data(current_user)
    allowed_org_unit_ids = {ou.id for ou in org_units}
    allowed_division_ids = {div.id for div in divisions}

    if effective_level != "university" and not allowed_org_unit_ids:
        flash("Bạn chưa có phạm vi để thêm người dùng.", "error")
        return redirect(url_for("admin.list_users"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        organization_unit_id = request.form.get("organization_unit_id", type=int)
        division_id = request.form.get("division_id", type=int)
        employee_id = request.form.get("employee_id", "").strip()
        # Chỉ tạo user thường ở màn hình thêm người dùng.
        # Quyền admin phải gán qua Quản lý Admin.
        admin_level = "none"

        # Validation
        errors = []
        email_err = validate_email(email)
        if email_err:
            errors.append(email_err)
        pw_err = validate_password(password)
        if pw_err:
            errors.append(pw_err)
        if not full_name:
            errors.append("Họ tên không được để trống.")
        if User.query.filter_by(email=email).first():
            errors.append("Email đã được sử dụng.")
        eid_err = validate_employee_id(employee_id)
        if eid_err:
            errors.append(eid_err)
        elif employee_id and User.query.filter_by(employee_id=employee_id).first():
            errors.append("Mã cán bộ đã được sử dụng.")
        # Kiểm tra Khoa/Phòng ban và Bộ môn
        if not organization_unit_id:
            errors.append("Vui lòng chọn Khoa/Phòng ban.")
        else:
            org_unit = OrganizationUnit.query.get(organization_unit_id)
            if not org_unit:
                errors.append("Khoa/Phòng ban không hợp lệ.")
            elif org_unit.unit_type == "office":
                division_id = None

        # Kiểm tra phạm vi theo cấp admin (act-as)
        if effective_level != "university":
            if (
                organization_unit_id
                and organization_unit_id not in allowed_org_unit_ids
            ):
                errors.append(
                    "Bạn không có quyền thêm người dùng vào Khoa/Phòng ban này."
                )
            if division_id and division_id not in allowed_division_ids:
                errors.append("Bạn không có quyền thêm người dùng vào Bộ môn này.")

        if effective_level == "department" and not division_id:
            errors.append("Admin Bộ môn phải chọn Bộ môn.")
        if (
            organization_unit_id
            and org_unit
            and org_unit.unit_type == "faculty"
            and getattr(org_unit, "requires_division", True)
            and not division_id
        ):
            errors.append("Vui lòng chọn Bộ môn (bắt buộc đối với Khoa).")

        if division_id:
            division = Division.query.get(division_id)
            if not division:
                errors.append("Bộ môn không hợp lệ.")
            elif division.organization_unit_id != organization_unit_id:
                errors.append("Bộ môn không thuộc Khoa/Phòng ban đã chọn.")

        if admin_level not in ["none", "department", "faculty"]:
            errors.append("Quyền admin không hợp lệ.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "admin/users/form.html",
                action="add",
                user=type(
                    "TmpUser",
                    (),
                    {
                        "email": email,
                        "full_name": full_name,
                        "employee_id": employee_id,
                        "organization_unit_id": organization_unit_id,
                        "division_id": division_id,
                    },
                )(),
                org_units=org_units,
                divisions=divisions,
                effective_level=effective_level,
                allowed_division_ids=(
                    sorted(allowed_division_ids)
                    if effective_level == "department"
                    else []
                ),
            )

        # Lấy tên đơn vị (organization unit) để lưu vào trường legacy `department`
        department_name = None
        if organization_unit_id:
            org_unit = OrganizationUnit.query.get(organization_unit_id)
            if org_unit:
                department_name = org_unit.name

        # Tao user moi
        user = User(
            email=email,
            full_name=full_name,
            department=department_name,
            organization_unit_id=organization_unit_id,
            division_id=division_id if division_id else None,
            employee_id=employee_id or None,
            is_active=True,
        )
        user.admin_level = admin_level
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash(f"Đã tạo người dùng: {full_name}", "success")
        return redirect(url_for("admin.list_users"))

    return render_template(
        "admin/users/form.html",
        action="add",
        user=None,
        org_units=org_units,
        divisions=divisions,
        effective_level=effective_level,
        allowed_division_ids=(
            sorted(allowed_division_ids) if effective_level == "department" else []
        ),
    )


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    """Sửa thông tin người dùng"""
    effective_level = effective_admin_level(current_user)
    user = User.query.get_or_404(user_id)
    if not is_user_in_scope(user):
        flash("Người dùng này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_users"))
    if not can_manage_user_scoped(current_user, user):
        flash("Bạn không có quyền sửa thông tin người dùng này.", "error")
        return redirect(url_for("admin.list_users"))
    org_units, divisions, _scoped_users, _ = build_scope_filter_data(current_user)
    allowed_org_unit_ids = {ou.id for ou in org_units}
    allowed_division_ids = {div.id for div in divisions}

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        organization_unit_id = request.form.get("organization_unit_id", type=int)
        division_id = request.form.get("division_id", type=int)
        employee_id = request.form.get("employee_id", "").strip()
        new_password = request.form.get("new_password", "").strip()

        if not full_name:
            flash("Họ tên không được để trống.", "error")
            return render_template(
                "admin/users/form.html",
                action="edit",
                user=user,
                org_units=org_units,
                effective_level=effective_level,
            )

        # Kiểm tra mã cán bộ
        eid_err = validate_employee_id(employee_id)
        if eid_err:
            flash(eid_err, "error")
            return render_template(
                "admin/users/form.html",
                action="edit",
                user=user,
                org_units=org_units,
                effective_level=effective_level,
            )
        if employee_id:
            existing = User.query.filter(
                User.employee_id == employee_id, User.id != user.id
            ).first()
            if existing:
                flash("Mã cán bộ đã được sử dụng.", "error")
                return render_template(
                    "admin/users/form.html",
                    action="edit",
                    user=user,
                    org_units=org_units,
                    effective_level=effective_level,
                )

        # Kiểm tra Khoa/Phòng ban (không bắt buộc cho Admin Trường)
        is_university_admin = user.highest_admin_level == "university"
        if not organization_unit_id and not is_university_admin:
            flash("Vui lòng chọn Khoa/Phòng ban.", "error")
            return render_template(
                "admin/users/form.html",
                action="edit",
                user=user,
                org_units=org_units,
                effective_level=effective_level,
            )

        if effective_level != "university":
            if effective_level == "department" and not division_id:
                flash("Admin Bộ môn phải chọn Bộ môn.", "error")
                return render_template(
                    "admin/users/form.html",
                    action="edit",
                    user=user,
                    org_units=org_units,
                    effective_level=effective_level,
                )
            if organization_unit_id and organization_unit_id not in allowed_org_unit_ids:
                flash("Bạn không có quyền gán người dùng vào Khoa/Phòng ban này.", "error")
                return render_template(
                    "admin/users/form.html",
                    action="edit",
                    user=user,
                    org_units=org_units,
                    effective_level=effective_level,
                )
            if division_id and division_id not in allowed_division_ids:
                flash("Bạn không có quyền gán người dùng vào Bộ môn này.", "error")
                return render_template(
                    "admin/users/form.html",
                    action="edit",
                    user=user,
                    org_units=org_units,
                    effective_level=effective_level,
                )

        # Kiểm tra Khoa/Phòng ban nếu có chọn
        org_unit = None
        department_name = None
        if organization_unit_id:
            org_unit = OrganizationUnit.query.get(organization_unit_id)
            if not org_unit:
                flash("Khoa/Phòng ban không hợp lệ.", "error")
                return render_template(
                    "admin/users/form.html",
                    action="edit",
                    user=user,
                    org_units=org_units,
                    effective_level=effective_level,
                )
            department_name = org_unit.name

            if org_unit.unit_type == "office":
                division_id = None
            elif (
                org_unit.unit_type == "faculty"
                and getattr(org_unit, "requires_division", True)
                and not division_id
                and not is_university_admin  # Admin Trường không bắt buộc chọn Bộ môn
            ):
                flash("Vui lòng chọn Bộ môn (bắt buộc đối với Khoa).", "error")
                return render_template(
                    "admin/users/form.html",
                    action="edit",
                    user=user,
                    org_units=org_units,
                    effective_level=effective_level,
                )

            if division_id:
                division = Division.query.get(division_id)
                if (
                    not division
                    or division.organization_unit_id != organization_unit_id
                ):
                    flash("Bộ môn không hợp lệ.", "error")
                    return render_template(
                        "admin/users/form.html",
                        action="edit",
                        user=user,
                        org_units=org_units,
                        effective_level=effective_level,
                    )
        else:
            # Không chọn Khoa/Phòng ban (cho phép với Admin Trường)
            division_id = None

        user.full_name = full_name
        user.department = department_name
        user.organization_unit_id = organization_unit_id
        user.division_id = division_id
        user.employee_id = employee_id or None

        # Doi mat khau neu co
        if new_password:
            pw_err = validate_password(new_password)
            if pw_err:
                flash(pw_err, "error")
                return render_template(
                    "admin/users/form.html",
                    action="edit",
                    user=user,
                    org_units=org_units,
                    effective_level=effective_level,
                )
            user.set_password(new_password)

        db.session.commit()
        flash(f"Đã cập nhật thông tin: {full_name}", "success")
        return redirect(url_for("admin.list_users"))

    return render_template(
        "admin/users/form.html",
        action="edit",
        user=user,
        org_units=org_units,
        effective_level=effective_level,
    )


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@university_admin_required  # Chỉ Admin Trường mới xóa user
def delete_user(user_id):
    """Xóa người dùng - Chỉ Admin Trường"""
    user = User.query.get_or_404(user_id)
    if not is_user_in_scope(user):
        flash("Người dùng này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_users"))

    if user.id == current_user.id:
        flash("Không thể xóa tài khoản của chính mình.", "error")
        return redirect(url_for("admin.list_users"))

    # Không cho xóa user có quyền admin - phải thu hồi quyền trước
    if user.is_admin:
        flash(
            f"Không thể xóa {user.full_name} vì người này có quyền admin. "
            "Vui lòng thu hồi quyền admin trước tại mục Quản lý Admin.",
            "error",
        )
        return redirect(url_for("admin.list_users"))

    # Xóa tất cả dữ liệu liên quan
    Publication.query.filter_by(user_id=user.id).delete()
    Project.query.filter_by(user_id=user.id).delete()
    OtherActivity.query.filter_by(user_id=user.id).delete()
    AdminPermissionLog.query.filter_by(user_id=user.id).delete()
    AdminRole.query.filter_by(user_id=user.id).delete()  # Xóa admin roles nếu còn

    name = user.full_name
    db.session.delete(user)
    db.session.commit()

    flash(f"Đã xóa người dùng {name} và tất cả dữ liệu liên quan.", "success")
    return redirect(url_for("admin.list_users"))


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@admin_required
def reset_user_password(user_id):
    """Đổi mật khẩu cho người dùng"""
    user = User.query.get_or_404(user_id)

    # Kiểm tra quyền - chỉ Admin Trường hoặc Admin cùng/cao hơn cấp mới được reset
    if not can_manage_user_scoped(current_user, user):
        flash("Bạn không có quyền đổi mật khẩu cho người dùng này.", "error")
        return redirect(url_for("admin.list_users"))

    new_password = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()

    # Validation
    if not new_password:
        flash("Vui lòng nhập mật khẩu mới.", "error")
        return redirect(url_for("admin.edit_user", user_id=user_id))

    pw_err = validate_password(new_password)
    if pw_err:
        flash(pw_err, "error")
        return redirect(url_for("admin.edit_user", user_id=user_id))

    if new_password != confirm_password:
        flash("Mật khẩu xác nhận không khớp.", "error")
        return redirect(url_for("admin.edit_user", user_id=user_id))

    # Reset password
    user.set_password(new_password)
    db.session.commit()

    flash(f"Đã đổi mật khẩu cho {user.full_name}.", "success")
    return redirect(url_for("admin.edit_user", user_id=user_id))
