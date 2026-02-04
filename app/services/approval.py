"""Approval + scope service.

Mục tiêu:
- Gom toàn bộ logic duyệt (quyết định + thao tác DB) cho Publication/Project/OtherActivity.
- Gom logic phạm vi (scope) của admin (university/faculty/department + act-as).
- Tránh phụ thuộc service -> blueprint (services không import app.blueprints.*).

Lưu ý: Thiết kế này ưu tiên *ít code* và *không đổi tính năng/URL* của hệ thống.
"""

from __future__ import annotations


from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from flask import g, has_request_context, session
from app.db_models import (
    db,
    User,
    AdminRole,
    ApprovalLog,
    OrganizationUnit,
    Publication,
    Project,
    OtherActivity,
)


# Thứ tự cấp bậc admin
ADMIN_LEVEL_HIERARCHY = {"none": 0, "department": 1, "faculty": 2, "university": 3}
ACT_AS_SESSION_KEY = "admin_act_as_role_id"
ACT_AS_USER_MODE_KEY = "admin_act_as_user_mode"


def _get_active_admin_roles(user: User) -> list[AdminRole]:
    """Lấy danh sách admin roles đang hoạt động (có cache theo request)."""
    if not getattr(user, "id", None):
        return []

    if has_request_context() and hasattr(g, "_active_admin_roles"):
        return g._active_admin_roles

    roles = AdminRole.query.filter_by(user_id=user.id, is_active=True).all()
    roles.sort(
        key=lambda r: (
            -ADMIN_LEVEL_HIERARCHY.get(getattr(r, "role_level", "none"), 0),
            (r.org_unit.name if getattr(r, "org_unit", None) else ""),
            (r.division.name if getattr(r, "division", None) else ""),
            r.id,
        )
    )

    if has_request_context():
        g._active_admin_roles = roles
    return roles


def get_act_as_role(user: User) -> AdminRole | None:
    """Lấy role đang act-as từ session (nếu hợp lệ)."""
    if not has_request_context():
        return None

    if hasattr(g, "_act_as_role"):
        return g._act_as_role

    if session.get(ACT_AS_USER_MODE_KEY, False):
        g._act_as_role = None
        return None

    role_id = session.get(ACT_AS_SESSION_KEY)
    role = None
    roles = _get_active_admin_roles(user)
    preferred_role = next((r for r in roles if r.role_level == "faculty"), None)
    if preferred_role is None:
        preferred_role = next((r for r in roles if r.role_level == "department"), None)
    if preferred_role is None:
        preferred_role = next((r for r in roles if r.role_level == "university"), None)

    if role_id:
        role = next((r for r in roles if r.id == role_id), None)
        if role is None:
            role = AdminRole.query.filter_by(
                id=role_id, user_id=user.id, is_active=True
            ).first()
        if role is None:
            session.pop(ACT_AS_SESSION_KEY, None)
    elif len(roles) > 1 and preferred_role:
        session[ACT_AS_SESSION_KEY] = preferred_role.id
        role = preferred_role

    g._act_as_role = role
    return role


def get_effective_context(user: User) -> dict:
    """Ngữ cảnh hiệu lực cho quyền admin, có xét act-as."""
    if has_request_context() and hasattr(g, "_effective_admin_context"):
        return g._effective_admin_context

    if has_request_context() and session.get(ACT_AS_USER_MODE_KEY, False):
        ctx = {"level": "none", "act_as_role": None, "user_mode": True}
        g._effective_admin_context = ctx
        return ctx

    act_as_role = get_act_as_role(user)
    if act_as_role:
        level = act_as_role.role_level
    else:
        level = getattr(user, "highest_admin_level", None) or "none"

    if level not in ADMIN_LEVEL_HIERARCHY:
        level = "none"

    ctx = {"level": level, "act_as_role": act_as_role, "user_mode": False}
    if has_request_context():
        g._effective_admin_context = ctx
    return ctx


def has_university_access(user: User) -> bool:
    """Kiểm tra quyền cấp Trường có xét act-as."""
    if has_request_context() and session.get(ACT_AS_USER_MODE_KEY, False):
        return False
    ctx = get_effective_context(user)
    if ctx["act_as_role"] is not None:
        return ctx["level"] == "university"
    return user.has_admin_role("university") or ctx["level"] == "university"


def get_role_scope_ids(user, role_level: str) -> list[int]:
    """Lấy danh sách scope ids từ AdminRole theo cấp."""
    ctx = get_effective_context(user)
    act_as_role = ctx["act_as_role"]
    effective_level = ctx["level"]

    if ctx.get("user_mode"):
        return []

    # Nếu đang act-as, chỉ dùng scope của role đó
    if act_as_role:
        if act_as_role.role_level != role_level:
            return []
        if role_level == "faculty" and act_as_role.organization_unit_id:
            return [act_as_role.organization_unit_id]
        if role_level == "department" and act_as_role.division_id:
            return [act_as_role.division_id]
        return []

    roles = _get_active_admin_roles(user)
    scope_ids: list[int] = []
    for role in roles:
        if role.role_level != role_level:
            continue
        if role_level == "faculty" and role.organization_unit_id:
            scope_ids.append(role.organization_unit_id)
        elif role_level == "department" and role.division_id:
            scope_ids.append(role.division_id)

    # Loại trùng, giữ thứ tự ổn định
    return sorted(set(scope_ids))


def count_effective_admins_by_scope(
    role_level: str,
    organization_unit_id: int | None = None,
    division_id: int | None = None,
    exclude_role_id: int | None = None,
    exclude_user_id: int | None = None,
) -> int:
    """Đếm số admin đang hoạt động theo cấp + phạm vi (AdminRole là nguồn chuẩn)."""
    roles_query = (
        AdminRole.query.join(User, AdminRole.user_id == User.id)
        .filter(
            AdminRole.role_level == role_level,
            AdminRole.is_active == True,
            User.is_active == True,
        )
    )
    if role_level == "faculty" and organization_unit_id:
        roles_query = roles_query.filter(
            AdminRole.organization_unit_id == organization_unit_id
        )
    if role_level == "department" and division_id:
        roles_query = roles_query.filter(AdminRole.division_id == division_id)
    if exclude_role_id:
        roles_query = roles_query.filter(AdminRole.id != exclude_role_id)
    if exclude_user_id:
        roles_query = roles_query.filter(AdminRole.user_id != exclude_user_id)

    role_user_ids = [row.user_id for row in roles_query.all()]

    return len(role_user_ids)


def get_scope_permissions(
    admin_user: User, item_owner: User
) -> tuple[bool, bool, bool]:
    """Trả về quyền theo scope: (university, faculty, department)."""
    ctx = get_effective_context(admin_user)
    level = ctx["level"]
    act_as_role = ctx["act_as_role"]

    # Act-as: khóa cứng theo đúng role được chọn
    if act_as_role is not None:
        if level == "university":
            return True, True, True
        if level == "faculty":
            scope_id = act_as_role.organization_unit_id
            can_faculty = bool(scope_id and item_owner.organization_unit_id == scope_id)
            return False, can_faculty, False
        if level == "department":
            scope_id = act_as_role.division_id
            can_department = bool(scope_id and item_owner.division_id == scope_id)
            return False, False, can_department
        return False, False, False

    can_university = has_university_access(admin_user)

    can_faculty = False
    if item_owner.organization_unit_id:
        faculty_scope_ids = get_role_scope_ids(admin_user, "faculty")
        if faculty_scope_ids:
            can_faculty = item_owner.organization_unit_id in faculty_scope_ids
        else:
            can_faculty = admin_user.has_admin_role(
                "faculty", org_unit_id=item_owner.organization_unit_id
            ) or (
                level == "faculty"
                and item_owner.organization_unit_id == admin_user.organization_unit_id
            )

    can_department = False
    if item_owner.division_id:
        department_scope_ids = get_role_scope_ids(admin_user, "department")
        if department_scope_ids:
            can_department = item_owner.division_id in department_scope_ids
        else:
            can_department = admin_user.has_admin_role(
                "department", division_id=item_owner.division_id
            ) or (
                level == "department"
                and item_owner.division_id == admin_user.division_id
            )

    return can_university, can_faculty, can_department


def effective_admin_level(user) -> str:
    """Admin level hiệu lực (ưu tiên AdminRole/highest_admin_level)."""
    level = get_effective_context(user)["level"]
    return level if level in ADMIN_LEVEL_HIERARCHY else "none"


def is_office_user(user) -> bool:
    """
    Kiểm tra user có thuộc Phòng ban (office) không.
    Phòng ban do Trường duyệt trực tiếp (1 bước).
    """
    if not user.org_unit:
        return False
    return user.org_unit.unit_type == "office"


def has_department_admin_for_owner(item_owner: User) -> bool:
    if not item_owner or not getattr(item_owner, "division_id", None):
        return False
    return (
        count_effective_admins_by_scope(
            "department", division_id=item_owner.division_id
        )
        > 0
    )


def has_faculty_admin_for_owner(item_owner: User) -> bool:
    if not item_owner or not getattr(item_owner, "organization_unit_id", None):
        return False
    return (
        count_effective_admins_by_scope(
            "faculty", organization_unit_id=item_owner.organization_unit_id
        )
        > 0
    )


def filter_items_by_scope(query, model_class, admin_user):
    """
    Lọc query Publication/Project/Activity theo phạm vi admin.

    Args:
        query: SQLAlchemy query object
        model_class: Publication, Project, hoặc OtherActivity
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
            return query.join(User, model_class.user_id == User.id).filter(
                User.organization_unit_id.in_(org_unit_ids)
            )
        if admin_user.organization_unit_id:
            return query.join(User, model_class.user_id == User.id).filter(
                User.organization_unit_id == admin_user.organization_unit_id
            )
        return query.filter(model_class.id == -1)

    if level == "department":
        division_ids = get_role_scope_ids(admin_user, "department")
        if division_ids:
            return query.join(User, model_class.user_id == User.id).filter(
                User.division_id.in_(division_ids)
            )
        if admin_user.division_id:
            return query.join(User, model_class.user_id == User.id).filter(
                User.division_id == admin_user.division_id
            )
        return query.filter(model_class.id == -1)

    return query.filter(model_class.id == -1)  # Empty


def exclude_lower_level_pending(query, model_class, admin_user):
    """Ẩn hẳn pending cấp dưới khỏi mọi danh sách/kết quả."""
    from sqlalchemy import or_

    level = effective_admin_level(admin_user)

    # Admin Khoa: không thấy pending cấp Bộ môn
    if level == "faculty":
        return query.filter(model_class.approval_status != "pending")

    # Admin Trường: không thấy pending cấp Bộ môn/Khoa
    if level == "university":
        # 1) Loại bỏ department_approved (pending cấp Khoa)
        query = query.filter(model_class.approval_status != "department_approved")

        # 2) Với pending, chỉ giữ lại pending của Phòng ban
        # (pending của Khoa/Bộ môn là cấp dưới, cần ẩn hẳn)
        query = (
            query.join(User, model_class.user_id == User.id)
            .join(OrganizationUnit, User.organization_unit_id == OrganizationUnit.id)
            .filter(
                or_(
                    model_class.approval_status != "pending",
                    OrganizationUnit.unit_type == "office",
                )
            )
        )
        return query

    return query


# =============================================================================
# APPROVAL WORKFLOW (pure logic)
# =============================================================================


@dataclass(frozen=True)
class ApprovalContext:
    """All inputs needed to evaluate approval permissions and transitions."""

    current_status: str
    is_office: bool
    can_university: bool
    can_faculty: bool
    can_department: bool
    missing_department_admin: bool
    missing_faculty_admin: bool


def can_approve(ctx: ApprovalContext) -> tuple[bool, str]:
    """Return (can_approve, message). Message is non-empty only when not allowed."""

    s = ctx.current_status or "pending"

    # Office: university approves directly from pending
    if ctx.is_office:
        if s != "pending":
            return False, "Công trình không ở trạng thái chờ duyệt."
        if not ctx.can_university:
            return False, "Công trình thuộc Phòng ban, chỉ Admin Trường mới duyệt được."
        return True, ""

    # Faculty flow (3 steps) with skip when missing admins in chain
    if s == "pending":
        if ctx.can_department:
            return True, ""
        if ctx.can_faculty and ctx.missing_department_admin:
            return True, ""
        if (
            ctx.can_university
            and ctx.missing_department_admin
            and ctx.missing_faculty_admin
        ):
            return True, ""
        return False, "Cần quyền Admin Bộ môn đúng phạm vi để xác nhận."

    if s == "department_approved":
        if ctx.can_faculty:
            return True, ""
        if ctx.can_university and ctx.missing_faculty_admin:
            return True, ""
        return False, "Cần quyền Admin Khoa đúng phạm vi để duyệt bước này."

    if s == "faculty_approved":
        if ctx.can_university:
            return True, ""
        return False, "Cần quyền Admin Trường để phê duyệt bước cuối."

    return False, "Công trình không ở trạng thái chờ duyệt."


def next_status(ctx: ApprovalContext) -> str:
    """Return the next approval_status after an approve action."""

    s = ctx.current_status or "pending"

    # Office shortcut
    if ctx.is_office:
        return "approved" if s == "pending" and ctx.can_university else s

    if s == "pending":
        if ctx.can_department:
            return "department_approved"
        if ctx.can_faculty and ctx.missing_department_admin:
            return "faculty_approved"
        if (
            ctx.can_university
            and ctx.missing_department_admin
            and ctx.missing_faculty_admin
        ):
            return "approved"
        return s

    if s == "department_approved":
        if ctx.can_faculty:
            return "faculty_approved"
        if ctx.can_university and ctx.missing_faculty_admin:
            return "approved"
        return s

    if s == "faculty_approved":
        if ctx.can_university:
            return "approved"
        return s

    return s


def action_level(ctx: ApprovalContext) -> str | None:
    """Return which level is performing the approve at current state."""

    s = ctx.current_status or "pending"

    if ctx.is_office:
        if s == "pending" and ctx.can_university:
            return "university"
        return None

    if s == "pending":
        if ctx.can_department:
            return "department"
        if ctx.can_faculty and ctx.missing_department_admin:
            return "faculty"
        if (
            ctx.can_university
            and ctx.missing_department_admin
            and ctx.missing_faculty_admin
        ):
            return "university"
        return None

    if s == "department_approved":
        if ctx.can_faculty:
            return "faculty"
        if ctx.can_university and ctx.missing_faculty_admin:
            return "university"
        return None

    if s == "faculty_approved" and ctx.can_university:
        return "university"

    return None


def can_return(ctx: ApprovalContext) -> bool:
    """Return whether admin can return (send back) the item."""

    if ctx.is_office:
        return ctx.can_university

    return ctx.can_university or ctx.can_faculty or ctx.can_department


# Convenience wrappers used by route handlers


def approval_can_approve(
    *,
    current_status: str,
    is_office: bool,
    can_university: bool,
    can_faculty: bool,
    can_department: bool,
    missing_department: bool,
    missing_faculty: bool,
) -> tuple[bool, str]:
    ctx = ApprovalContext(
        current_status=current_status,
        is_office=is_office,
        can_university=can_university,
        can_faculty=can_faculty,
        can_department=can_department,
        missing_department_admin=missing_department,
        missing_faculty_admin=missing_faculty,
    )
    return can_approve(ctx)


def approval_next_status(
    *,
    current_status: str,
    is_office: bool,
    can_university: bool,
    can_faculty: bool,
    can_department: bool,
    missing_department: bool,
    missing_faculty: bool,
) -> str:
    ctx = ApprovalContext(
        current_status=current_status,
        is_office=is_office,
        can_university=can_university,
        can_faculty=can_faculty,
        can_department=can_department,
        missing_department_admin=missing_department,
        missing_faculty_admin=missing_faculty,
    )
    return next_status(ctx)


def approval_action_level(
    *,
    current_status: str,
    is_office: bool,
    can_university: bool,
    can_faculty: bool,
    can_department: bool,
    missing_department: bool,
    missing_faculty: bool,
) -> str | None:
    ctx = ApprovalContext(
        current_status=current_status,
        is_office=is_office,
        can_university=can_university,
        can_faculty=can_faculty,
        can_department=can_department,
        missing_department_admin=missing_department,
        missing_faculty_admin=missing_faculty,
    )
    return action_level(ctx)


def approval_can_return(
    *,
    is_office: bool,
    has_university_access: bool,
    can_university: bool,
    can_faculty: bool,
    can_department: bool,
) -> bool:
    # For office users, we only care about university access.
    ctx = ApprovalContext(
        current_status="pending",
        is_office=is_office,
        can_university=(has_university_access if is_office else can_university),
        can_faculty=can_faculty,
        can_department=can_department,
        missing_department_admin=False,
        missing_faculty_admin=False,
    )
    return can_return(ctx)


# =============================================================================
# APPROVAL ACTIONS (DB-writing)
# =============================================================================

Action = Literal["approve", "reject", "return"]


@dataclass(frozen=True)
class ApprovalActionResult:
    ok: bool
    new_status: str | None = None
    # A list of (message, category) suitable for Flask `flash()`
    flashes: list[tuple[str, str]] | None = None


_ACTION_MAP_BY_NEW_STATUS: dict[str, str] = {
    "department_approved": "department_approve",
    "faculty_approved": "faculty_approve",
    "approved": "university_approve",
}


_STATUS_DISPLAY: dict[str, str] = {
    "department_approved": "Bộ môn đã xác nhận",
    "faculty_approved": "Khoa đã duyệt",
    "approved": "Đã phê duyệt",
}


_ITEM_LABEL: dict[str, str] = {
    "publication": "ấn phẩm",
    "project": "đề tài",
    "activity": "hoạt động",
}


_MODEL_TO_ITEM_TYPE = {
    Publication: "publication",
    Project: "project",
    OtherActivity: "activity",
}


def check_approval_chain(item, admin_user: User) -> tuple[bool, str]:
    """Kiểm tra xem admin có thể duyệt item này không.

    Hàm này được giữ để tương thích ngược với code admin templates/routes cũ.
    """
    current_status = getattr(item, "approval_status", "pending")
    item_owner = User.query.get(getattr(item, "user_id", None))
    if not item_owner:
        return False, "Không tìm thấy chủ sở hữu công trình."

    can_university, can_faculty, can_department = get_scope_permissions(
        admin_user, item_owner
    )
    missing_department = not has_department_admin_for_owner(item_owner)
    missing_faculty = not has_faculty_admin_for_owner(item_owner)

    return approval_can_approve(
        current_status=current_status,
        is_office=is_office_user(item_owner),
        can_university=can_university,
        can_faculty=can_faculty,
        can_department=can_department,
        missing_department=missing_department,
        missing_faculty=missing_faculty,
    )


def resolve_next_approval_status(
    current_status: str, item_owner: User, admin_user: User
) -> str:
    """Tính trạng thái kế tiếp khi duyệt (approve).

    Giữ tên hàm để tương thích ngược.
    """
    if not item_owner:
        return current_status

    can_university, can_faculty, can_department = get_scope_permissions(
        admin_user, item_owner
    )
    missing_department = not has_department_admin_for_owner(item_owner)
    missing_faculty = not has_faculty_admin_for_owner(item_owner)

    return approval_next_status(
        current_status=current_status,
        is_office=is_office_user(item_owner),
        can_university=can_university,
        can_faculty=can_faculty,
        can_department=can_department,
        missing_department=missing_department,
        missing_faculty=missing_faculty,
    )


def get_approval_action_level(item, admin_user: User) -> str | None:
    """Xác định 'level' của nút duyệt hiện tại (Bộ môn/Khoa/Trường).

    Giữ tên hàm để tương thích ngược.
    """
    current_status = getattr(item, "approval_status", "pending")
    item_owner = User.query.get(getattr(item, "user_id", None))
    if not item_owner:
        return None

    can_university, can_faculty, can_department = get_scope_permissions(
        admin_user, item_owner
    )
    missing_department = not has_department_admin_for_owner(item_owner)
    missing_faculty = not has_faculty_admin_for_owner(item_owner)

    return approval_action_level(
        current_status=current_status,
        is_office=is_office_user(item_owner),
        can_university=can_university,
        can_faculty=can_faculty,
        can_department=can_department,
        missing_department=missing_department,
        missing_faculty=missing_faculty,
    )


def can_return_item(item, admin_user: User) -> bool:
    """Kiểm tra quyền trả lại (return) theo scope + AdminRole.

    Giữ tên hàm để tương thích ngược.
    """
    item_owner = User.query.get(getattr(item, "user_id", None))
    if not item_owner:
        return False

    if is_office_user(item_owner):
        return approval_can_return(
            is_office=True,
            has_university_access=has_university_access(admin_user),
            can_university=False,
            can_faculty=False,
            can_department=False,
        )

    can_university, can_faculty, can_department = get_scope_permissions(
        admin_user, item_owner
    )
    return approval_can_return(
        is_office=False,
        has_university_access=False,
        can_university=can_university,
        can_faculty=can_faculty,
        can_department=can_department,
    )


def _short_title(item) -> str:
    t = getattr(item, "title", "") or ""
    t = str(t)
    return (t[:50] + "...") if len(t) > 50 else t


def _missing_admin_warning_for_owner(owner: User) -> str | None:
    """Return a warning message if the approval chain is missing admins."""

    if not owner or is_office_user(owner):
        return None

    missing_department = not has_department_admin_for_owner(owner)
    missing_faculty = not has_faculty_admin_for_owner(owner)
    if not (missing_department or missing_faculty):
        return None

    parts: list[str] = []
    if missing_department:
        parts.append("thiếu Admin Bộ môn")
    if missing_faculty:
        parts.append("thiếu Admin Khoa")
    joined = " và ".join(parts)
    return f"Cảnh báo: {joined}. Hệ thống có thể bỏ qua một số bước duyệt trong chuỗi duyệt."  # noqa: E501


def get_scoped_item_or_none(
    model_class,
    item_id: int,
    *,
    actor,
    include_lower_pending: bool = False,
):
    """Fetch an item by id within the actor's effective admin scope.

    This centralizes the commonly duplicated pattern in admin routes.
    """

    scoped_query = filter_items_by_scope(model_class.query, model_class, actor)
    if not include_lower_pending:
        scoped_query = exclude_lower_level_pending(scoped_query, model_class, actor)
    return scoped_query.filter(model_class.id == item_id).first()


def apply_approval_action_by_id(
    *,
    model_class,
    item_id: int,
    action: Action,
    actor,
    reason: str | None = None,
    include_lower_pending: bool = False,
    commit: bool = True,
    collect_flashes: bool = True,
) -> ApprovalActionResult:
    """Convenience wrapper: scope-check + apply action.

    Returns a failed result with a user-friendly message when the item is
    outside the actor's current working scope.
    """

    item = get_scoped_item_or_none(
        model_class,
        item_id,
        actor=actor,
        include_lower_pending=include_lower_pending,
    )
    if not item:
        return ApprovalActionResult(
            ok=False,
            flashes=(
                [("Mục này nằm ngoài phạm vi bạn đang làm việc.", "error")]
                if collect_flashes
                else []
            ),
        )

    item_type = _MODEL_TO_ITEM_TYPE.get(model_class)
    if not item_type:
        # Fallback: best-effort type name
        item_type = getattr(model_class, "__name__", "item").lower()

    return apply_approval_action(
        item=item,
        item_type=item_type,  # type: ignore[arg-type]
        action=action,
        actor=actor,
        reason=reason,
        commit=commit,
        collect_flashes=collect_flashes,
    )


def apply_approval_action(
    *,
    item,
    item_type: Literal["publication", "project", "activity"],
    action: Action,
    actor,
    reason: str | None = None,
    commit: bool = True,
    collect_flashes: bool = True,
) -> ApprovalActionResult:
    """Apply an approval action to an item.

    Parameters
    ----------
    item:
        A SQLAlchemy model instance (Publication / Project / OtherActivity).
    item_type:
        "publication" | "project" | "activity" (used for logs and messages).
    action:
        "approve" | "reject" | "return".
    actor:
        Current admin user.
    reason:
        Required for action="return".
    commit:
        When False, the caller is responsible for committing the session.
        Useful for batch approve.
    """

    flashes: list[tuple[str, str]] = []

    # Owner is needed for workflow decisions and warnings.
    owner = User.query.get(getattr(item, "user_id", None))
    if not owner:
        return ApprovalActionResult(
            ok=False, flashes=[("Không tìm thấy chủ sở hữu công trình.", "error")]
        )

    old_status = getattr(item, "approval_status", "pending") or "pending"

    if action == "approve":
        can_do, message = check_approval_chain(item, actor)
        if not can_do:
            return ApprovalActionResult(
                ok=False, flashes=[(message or "Bạn không có quyền duyệt.", "error")]
            )

        # Optional warning for missing admins in chain (only meaningful at first step).
        if collect_flashes and old_status == "pending":
            warn = _missing_admin_warning_for_owner(owner)
            if warn:
                flashes.append((warn, "warning"))

        new_status = resolve_next_approval_status(old_status, owner, actor)
        item.approval_status = new_status
        item.rejection_reason = None
        item.returned_at = None

        if new_status == "approved":
            item.is_approved = True
            item.approved_at = datetime.utcnow()
            item.approved_by = actor.id

        db.session.add(
            ApprovalLog(
                item_type=item_type,
                item_id=item.id,
                action=_ACTION_MAP_BY_NEW_STATUS.get(new_status, "approve"),
                old_status=old_status,
                new_status=new_status,
                performed_by=actor.id,
            )
        )

        if collect_flashes:
            label = _ITEM_LABEL.get(item_type, "mục")
            flashes.append(
                (
                    f"{_STATUS_DISPLAY.get(new_status, 'Đã duyệt')}: {label} {(_short_title(item))}",
                    "success",
                )
            )

        if commit:
            db.session.commit()
        return ApprovalActionResult(
            ok=True, new_status=new_status, flashes=flashes if collect_flashes else []
        )

    if action == "reject":
        # Reject resets to pending. Permission is normally ensured by route decorator.
        new_status = "pending"
        item.is_approved = False
        item.approval_status = new_status
        item.approved_at = None
        item.approved_by = None
        item.rejection_reason = None
        item.returned_at = None
        item.returned_by_level = None

        db.session.add(
            ApprovalLog(
                item_type=item_type,
                item_id=item.id,
                action="reject",
                old_status=old_status,
                new_status=new_status,
                performed_by=actor.id,
            )
        )

        if commit:
            db.session.commit()

        label = _ITEM_LABEL.get(item_type, "mục")
        msg = (f"Đã hủy duyệt {label}: {(_short_title(item))}", "success")
        return ApprovalActionResult(
            ok=True,
            new_status=new_status,
            flashes=[msg] if collect_flashes else [],
        )

    if action == "return":
        reason = (reason or "").strip()
        if not reason:
            return ApprovalActionResult(
                ok=False, flashes=[("Vui lòng nhập lý do trả lại.", "error")]
            )

        if old_status == "approved":
            return ApprovalActionResult(
                ok=False,
                flashes=[
                    (
                        "Công trình đã được phê duyệt. Hãy dùng chức năng hủy duyệt.",
                        "error",
                    )
                ],
            )

        if not can_return_item(item, actor):
            return ApprovalActionResult(
                ok=False, flashes=[("Bạn không có quyền trả lại mục này.", "error")]
            )

        new_status = "returned"
        item.is_approved = False
        item.approval_status = new_status
        item.rejection_reason = reason
        item.returned_at = datetime.utcnow()
        item.approved_at = None
        item.approved_by = None
        item.returned_by_level = effective_admin_level(actor)

        db.session.add(
            ApprovalLog(
                item_type=item_type,
                item_id=item.id,
                action="return",
                old_status=old_status,
                new_status=new_status,
                performed_by=actor.id,
                notes=reason,
            )
        )

        if commit:
            db.session.commit()

        label = _ITEM_LABEL.get(item_type, "mục")
        msg = (f"Đã trả lại {label}: {(_short_title(item))}", "warning")
        return ApprovalActionResult(
            ok=True,
            new_status=new_status,
            flashes=[msg] if collect_flashes else [],
        )

    return ApprovalActionResult(
        ok=False, flashes=[("Hành động không hợp lệ.", "error")]
    )
