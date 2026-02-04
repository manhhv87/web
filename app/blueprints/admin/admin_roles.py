"""Admin role management routes."""

from __future__ import annotations

from flask_login import login_required

from . import admin_bp
from .helpers import *  # noqa: F403

# =============================================================================
# QUẢN LÝ ADMIN - Admin Management (riêng biệt với User Management)
# =============================================================================


@admin_bp.route("/admins")
@login_required
@admin_required
def list_admins():
    """Danh sách admin - chỉ hiển thị admin cấp dưới hoặc bằng"""
    # Lấy danh sách admin theo quyền xem
    effective_level = effective_admin_level(current_user)
    effective_rank = ADMIN_LEVEL_HIERARCHY.get(effective_level, 0)
    base_query = filter_users_by_scope(User.query, current_user)

    active_admin_users_sq = select(AdminRole.user_id).where(AdminRole.is_active == True)
    admins_query = base_query.filter(User.id.in_(active_admin_users_sq))

    admins = admins_query.order_by(User.admin_level.desc(), User.full_name).all()

    # Lấy thông tin roles chi tiết cho mỗi admin
    admin_data = []
    for admin in admins:
        roles = AdminRole.query.filter_by(user_id=admin.id, is_active=True).all()
        admin_rank = ADMIN_LEVEL_HIERARCHY.get(admin.highest_admin_level, 0)
        admin_data.append(
            {
                "user": admin,
                "roles": roles,
                "can_manage": effective_rank > admin_rank or admin.id == current_user.id,
            }
        )

    return render_template(
        "admin/admins/list.html",
        admin_data=admin_data,
        current_level=effective_level,
    )


@admin_bp.route("/admins/add", methods=["GET", "POST"])
@login_required
@faculty_admin_required  # Chỉ Admin Khoa trở lên mới gán quyền admin
def add_admin():
    """Thêm quyền admin cho user"""
    if request.method == "POST":
        user_id = request.form.get("user_id", type=int)
        role_level = request.form.get("role_level", "").strip()
        organization_unit_id = request.form.get("organization_unit_id", type=int)
        division_id = request.form.get("division_id", type=int)
        notes = request.form.get("notes", "").strip()

        # Validation
        if not user_id:
            flash("Vui lòng chọn người dùng.", "error")
            return redirect(url_for("admin.add_admin"))

        if not role_level or role_level not in ["department", "faculty", "university"]:
            flash("Vui lòng chọn cấp admin hợp lệ.", "error")
            return redirect(url_for("admin.add_admin"))

        user = User.query.get(user_id)
        if not user:
            flash("Người dùng không tồn tại.", "error")
            return redirect(url_for("admin.add_admin"))

        scoped_user = (
            filter_users_by_scope(User.query, current_user)
            .filter(User.id == user_id)
            .first()
        )
        if not scoped_user:
            flash(
                "Người dùng này nằm ngoài phạm vi bạn đang quản lý.",
                "error",
            )
            return redirect(url_for("admin.add_admin"))

        # Kiểm tra quyền gán
        if not can_assign_admin_level_scoped(current_user, role_level):
            flash("Bạn không có quyền gán cấp admin này.", "error")
            return redirect(url_for("admin.add_admin"))

        # Validate scope
        if role_level == "faculty" and not organization_unit_id:
            flash("Vui lòng chọn Khoa cho Admin Khoa.", "error")
            return redirect(url_for("admin.add_admin"))

        if role_level == "department" and not division_id:
            flash("Vui lòng chọn Bộ môn cho Admin Bộ môn.", "error")
            return redirect(url_for("admin.add_admin"))

        # Validate user thuộc đơn vị được gán quyền

        if role_level == "department":
            div = Division.query.get(division_id)
            if not div:
                flash("Bộ môn không hợp lệ.", "error")
                return redirect(url_for("admin.add_admin"))

            if effective_admin_level(current_user) != "university":
                division_scope_ids = get_role_scope_ids(current_user, "department")
                faculty_scope_ids = get_role_scope_ids(current_user, "faculty")
                if division_scope_ids and division_id not in division_scope_ids:
                    flash(
                        "Bạn không có quyền gán Admin Bộ môn cho bộ môn này.", "error"
                    )
                    return redirect(url_for("admin.add_admin"))
                if (
                    faculty_scope_ids
                    and div.organization_unit_id not in faculty_scope_ids
                ):
                    flash("Bộ môn này không thuộc Khoa bạn quản lý.", "error")
                    return redirect(url_for("admin.add_admin"))

            # Admin BM phải thuộc đúng Bộ môn
            if user.division_id != division_id:
                flash(
                    f"Không thể gán quyền: {user.full_name} không thuộc bộ môn {div.name}. "
                    "Hãy cập nhật bộ môn của người dùng trước.",
                    "error",
                )
                return redirect(url_for("admin.add_admin"))

        if role_level == "faculty":
            org = OrganizationUnit.query.get(organization_unit_id)
            if not org:
                flash("Khoa không hợp lệ.", "error")
                return redirect(url_for("admin.add_admin"))

            if effective_admin_level(current_user) != "university":
                faculty_scope_ids = get_role_scope_ids(current_user, "faculty")
                if faculty_scope_ids and organization_unit_id not in faculty_scope_ids:
                    flash("Bạn không có quyền gán Admin Khoa cho khoa này.", "error")
                    return redirect(url_for("admin.add_admin"))

            # Admin Khoa phải thuộc Khoa đó.
            if user.organization_unit_id != organization_unit_id:
                user_div = (
                    Division.query.get(user.division_id) if user.division_id else None
                )
                if not (
                    user_div and user_div.organization_unit_id == organization_unit_id
                ):
                    flash(
                        f"Không thể gán quyền: {user.full_name} không thuộc {org.name}. "
                        "Hãy cập nhật đơn vị của người dùng trước.",
                        "error",
                    )
                    return redirect(url_for("admin.add_admin"))

        # Tạo role
        old_level = user.highest_admin_level
        role = AdminRole.grant_role(
            user_id=user_id,
            role_level=role_level,
            organization_unit_id=(
                organization_unit_id
                if role_level in ["faculty", "department"]
                else None
            ),
            division_id=division_id if role_level == "department" else None,
            assigned_by=current_user.id,
            notes=notes,
        )

        if role is None:
            flash("Người dùng đã có vai trò này.", "warning")
            return redirect(url_for("admin.list_admins"))

        # Cập nhật admin_level theo vai trò hiện tại (cache)
        new_highest = AdminRole.get_highest_level(user_id)
        user.admin_level = new_highest if new_highest != "none" else "none"

        # Ghi log
        AdminPermissionLog.log_change(
            user_id=user_id,
            old_level=old_level,
            new_level=new_highest,
            performed_by=current_user.id,
            notes=notes,
        )

        db.session.commit()
        flash(
            f"Đã cấp quyền {role.role_level_display} cho {user.full_name}.", "success"
        )
        return redirect(url_for("admin.list_admins"))

    # GET - Hiển thị form
    # Lấy danh sách users có thể gán quyền (trong phạm vi quản lý)
    users_query = filter_users_by_scope(User.query, current_user)
    users = users_query.filter(User.is_active == True).order_by(User.full_name).all()

    user_ids = [u.id for u in users]
    roles_by_user: dict[int, list[str]] = {uid: [] for uid in user_ids}
    if user_ids:
        active_roles = AdminRole.query.filter(
            AdminRole.user_id.in_(user_ids),
            AdminRole.is_active == True,
        ).all()
        for role in active_roles:
            roles_by_user.setdefault(role.user_id, []).append(role.role_level)
    # Legacy admin_level is no longer used for permissions

    # Lấy danh sách Khoa/Bộ môn theo phạm vi quyền (không phụ thuộc vào việc đã có user)
    org_units, divisions, _scoped_users, _ = build_scope_filter_data(current_user)

    # Các cấp admin có thể gán
    assignable_levels = []
    effective_level = effective_admin_level(current_user)
    if effective_level == "university":
        assignable_levels = [
            ("university", "Admin Trường"),
            ("faculty", "Admin Khoa"),
            ("department", "Admin Bộ môn"),
        ]
    elif effective_level == "faculty":
        assignable_levels = [
            ("faculty", "Admin Khoa"),
            ("department", "Admin Bộ môn"),
        ]

    return render_template(
        "admin/admins/add.html",
        users=users,
        org_units=org_units,
        divisions=divisions,
        assignable_levels=assignable_levels,
        roles_by_user=roles_by_user,
    )


@admin_bp.route("/admins/<int:user_id>/roles")
@login_required
@admin_required
def view_admin_roles(user_id):
    """Xem chi tiết các vai trò admin của một user"""
    user = User.query.get_or_404(user_id)
    effective_level = effective_admin_level(current_user)

    # Kiểm tra quyền xem
    if not can_view_user_scoped(current_user, user):
        flash("Bạn không có quyền xem thông tin admin này.", "error")
        return redirect(url_for("admin.list_admins"))
    if not is_user_in_scope(user):
        flash("Admin này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_admins"))

    roles = (
        AdminRole.query.filter_by(user_id=user_id)
        .order_by(AdminRole.role_level.desc())
        .all()
    )
    role_lock_reasons = {}
    for role in roles:
        if not role.is_active:
            continue
        remaining = count_effective_admins_by_scope(
            role_level=role.role_level,
            organization_unit_id=role.organization_unit_id,
            division_id=role.division_id,
            exclude_role_id=role.id,
            exclude_user_id=role.user_id,
        )
        if remaining <= 0:
            if role.role_level == "university":
                reason = "Không thể thay đổi Admin Trường cuối cùng."
            elif role.role_level == "faculty":
                scope = role.org_unit.name if role.org_unit else "Khoa này"
                reason = f"Không thể thay đổi Admin Khoa cuối cùng của {scope}."
            else:
                scope = role.division.name if role.division else "Bộ môn này"
                reason = f"Không thể thay đổi Admin Bộ môn cuối cùng của {scope}."
            role_lock_reasons[role.id] = reason
    logs = (
        AdminPermissionLog.query.filter_by(user_id=user_id)
        .order_by(AdminPermissionLog.performed_at.desc())
        .limit(20)
        .all()
    )

    assignable_levels = []
    if effective_level == "university":
        assignable_levels = ["university", "faculty", "department"]
    elif effective_level == "faculty":
        assignable_levels = ["faculty", "department"]

    return render_template(
        "admin/admins/roles.html",
        user=user,
        roles=roles,
        logs=logs,
        can_manage=(
            ADMIN_LEVEL_HIERARCHY.get(effective_level, 0)
            > ADMIN_LEVEL_HIERARCHY.get(user.highest_admin_level, 0)
            or current_user.id == user.id
        ),
        role_lock_reasons=role_lock_reasons,
        assignable_levels=assignable_levels,
    )


@admin_bp.route("/admins/roles/<int:role_id>/toggle", methods=["POST"])
@login_required
@faculty_admin_required
def toggle_admin_role(role_id):
    """Bật/tắt vai trò admin"""
    role = AdminRole.query.get_or_404(role_id)
    user = User.query.get(role.user_id)
    if not user or not is_user_in_scope(user):
        flash("Admin này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_admins"))

    # Kiểm tra quyền
    if not can_assign_admin_level_scoped(current_user, role.role_level):
        flash("Bạn không có quyền thay đổi vai trò này.", "error")
        return redirect(url_for("admin.list_admins"))

    if role.is_active:
        remaining = count_effective_admins_by_scope(
            role_level=role.role_level,
            organization_unit_id=role.organization_unit_id,
            division_id=role.division_id,
            exclude_role_id=role.id,
            exclude_user_id=role.user_id,
        )
        if remaining <= 0:
            if role.role_level == "university":
                message = "Không thể thu hồi vai trò Admin Trường cuối cùng."
            elif role.role_level == "faculty":
                scope = role.org_unit.name if role.org_unit else "Khoa này"
                message = f"Không thể thu hồi vai trò Admin Khoa cuối cùng của {scope}."
            else:
                scope = role.division.name if role.division else "Bộ môn này"
                message = (
                    f"Không thể thu hồi vai trò Admin Bộ môn cuối cùng của {scope}."
                )
            flash(message, "error")
            return redirect(url_for("admin.view_admin_roles", user_id=user.id))

    old_level = user.highest_admin_level
    role.is_active = not role.is_active

    # Cập nhật admin_level của user
    new_highest = AdminRole.get_highest_level(user.id)
    user.admin_level = new_highest if new_highest != "none" else "none"

    # Ghi log
    action = "grant" if role.is_active else "revoke"
    AdminPermissionLog.log_change(
        user_id=user.id,
        old_level=old_level,
        new_level=new_highest,
        performed_by=current_user.id,
        notes=f"{'Kích hoạt' if role.is_active else 'Vô hiệu hóa'} vai trò {role.role_level_display}",
    )

    db.session.commit()

    status = "kích hoạt" if role.is_active else "vô hiệu hóa"
    flash(
        f"Đã {status} vai trò {role.role_level_display} của {user.full_name}.",
        "success",
    )
    return redirect(url_for("admin.view_admin_roles", user_id=user.id))


@admin_bp.route("/admins/roles/<int:role_id>/delete", methods=["POST"])
@login_required
@faculty_admin_required
def delete_admin_role(role_id):
    """Xóa vai trò admin"""
    role = AdminRole.query.get_or_404(role_id)
    user = User.query.get(role.user_id)
    if not user or not is_user_in_scope(user):
        flash("Admin này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_admins"))

    # Kiểm tra quyền
    if not can_assign_admin_level_scoped(current_user, role.role_level):
        flash("Bạn không có quyền xóa vai trò này.", "error")
        return redirect(url_for("admin.list_admins"))

    remaining = count_effective_admins_by_scope(
        role_level=role.role_level,
        organization_unit_id=role.organization_unit_id,
        division_id=role.division_id,
        exclude_role_id=role.id,
        exclude_user_id=role.user_id,
    )
    if remaining <= 0:
        if role.role_level == "university":
            message = "Không thể xóa vai trò Admin Trường cuối cùng."
        elif role.role_level == "faculty":
            scope = role.org_unit.name if role.org_unit else "Khoa này"
            message = f"Không thể xóa vai trò Admin Khoa cuối cùng của {scope}."
        else:
            scope = role.division.name if role.division else "Bộ môn này"
            message = f"Không thể xóa vai trò Admin Bộ môn cuối cùng của {scope}."
        flash(message, "error")
        return redirect(url_for("admin.view_admin_roles", user_id=user.id))

    old_level = user.highest_admin_level
    role_display = role.role_level_display

    db.session.delete(role)

    # Cập nhật admin_level của user
    new_highest = AdminRole.get_highest_level(user.id)
    user.admin_level = new_highest if new_highest != "none" else "none"

    # Ghi log
    AdminPermissionLog.log_change(
        user_id=user.id,
        old_level=old_level,
        new_level=new_highest,
        performed_by=current_user.id,
        notes=f"Xóa vai trò {role_display}",
    )

    db.session.commit()
    flash(f"Đã xóa vai trò {role_display} của {user.full_name}.", "success")
    return redirect(url_for("admin.view_admin_roles", user_id=user.id))
