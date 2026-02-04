"""Admin dashboard + act-as role routes."""

from __future__ import annotations

from urllib.parse import urlparse

from flask_login import login_required

from . import admin_bp
from .helpers import *  # noqa: F403
from app.services.approval import _get_active_admin_roles, ACT_AS_SESSION_KEY, ACT_AS_USER_MODE_KEY


def _safe_next_url(url, fallback):
    """Trả về URL an toàn (chỉ relative path, không cho //evil.com)."""
    if not url:
        return fallback
    parsed = urlparse(str(url))
    if parsed.scheme or parsed.netloc or not str(url).startswith("/"):
        return fallback
    return str(url)


@admin_bp.route("/", methods=["GET"])
@login_required
@admin_required  # noqa: F405
def dashboard():
    """Admin dashboard - Tổng quan theo phạm vi quyền của admin"""
    return _dashboard_impl()  # noqa: F405


@admin_bp.route("/act-as", methods=["POST"])
@login_required
def set_act_as_role():
    """Đổi vai trò đang làm việc (act-as) cho admin nhiều vai trò.

    role_id=0  → chuyển sang chế độ "Người dùng" (ẩn menu admin, hiện menu nghiên cứu)
    role_id>0  → chuyển sang vai trò admin tương ứng
    """
    if not current_user.is_admin:
        flash("Bạn không có quyền thực hiện thao tác này.", "error")  # noqa: F405
        return redirect(url_for("main.dashboard"))  # noqa: F405

    roles = _get_active_admin_roles(current_user)  # noqa: F405
    allowed_role_ids = {r.id for r in roles}

    requested_role_id = request.form.get("role_id", type=int)  # noqa: F405
    mode = (request.form.get("mode") or "").strip() or "auto"  # noqa: F405
    next_url = _safe_next_url(
        request.form.get("next") or request.referrer,
        url_for("main.dashboard"),
    )

    # Chế độ "Người dùng": role_id = 0
    if requested_role_id == 0:
        session.pop(ACT_AS_SESSION_KEY, None)  # noqa: F405
        session[ACT_AS_USER_MODE_KEY] = True  # noqa: F405
        return redirect(url_for("main.dashboard"))  # noqa: F405

    # Chuyển về admin mode → xóa user mode flag
    session.pop(ACT_AS_USER_MODE_KEY, None)  # noqa: F405

    if mode == "auto" or not requested_role_id:
        session.pop(ACT_AS_SESSION_KEY, None)  # noqa: F405
        return redirect(next_url)  # noqa: F405

    if requested_role_id not in allowed_role_ids:
        session.pop(ACT_AS_SESSION_KEY, None)  # noqa: F405
        return redirect(next_url)  # noqa: F405

    session[ACT_AS_SESSION_KEY] = requested_role_id  # noqa: F405
    return redirect(next_url)  # noqa: F405


def _dashboard_impl():
    """Original dashboard implementation extracted from legacy routes module."""
    """Admin dashboard - Tổng quan theo phạm vi quyền của admin"""
    current_year = datetime.now().year
    effective_level = effective_admin_level(current_user)
    act_as_role = get_act_as_role(current_user)
    admin_level_display = {
        "university": "Admin Trường",
        "faculty": "Admin Khoa",
        "department": "Admin Bộ môn",
    }.get(effective_level, "Người dùng")

    # Xác định trạng thái cần xử lý theo cấp admin
    my_pending_status = get_approval_status_for_level(effective_level)

    # =========================================================================
    # THỐNG KÊ USERS (theo phạm vi)
    # =========================================================================
    user_query = filter_users_by_scope(User.query, current_user)
    total_users = user_query.count()
    active_users = user_query.filter(User.is_active == True).count()

    # Đếm admin theo cấp
    from sqlalchemy import func

    admin_stats = {
        "university": db.session.query(func.count(func.distinct(AdminRole.user_id)))
        .join(User, AdminRole.user_id == User.id)
        .filter(
            AdminRole.role_level == "university",
            AdminRole.is_active == True,
            User.is_active == True,
        )
        .scalar(),
        "faculty": db.session.query(func.count(func.distinct(AdminRole.user_id)))
        .join(User, AdminRole.user_id == User.id)
        .filter(
            AdminRole.role_level == "faculty",
            AdminRole.is_active == True,
            User.is_active == True,
        )
        .scalar(),
        "department": db.session.query(func.count(func.distinct(AdminRole.user_id)))
        .join(User, AdminRole.user_id == User.id)
        .filter(
            AdminRole.role_level == "department",
            AdminRole.is_active == True,
            User.is_active == True,
        )
        .scalar(),
    }

    # =========================================================================
    # THỐNG KÊ PUBLICATIONS (theo phạm vi và năm hiện tại)
    # =========================================================================
    pub_base_query = Publication.query.filter_by(year=current_year)
    pub_query = filter_items_by_scope(pub_base_query, Publication, current_user)

    total_publications = pub_query.count()
    approved_publications = filter_items_by_scope(
        Publication.query.filter_by(year=current_year, is_approved=True),
        Publication,
        current_user,
    ).count()
    returned_publications = filter_items_by_scope(
        Publication.query.filter_by(year=current_year, approval_status="returned"),
        Publication,
        current_user,
    ).count()

    # Số lượng cần TÔI xử lý (theo cấp admin)
    my_pending_pubs = filter_my_pending_items(
        Publication.query.filter_by(year=current_year),
        Publication,
        current_user,
    ).count()

    # =========================================================================
    # THỐNG KÊ PROJECTS (theo phạm vi)
    # =========================================================================
    proj_base_query = Project.query.filter(
        Project.start_year <= current_year, Project.end_year >= current_year
    )
    proj_query = filter_items_by_scope(proj_base_query, Project, current_user)

    total_projects = proj_query.count()
    approved_projects = filter_items_by_scope(
        Project.query.filter(
            Project.start_year <= current_year,
            Project.end_year >= current_year,
            Project.is_approved == True,
        ),
        Project,
        current_user,
    ).count()
    returned_projects = filter_items_by_scope(
        Project.query.filter(
            Project.start_year <= current_year,
            Project.end_year >= current_year,
            Project.approval_status == "returned",
        ),
        Project,
        current_user,
    ).count()

    my_pending_projects = filter_my_pending_items(
        Project.query.filter(
            Project.start_year <= current_year,
            Project.end_year >= current_year,
        ),
        Project,
        current_user,
    ).count()

    # =========================================================================
    # THỐNG KÊ ACTIVITIES (theo phạm vi)
    # =========================================================================
    act_base_query = OtherActivity.query.filter_by(year=current_year)
    act_query = filter_items_by_scope(act_base_query, OtherActivity, current_user)

    total_activities = act_query.count()
    approved_activities = filter_items_by_scope(
        OtherActivity.query.filter_by(year=current_year, is_approved=True),
        OtherActivity,
        current_user,
    ).count()
    returned_activities = filter_items_by_scope(
        OtherActivity.query.filter_by(year=current_year, approval_status="returned"),
        OtherActivity,
        current_user,
    ).count()

    my_pending_activities = filter_my_pending_items(
        OtherActivity.query.filter_by(year=current_year),
        OtherActivity,
        current_user,
    ).count()

    # =========================================================================
    # DANH SÁCH CẦN TÔI XỬ LÝ (recent)
    # =========================================================================
    recent_pending_pubs = (
        filter_my_pending_items(Publication.query, Publication, current_user)
        .order_by(Publication.created_at.desc())
        .limit(5)
        .all()
    )

    recent_pending_projects = (
        filter_my_pending_items(Project.query, Project, current_user)
        .order_by(Project.created_at.desc())
        .limit(5)
        .all()
    )

    recent_pending_activities = (
        filter_my_pending_items(OtherActivity.query, OtherActivity, current_user)
        .order_by(OtherActivity.created_at.desc())
        .limit(5)
        .all()
    )

    # Tổng số cần xử lý
    total_my_pending = my_pending_pubs + my_pending_projects + my_pending_activities

    if act_as_role:
        if act_as_role.role_level == "faculty":
            scope_name = act_as_role.org_unit.name if act_as_role.org_unit else ""
            scope_label = "Khoa"
        elif act_as_role.role_level == "department":
            scope_name = act_as_role.division.name if act_as_role.division else ""
            scope_label = "Bộ môn"
        else:
            scope_name = "Toàn trường"
            scope_label = "Phạm vi"
    else:
        if effective_level == "faculty":
            scope_name = current_user.organization_unit_name
            scope_label = "Khoa"
        elif effective_level == "department":
            scope_name = current_user.division_name
            scope_label = "Bộ môn"
        else:
            scope_name = "Toàn trường"
            scope_label = "Phạm vi"

    return render_template(
        "admin/dashboard.html",
        # User stats
        total_users=total_users,
        active_users=active_users,
        admin_stats=admin_stats,
        # Publication stats
        total_publications=total_publications,
        pending_publications=my_pending_pubs,  # Số cần TÔI xử lý
        approved_publications=approved_publications,
        returned_publications=returned_publications,
        # Project stats
        total_projects=total_projects,
        pending_projects=my_pending_projects,
        approved_projects=approved_projects,
        returned_projects=returned_projects,
        # Activity stats
        total_activities=total_activities,
        pending_activities=my_pending_activities,
        approved_activities=approved_activities,
        returned_activities=returned_activities,
        # Recent items cần xử lý
        recent_pending_pubs=recent_pending_pubs,
        recent_pending_projects=recent_pending_projects,
        recent_pending_activities=recent_pending_activities,
        # Context
        current_year=current_year,
        my_pending_status=my_pending_status,
        total_my_pending=total_my_pending,
        admin_level=effective_level,
        admin_level_display=admin_level_display,
        scope_label=scope_label,
        scope_name=scope_name,
    )
