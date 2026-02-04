"""Shared helpers and permission/scope logic for the Admin blueprint.

This module intentionally contains **no routes** to avoid circular imports.
Route modules (dashboard/users/approval/org/reports/admin_roles) import from here.
"""

from __future__ import annotations

from datetime import datetime
from functools import wraps

from sqlalchemy import or_, select
from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    request,
    session,
)
from flask_login import login_required, current_user, logout_user

from app.db_models import (
    db,
    User,
    Publication,
    Project,
    OtherActivity,
    OrganizationUnit,
    Division,
    AdminPermissionLog,
    ApprovalLog,
    AdminRole,
    validate_email,
    validate_password,
    validate_employee_id,
)
from app.hours_calculator import (
    calculate_publication_hours,
    calculate_project_hours_from_model,
    calculate_other_activity_hours_from_model,
    calculate_total_research_hours,
    PUBLICATION_TYPE_CHOICES,
    QUARTILE_CHOICES,
    AUTHOR_ROLE_CHOICES,
    PATENT_STAGE_CHOICES,
    PROJECT_LEVEL_CHOICES,
    PROJECT_ROLE_CHOICES,
    PROJECT_STATUS_CHOICES,
    OTHER_ACTIVITY_TYPE_CHOICES,
)
from app.services.approval import (
    ADMIN_LEVEL_HIERARCHY,
    ACT_AS_SESSION_KEY,
    ACT_AS_USER_MODE_KEY,
    _get_active_admin_roles,
    get_act_as_role,
    get_effective_context,
    has_university_access,
    effective_admin_level,
    get_role_scope_ids,
    count_effective_admins_by_scope,
    get_scope_permissions,
    is_office_user,
    has_department_admin_for_owner,
    has_faculty_admin_for_owner,
    filter_items_by_scope,
    exclude_lower_level_pending,
    check_approval_chain,
    resolve_next_approval_status,
    can_return_item,
    get_approval_action_level,
    # pure workflow wrappers (kept for compatibility)
    approval_can_approve,
    approval_next_status,
    approval_action_level,
    approval_can_return,
)

# =============================================================================
# DECORATORS VÀ HELPER FUNCTIONS - PHÂN QUYỀN 3 CẤP
# =============================================================================


def inject_act_as_context():
    """Inject dữ liệu act-as vào template.

    Admin luôn thấy dropdown chuyển vai trò (bao gồm "Người dùng").
    Khi chọn "Người dùng", navigation hiển thị menu nghiên cứu cá nhân.
    Khi chọn một vai trò admin, navigation hiển thị menu quản lý.
    """
    if not current_user.is_authenticated or not current_user.is_admin:
        return {"act_as_user_mode": False}

    is_user_mode = session.get(ACT_AS_USER_MODE_KEY, False)

    roles = _get_active_admin_roles(current_user)
    act_as_role = get_act_as_role(current_user)
    effective_level = effective_admin_level(current_user)

    auto_label = f"Tự động ({current_user.admin_level_display})"

    if is_user_mode:
        selected_role_id = 0
        current_label = "Người dùng"
    else:
        selected_role_id = (
            act_as_role.id if act_as_role else (roles[0].id if roles else None)
        )
        if act_as_role:
            current_label = act_as_role.full_display
        elif selected_role_id:
            selected_role = next((r for r in roles if r.id == selected_role_id), None)
            current_label = selected_role.full_display if selected_role else auto_label
        else:
            current_label = auto_label

    return {
        "act_as_show_dropdown": len(roles) >= 1,
        "act_as_options": roles,
        "act_as_selected_role_id": selected_role_id,
        "act_as_auto_label": auto_label,
        "act_as_current_label": current_label,
        "act_as_effective_level": effective_level,
        "act_as_user_mode": is_user_mode,
    }


def admin_required(f):
    """Decorator kiểm tra có phải admin không (bất kỳ cấp nào)"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_active:
            logout_user()
            flash("Tài khoản của bạn đã bị khóa.", "error")
            return redirect(url_for("auth.login"))
        if session.get(ACT_AS_USER_MODE_KEY, False):
            flash("Bạn đang ở chế độ Người dùng. Hãy chuyển lại vai trò Admin để truy cập.", "error")
            return redirect(url_for("main.dashboard"))
        if not current_user.is_admin:
            flash("Bạn không có quyền truy cập trang này.", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)

    return decorated_function


def admin_level_required(min_level: str):
    """
    Decorator kiểm tra cấp admin tối thiểu.

    Args:
        min_level: 'department', 'faculty', hoặc 'university'
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if not current_user.is_active:
                logout_user()
                flash("Tài khoản của bạn đã bị khóa.", "error")
                return redirect(url_for("auth.login"))

            if session.get(ACT_AS_USER_MODE_KEY, False):
                flash("Bạn đang ở chế độ Người dùng. Hãy chuyển lại vai trò Admin để truy cập.", "error")
                return redirect(url_for("main.dashboard"))

            user_level = ADMIN_LEVEL_HIERARCHY.get(
                effective_admin_level(current_user), 0
            )
            required_level = ADMIN_LEVEL_HIERARCHY.get(min_level, 0)

            if user_level < required_level:
                flash(f"Bạn cần quyền Admin {min_level} trở lên để thực hiện.", "error")
                return redirect(url_for("main.dashboard"))

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def _effective_admin_rank(admin_user) -> int:
    """Hierarchy rank based on act-as effective level."""
    return ADMIN_LEVEL_HIERARCHY.get(effective_admin_level(admin_user), 0)


def can_view_user_scoped(admin_user, target_user: User) -> bool:
    """Act-as aware view permission for users."""
    if not admin_user or not admin_user.is_admin:
        return False
    if session.get(ACT_AS_USER_MODE_KEY, False):
        return False
    if not target_user:
        return False
    if not is_user_in_scope(target_user):
        return False

    effective_rank = _effective_admin_rank(admin_user)
    if effective_rank <= 0:
        return False

    if not target_user.is_admin:
        return True

    target_rank = ADMIN_LEVEL_HIERARCHY.get(target_user.highest_admin_level, 0)
    return target_rank <= effective_rank


def can_manage_user_scoped(admin_user, target_user: User) -> bool:
    """Act-as aware manage permission for users."""
    if not can_view_user_scoped(admin_user, target_user):
        return False

    effective_rank = _effective_admin_rank(admin_user)
    if target_user.is_admin:
        target_rank = ADMIN_LEVEL_HIERARCHY.get(target_user.highest_admin_level, 0)
        if target_rank >= effective_rank:
            return False
    return True


def can_assign_admin_level_scoped(admin_user, target_level: str) -> bool:
    """Act-as aware check for assigning admin levels."""
    level = effective_admin_level(admin_user)
    if level == "university":
        return target_level in ["university", "faculty", "department", "none"]
    if level == "faculty":
        return target_level in ["faculty", "department", "none"]
    return False


def university_admin_required(f):
    """Decorator yêu cầu Admin cấp Trường"""
    return admin_level_required("university")(f)


def faculty_admin_required(f):
    """Decorator yêu cầu Admin cấp Khoa trở lên"""
    return admin_level_required("faculty")(f)


def get_scope_filter_for_user(user):
    """
    Trả về dict filter để lọc dữ liệu theo phạm vi admin.

    Returns:
        dict: Filter cho query (rỗng nếu là university)
        None: Nếu không phải admin
    """
    if not user.is_admin:
        return None

    level = effective_admin_level(user)

    if level == "university":
        return {}  # Không filter - xem tất cả
    elif level == "faculty":
        return {"organization_unit_id": user.organization_unit_id}
    elif level == "department":
        return {"division_id": user.division_id}
    return None


def filter_users_by_scope(query, admin_user):
    """
    Lọc query User theo phạm vi admin.

    Args:
        query: SQLAlchemy query object
        admin_user: User admin hiện tại

    Returns:
        Filtered query
    """
    level = effective_admin_level(admin_user)

    if level == "university":
        return query  # Xem tất cả

    if level == "faculty":
        org_unit_ids = get_role_scope_ids(admin_user, "faculty")
        if org_unit_ids:
            return query.filter(User.organization_unit_id.in_(org_unit_ids))
        if admin_user.organization_unit_id:
            return query.filter(
                User.organization_unit_id == admin_user.organization_unit_id
            )
        return query.filter(User.id == -1)

    if level == "department":
        division_ids = get_role_scope_ids(admin_user, "department")
        if division_ids:
            return query.filter(User.division_id.in_(division_ids))
        if admin_user.division_id:
            return query.filter(User.division_id == admin_user.division_id)
        return query.filter(User.id == -1)

    return query.filter(User.id == -1)  # Empty


def build_scope_filter_data(admin_user, org_unit_id=None, division_id=None):
    """
    Xây dữ liệu filter theo phạm vi hiện tại (có xét act-as).

    Trả về:
    - org_units: các Khoa/Phòng ban trong phạm vi
    - divisions: các Bộ môn trong phạm vi (UI lọc theo org_unit_id ở client)
    - users: danh sách người dùng trong phạm vi (UI lọc theo org_unit/division)
    - filtered_user_ids_sq: subquery user ids để lọc items an toàn (không join trùng)
    """

    # Users filtered by current admin scope (kept for user list + subquery)
    base_users_query = filter_users_by_scope(
        User.query.filter_by(is_active=True), admin_user
    )

    level = effective_admin_level(admin_user)

    # Determine scope ids without requiring existing users
    org_unit_scope_ids = None
    division_scope_ids = []

    if level == "faculty":
        org_unit_scope_ids = get_role_scope_ids(admin_user, "faculty")
        if not org_unit_scope_ids and admin_user.organization_unit_id:
            org_unit_scope_ids = [admin_user.organization_unit_id]
        org_unit_scope_ids = sorted(set(org_unit_scope_ids))
    elif level == "department":
        division_scope_ids = get_role_scope_ids(admin_user, "department")
        if not division_scope_ids and admin_user.division_id:
            division_scope_ids = [admin_user.division_id]
        division_scope_ids = sorted(set(division_scope_ids))

        if division_scope_ids:
            org_unit_scope_ids = sorted(
                {
                    ou_id
                    for (ou_id,) in Division.query.with_entities(
                        Division.organization_unit_id
                    )
                    .filter(Division.id.in_(division_scope_ids))
                    .distinct()
                    .all()
                }
            )
        else:
            org_unit_scope_ids = []
    elif level not in ("university",):
        org_unit_scope_ids = []

    # Org units in scope
    org_units_query = OrganizationUnit.query.filter_by(is_active=True)
    if org_unit_scope_ids is not None:
        if org_unit_scope_ids:
            org_units_query = org_units_query.filter(
                OrganizationUnit.id.in_(org_unit_scope_ids)
            )
        else:
            org_units_query = org_units_query.filter(OrganizationUnit.id == -1)
    org_units = org_units_query.order_by(
        OrganizationUnit.unit_type, OrganizationUnit.name
    ).all()

    # Divisions in scope (do not depend on existing users)
    divisions_query = Division.query.filter_by(is_active=True)

    if division_scope_ids:
        divisions_query = divisions_query.filter(Division.id.in_(division_scope_ids))

    if org_unit_scope_ids is not None:
        if org_unit_scope_ids:
            divisions_query = divisions_query.filter(
                Division.organization_unit_id.in_(org_unit_scope_ids)
            )
        else:
            divisions_query = divisions_query.filter(Division.id == -1)

    divisions = divisions_query.order_by(
        Division.organization_unit_id, Division.name
    ).all()

    # Users subquery uses selected filters; users list stays scope-wide for client-side cascade
    filtered_users_query = base_users_query
    if org_unit_id:
        filtered_users_query = filtered_users_query.filter(
            User.organization_unit_id == org_unit_id
        )
    if division_id:
        filtered_users_query = filtered_users_query.filter(
            User.division_id == division_id
        )

    filtered_user_ids_sq = filtered_users_query.with_entities(User.id).subquery()
    users = base_users_query.order_by(User.full_name).all()

    return org_units, divisions, users, filtered_user_ids_sq


def get_scoped_item_or_none(
    model_class, item_id: int, include_lower_pending: bool = False
):
    # Get item by scope (optionally include lower-level pending).
    scoped_query = filter_items_by_scope(model_class.query, model_class, current_user)
    if not include_lower_pending:
        scoped_query = exclude_lower_level_pending(
            scoped_query, model_class, current_user
        )
    return scoped_query.filter(model_class.id == item_id).first()


def is_user_in_scope(target_user: User) -> bool:
    """Kiểm tra user có nằm trong phạm vi hiện tại (có xét act-as) không."""
    scoped_query = filter_users_by_scope(User.query, current_user)
    return scoped_query.filter(User.id == target_user.id).first() is not None


def get_approval_status_for_level(admin_level: str) -> str:
    """
    Trả về approval_status mà admin cấp này cần xử lý (cho Khoa).

    Args:
        admin_level: 'department', 'faculty', 'university'

    Returns:
        str: 'pending', 'department_approved', 'faculty_approved'
    """
    status_map = {
        "department": "pending",  # BM xử lý items pending
        "faculty": "department_approved",  # Khoa xử lý items đã BM duyệt
        "university": "faculty_approved",  # Trường xử lý items đã Khoa duyệt
    }
    return status_map.get(admin_level, "pending")


def filter_my_pending_items(query, model_class, admin_user):
    # Filter items awaiting approval for this admin.
    from sqlalchemy import or_, and_

    level = effective_admin_level(admin_user)

    if level == "department":
        division_ids = get_role_scope_ids(admin_user, "department")
        if not division_ids and admin_user.division_id:
            division_ids = [admin_user.division_id]
        if not division_ids:
            return query.filter(model_class.id == -1)

        return (
            query.join(User, model_class.user_id == User.id)
            .join(OrganizationUnit, User.organization_unit_id == OrganizationUnit.id)
            .filter(
                model_class.approval_status == "pending",
                User.division_id.in_(division_ids),
                OrganizationUnit.unit_type != "office",
            )
        )

    if level == "faculty":
        org_unit_ids = get_role_scope_ids(admin_user, "faculty")
        if not org_unit_ids and admin_user.organization_unit_id:
            org_unit_ids = [admin_user.organization_unit_id]
        if not org_unit_ids:
            return query.filter(model_class.id == -1)

        missing_division_ids = []
        divisions = Division.query.filter(
            Division.organization_unit_id.in_(org_unit_ids)
        ).all()
        for division in divisions:
            if (
                count_effective_admins_by_scope("department", division_id=division.id)
                == 0
            ):
                missing_division_ids.append(division.id)

        return (
            query.join(User, model_class.user_id == User.id)
            .join(OrganizationUnit, User.organization_unit_id == OrganizationUnit.id)
            .filter(
                User.organization_unit_id.in_(org_unit_ids),
                OrganizationUnit.unit_type != "office",
                or_(
                    model_class.approval_status == "department_approved",
                    and_(
                        model_class.approval_status == "pending",
                        or_(
                            User.division_id.is_(None),
                            User.division_id.in_(missing_division_ids),
                        ),
                    ),
                ),
            )
        )

    if level == "university":
        missing_org_unit_ids = []
        org_units = OrganizationUnit.query.filter(
            OrganizationUnit.unit_type != "office"
        ).all()
        for org_unit in org_units:
            if (
                count_effective_admins_by_scope(
                    "faculty", organization_unit_id=org_unit.id
                )
                == 0
            ):
                missing_org_unit_ids.append(org_unit.id)

        missing_division_ids = []
        if missing_org_unit_ids:
            divisions = Division.query.filter(
                Division.organization_unit_id.in_(missing_org_unit_ids)
            ).all()
            for division in divisions:
                if (
                    count_effective_admins_by_scope(
                        "department", division_id=division.id
                    )
                    == 0
                ):
                    missing_division_ids.append(division.id)

        return (
            query.join(User, model_class.user_id == User.id)
            .join(OrganizationUnit, User.organization_unit_id == OrganizationUnit.id)
            .filter(
                or_(
                    and_(
                        model_class.approval_status == "faculty_approved",
                        OrganizationUnit.unit_type != "office",
                    ),
                    and_(
                        model_class.approval_status == "pending",
                        OrganizationUnit.unit_type == "office",
                    ),
                    and_(
                        model_class.approval_status == "department_approved",
                        User.organization_unit_id.in_(missing_org_unit_ids),
                    ),
                    and_(
                        model_class.approval_status == "pending",
                        User.organization_unit_id.in_(missing_org_unit_ids),
                        or_(
                            User.division_id.is_(None),
                            User.division_id.in_(missing_division_ids),
                        ),
                    ),
                )
            )
        )

    return query.filter(model_class.id == -1)


ALLOWED_STATUS_FILTERS = {"all", "pending", "approved", "returned"}

# Trạng thái được coi là "đã duyệt" theo cấp admin:
# - Admin Bộ môn: department_approved, faculty_approved, approved
# - Admin Khoa: faculty_approved, approved
# - Admin Trường: approved
APPROVED_STATUSES_BY_LEVEL = {
    "department": ["department_approved", "faculty_approved", "approved"],
    "faculty": ["faculty_approved", "approved"],
    "university": ["approved"],
}


def get_approved_statuses(admin_user) -> list[str]:
    """Trả về danh sách trạng thái coi là 'đã duyệt' theo cấp admin hiện tại."""
    level = effective_admin_level(admin_user)
    return APPROVED_STATUSES_BY_LEVEL.get(level, ["approved"])


def normalize_status_filter(raw_status: str) -> str:
    """
    Chuẩn hoá status filter về đúng 4 lựa chọn hiển thị trên UI.

    - `my_pending` được map về `pending`.
    - Bất kỳ giá trị lạ/cũ nào sẽ rơi về `all`.
    """
    if raw_status == "my_pending":
        return "pending"
    if raw_status in ALLOWED_STATUS_FILTERS:
        return raw_status
    return "all"


def get_next_approval_status(current_status: str, item_owner=None) -> str:
    """
    Trả về trạng thái tiếp theo trong quy trình duyệt.

    Quy trình linh hoạt:
    - Khoa (faculty): pending → department_approved → faculty_approved → approved
    - Phòng ban (office): pending → approved (Trường duyệt trực tiếp)

    Args:
        current_status: Trạng thái hiện tại
        item_owner: User sở hữu công trình (để xác định loại đơn vị)

    Returns:
        str: Trạng thái tiếp theo
    """
    # Quy trình cho Phòng ban (1 bước - Trường duyệt trực tiếp)
    if item_owner and is_office_user(item_owner):
        office_next_map = {
            "pending": "approved",  # Trường duyệt trực tiếp
        }
        return office_next_map.get(current_status, current_status)

    # Quy trình chuẩn cho Khoa (3 bước)
    next_status_map = {
        "pending": "department_approved",
        "department_approved": "faculty_approved",
        "faculty_approved": "approved",
    }
    return next_status_map.get(current_status, current_status)
