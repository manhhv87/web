"""Admin approval routes for publications, projects, and other activities."""

from __future__ import annotations

from urllib.parse import urlparse, urlencode

from flask_login import login_required

from app.services.approval import (
    apply_approval_action,
    apply_approval_action_by_id,
    get_scoped_item_or_none as get_scoped_item_or_none_in_scope,
)

from . import admin_bp
from .helpers import *  # noqa: F403


def _safe_next_url(url, fallback):
    """Trả về URL an toàn (chỉ relative path, không cho //evil.com)."""
    if not url:
        return fallback
    parsed = urlparse(str(url))
    if parsed.scheme or parsed.netloc or not str(url).startswith("/"):
        return fallback
    return str(url)


def _build_pagination_base(endpoint: str) -> str:
    """Build base URL for pagination links, preserving current filters."""
    base = url_for(endpoint)
    params = request.args.to_dict(flat=True)
    params.pop("page", None)
    if params:
        return f"{base}?{urlencode(params)}&page="
    return f"{base}?page="

# =============================================================================
# APPROVAL MANAGEMENT - PUBLICATIONS
# =============================================================================


@admin_bp.route("/publications")
@login_required
@admin_required
def list_all_publications():
    """Danh sách ấn phẩm (theo phạm vi admin)"""
    raw_status = request.args.get("status")
    year = request.args.get("year", type=int)
    user_id = request.args.get("user_id", type=int)
    org_unit_id = request.args.get("org_unit_id", type=int)
    division_id = request.args.get("division_id", type=int)
    page = request.args.get("page", type=int, default=1)
    per_page = request.args.get("per_page", type=int, default=20)
    per_page = max(10, min(per_page, 100))
    effective_level = effective_admin_level(current_user)
    can_university = has_university_access(current_user)

    # Lấy trạng thái chờ duyệt cho cấp admin này
    my_pending_status = get_approval_status_for_level(effective_level)
    pending_total = filter_my_pending_items(
        Publication.query, Publication, current_user
    ).count()

    # Mặc định: Tất cả. Nếu có việc cần duyệt thì ưu tiên mở "Cần phê duyệt".
    default_status = "pending" if pending_total > 0 else "all"
    status = normalize_status_filter(raw_status or default_status)

    # Lọc theo trạng thái
    if status == "pending":
        # pending trên UI luôn nghĩa là "cần TÔI xử lý"
        query = filter_my_pending_items(Publication.query, Publication, current_user)
    else:
        # Các filter khác - lọc theo phạm vi admin trước
        query = filter_items_by_scope(Publication.query, Publication, current_user)
        query = exclude_lower_level_pending(query, Publication, current_user)
        if status == "approved":
            approved_statuses = get_approved_statuses(current_user)
            query = query.filter(Publication.approval_status.in_(approved_statuses))
        elif status == "returned":
            query = query.filter(Publication.approval_status == "returned")

    # Dữ liệu filter theo phạm vi (Khoa/Phòng ban, Bộ môn, Người dùng)
    org_units, divisions, users, filtered_user_ids_sq = build_scope_filter_data(
        current_user, org_unit_id, division_id
    )

    # Lọc theo Khoa/Phòng ban hoặc Bộ môn mà không join trùng bảng User
    if org_unit_id or division_id:
        query = query.filter(Publication.user_id.in_(select(filtered_user_ids_sq.c.id)))

    if year:
        query = query.filter(Publication.year == year)

    if user_id:
        query = query.filter(Publication.user_id == user_id)

    # Pagination
    pagination = db.paginate(
        query.order_by(Publication.created_at.desc()),
        page=page,
        per_page=per_page,
        error_out=False,
    )
    pending_filtered_count = pagination.total if status == "pending" else None
    publications = pagination.items

    # Tính giờ và kiểm tra quyền duyệt
    for pub in publications:
        hours = calculate_publication_hours(pub)
        pub.base_hours = hours["base_hours"]
        pub.author_hours = hours["author_hours"]
        # Kiểm tra có thể duyệt không
        can_approve, _ = check_approval_chain(pub, current_user)
        pub.can_approve = can_approve
        pub.approval_action_level = get_approval_action_level(pub, current_user)
        pub.can_return = (
            can_return_item(pub, current_user) and pub.approval_status != "approved"
        )
        pub.can_reject = pub.approval_status == "approved" and can_university

    # Lấy danh sách users (theo phạm vi) và years cho filter
    years = (
        db.session.query(Publication.year)
        .distinct()
        .order_by(Publication.year.desc())
        .all()
    )
    years = [y[0] for y in years]

    return render_template(
        "admin/publications/list.html",
        publications=publications,
        pagination=pagination,
        per_page=per_page,
        org_units=org_units,
        divisions=divisions,
        users=users,
        years=years,
        selected_status=status,
        selected_org_unit_id=org_unit_id,
        selected_division_id=division_id,
        selected_year=year,
        selected_user_id=user_id,
        pub_type_choices=PUBLICATION_TYPE_CHOICES,
        my_pending_status=my_pending_status,
        admin_level=effective_level,
        pending_total=pending_total,
        pending_filtered_count=pending_filtered_count,
        pagination_base_url=_build_pagination_base("admin.list_all_publications"),
    )


@admin_bp.route("/publications/<int:pub_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_publication(pub_id):
    """
    Duyệt ấn phẩm theo quy trình 3 cấp:
    - Admin BM: pending -> department_approved
    - Admin Khoa: department_approved -> faculty_approved
    - Admin Trường: faculty_approved -> approved
    """
    result = apply_approval_action_by_id(
        model_class=Publication,
        item_id=pub_id,
        action="approve",
        actor=current_user,
        include_lower_pending=True,
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    if not result.ok:
        return redirect(request.referrer or url_for("admin.list_all_publications"))
    return redirect(request.referrer or url_for("admin.list_all_publications"))


@admin_bp.route("/publications/<int:pub_id>/reject", methods=["POST"])
@login_required
@university_admin_required  # Chỉ Admin Trường mới hủy duyệt (reset về pending)
def reject_publication(pub_id):
    """Hủy duyệt ấn phẩm (reset về pending) - Chỉ Admin Trường"""
    result = apply_approval_action_by_id(
        model_class=Publication,
        item_id=pub_id,
        action="reject",
        actor=current_user,
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    return redirect(request.referrer or url_for("admin.list_all_publications"))


@admin_bp.route("/publications/<int:pub_id>/return", methods=["POST"])
@login_required
@admin_required
def return_publication(pub_id):
    """Trả lại ấn phẩm với lý do - Tất cả cấp admin trong phạm vi"""
    result = apply_approval_action_by_id(
        model_class=Publication,
        item_id=pub_id,
        action="return",
        actor=current_user,
        reason=request.form.get("reason", ""),
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    return redirect(request.referrer or url_for("admin.list_all_publications"))


@admin_bp.route("/publications/<int:pub_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_publication(pub_id):
    """Xóa ấn phẩm (admin)"""
    pub = get_scoped_item_or_none_in_scope(Publication, pub_id, actor=current_user)
    if not pub:
        flash("Ấn phẩm này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(request.referrer or url_for("admin.list_all_publications"))
    title = pub.title[:50]
    db.session.delete(pub)
    db.session.commit()

    flash(f"Đã xóa ấn phẩm: {title}...", "success")
    return redirect(request.referrer or url_for("admin.list_all_publications"))


@admin_bp.route("/publications/<int:pub_id>/view")
@login_required
@admin_required
def view_publication(pub_id):
    """Xem chi tiết ấn phẩm (admin)"""
    pub = get_scoped_item_or_none_in_scope(Publication, pub_id, actor=current_user)
    if not pub:
        flash("Ấn phẩm này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(request.referrer or url_for("admin.list_all_publications"))

    hours = calculate_publication_hours(pub)
    pub.base_hours = hours["base_hours"]
    pub.author_hours = hours["author_hours"]

    return render_template("admin/publications/view.html", publication=pub)


@admin_bp.route("/publications/<int:pub_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_publication(pub_id):
    """Sửa ấn phẩm (admin)"""
    from app.blueprints.publications.routes import _update_publication_from_form

    pub = get_scoped_item_or_none_in_scope(Publication, pub_id, actor=current_user)
    if not pub:
        flash("Ấn phẩm này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_all_publications"))

    if request.method == "POST":
        _update_publication_from_form(pub, request.form)
        db.session.commit()
        flash(f"Đã cập nhật ấn phẩm: {pub.title[:50]}...", "success")
        return redirect(url_for("admin.list_all_publications"))

    return render_template(
        "admin/publications/form.html",
        action="edit",
        publication=pub,
        pub_type_choices=PUBLICATION_TYPE_CHOICES,
        quartile_choices=QUARTILE_CHOICES,
        author_role_choices=AUTHOR_ROLE_CHOICES,
        patent_stage_choices=PATENT_STAGE_CHOICES,
        current_year=datetime.now().year,
    )


# =============================================================================
# APPROVAL MANAGEMENT - PROJECTS
# =============================================================================


@admin_bp.route("/projects")
@login_required
@admin_required
def list_all_projects():
    """Danh sách đề tài/dự án (theo phạm vi admin)"""
    raw_status = request.args.get("status")
    year = request.args.get("year", type=int)
    user_id = request.args.get("user_id", type=int)
    org_unit_id = request.args.get("org_unit_id", type=int)
    division_id = request.args.get("division_id", type=int)
    page = request.args.get("page", type=int, default=1)
    per_page = request.args.get("per_page", type=int, default=20)
    per_page = max(10, min(per_page, 100))
    effective_level = effective_admin_level(current_user)
    can_university = has_university_access(current_user)

    # Lấy trạng thái chờ duyệt cho cấp admin này
    my_pending_status = get_approval_status_for_level(effective_level)
    pending_total = filter_my_pending_items(
        Project.query, Project, current_user
    ).count()

    # Mặc định: Tất cả. Nếu có việc cần duyệt thì ưu tiên mở "Cần phê duyệt".
    default_status = "pending" if pending_total > 0 else "all"
    status = normalize_status_filter(raw_status or default_status)

    # Lọc theo trạng thái
    if status == "pending":
        # pending trên UI luôn nghĩa là "cần TÔI xử lý"
        query = filter_my_pending_items(Project.query, Project, current_user)
    else:
        # Các filter khác - lọc theo phạm vi admin trước
        query = filter_items_by_scope(Project.query, Project, current_user)
        query = exclude_lower_level_pending(query, Project, current_user)
        if status == "approved":
            approved_statuses = get_approved_statuses(current_user)
            query = query.filter(Project.approval_status.in_(approved_statuses))
        elif status == "returned":
            query = query.filter(Project.approval_status == "returned")

    # Dữ liệu filter theo phạm vi (Khoa/Phòng ban, Bộ môn, Người dùng)
    org_units, divisions, users, filtered_user_ids_sq = build_scope_filter_data(
        current_user, org_unit_id, division_id
    )

    # Lọc theo Khoa/Phòng ban hoặc Bộ môn mà không join trùng bảng User
    if org_unit_id or division_id:
        query = query.filter(Project.user_id.in_(select(filtered_user_ids_sq.c.id)))

    if year:
        query = query.filter(Project.start_year <= year, Project.end_year >= year)

    if user_id:
        query = query.filter(Project.user_id == user_id)

    pagination = db.paginate(
        query.order_by(Project.created_at.desc()),
        page=page,
        per_page=per_page,
        error_out=False,
    )
    pending_filtered_count = pagination.total if status == "pending" else None
    projects = pagination.items

    # Tính giờ và kiểm tra quyền
    for proj in projects:
        hours = calculate_project_hours_from_model(proj)
        proj.total_hours = hours["total_hours"]
        proj.user_hours = hours["user_hours"]
        can_approve, _ = check_approval_chain(proj, current_user)
        proj.can_approve = can_approve
        proj.approval_action_level = get_approval_action_level(proj, current_user)
        proj.can_return = (
            can_return_item(proj, current_user) and proj.approval_status != "approved"
        )
        proj.can_reject = proj.approval_status == "approved" and can_university

    # Lấy danh sách users (theo phạm vi) và years
    all_projects = filter_items_by_scope(Project.query, Project, current_user).all()
    years = set()
    for p in all_projects:
        for y in range(p.start_year, p.end_year + 1):
            years.add(y)
    years = sorted(years, reverse=True)

    return render_template(
        "admin/projects/list.html",
        projects=projects,
        pagination=pagination,
        per_page=per_page,
        org_units=org_units,
        divisions=divisions,
        users=users,
        years=years,
        selected_status=status,
        selected_org_unit_id=org_unit_id,
        selected_division_id=division_id,
        selected_year=year,
        selected_user_id=user_id,
        level_choices=PROJECT_LEVEL_CHOICES,
        my_pending_status=my_pending_status,
        admin_level=effective_level,
        pending_total=pending_total,
        pending_filtered_count=pending_filtered_count,
        pagination_base_url=_build_pagination_base("admin.list_all_projects"),
    )


@admin_bp.route("/projects/<int:proj_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_project(proj_id):
    """Duyệt đề tài theo quy trình 3 cấp"""
    result = apply_approval_action_by_id(
        model_class=Project,
        item_id=proj_id,
        action="approve",
        actor=current_user,
        include_lower_pending=True,
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    return redirect(request.referrer or url_for("admin.list_all_projects"))


@admin_bp.route("/projects/<int:proj_id>/reject", methods=["POST"])
@login_required
@university_admin_required  # Chỉ Admin Trường
def reject_project(proj_id):
    """Hủy duyệt đề tài - Chỉ Admin Trường"""
    result = apply_approval_action_by_id(
        model_class=Project,
        item_id=proj_id,
        action="reject",
        actor=current_user,
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    return redirect(request.referrer or url_for("admin.list_all_projects"))


@admin_bp.route("/projects/<int:proj_id>/return", methods=["POST"])
@login_required
@admin_required
def return_project(proj_id):
    """Trả lại đề tài với lý do"""
    result = apply_approval_action_by_id(
        model_class=Project,
        item_id=proj_id,
        action="return",
        actor=current_user,
        reason=request.form.get("reason", ""),
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    return redirect(request.referrer or url_for("admin.list_all_projects"))


@admin_bp.route("/projects/<int:proj_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_project(proj_id):
    """Xóa đề tài (admin)"""
    proj = get_scoped_item_or_none_in_scope(Project, proj_id, actor=current_user)
    if not proj:
        flash("Đề tài này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(request.referrer or url_for("admin.list_all_projects"))
    title = proj.title[:50]
    db.session.delete(proj)
    db.session.commit()

    flash(f"Đã xóa đề tài: {title}...", "success")
    return redirect(request.referrer or url_for("admin.list_all_projects"))


@admin_bp.route("/projects/<int:proj_id>/view")
@login_required
@admin_required
def view_project(proj_id):
    """Xem chi tiết đề tài (admin)"""
    proj = get_scoped_item_or_none_in_scope(Project, proj_id, actor=current_user)
    if not proj:
        flash("Đề tài này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_all_projects"))

    hours_detail = calculate_project_hours_from_model(proj)
    proj.total_hours = hours_detail["total_hours"]
    proj.user_hours = hours_detail["user_hours"]

    return render_template(
        "admin/projects/view.html",
        project=proj,
        hours_detail=hours_detail,
    )


@admin_bp.route("/projects/<int:proj_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_project(proj_id):
    """Sửa đề tài (admin)"""
    from app.blueprints.projects.routes import _update_project_from_form

    proj = get_scoped_item_or_none_in_scope(Project, proj_id, actor=current_user)
    if not proj:
        flash("Đề tài này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_all_projects"))

    if request.method == "POST":
        _update_project_from_form(proj, request.form)
        db.session.commit()
        flash(f"Đã cập nhật đề tài: {proj.title[:50]}...", "success")
        return redirect(url_for("admin.list_all_projects"))

    return render_template(
        "admin/projects/form.html",
        action="edit",
        project=proj,
        level_choices=PROJECT_LEVEL_CHOICES,
        role_choices=PROJECT_ROLE_CHOICES,
        status_choices=PROJECT_STATUS_CHOICES,
        current_year=datetime.now().year,
    )


# =============================================================================
# APPROVAL MANAGEMENT - OTHER ACTIVITIES
# =============================================================================


@admin_bp.route("/activities")
@login_required
@admin_required
def list_all_activities():
    """Danh sách hoạt động KHCN (theo phạm vi admin)"""
    raw_status = request.args.get("status")
    year = request.args.get("year", type=int)
    user_id = request.args.get("user_id", type=int)
    org_unit_id = request.args.get("org_unit_id", type=int)
    division_id = request.args.get("division_id", type=int)
    page = request.args.get("page", type=int, default=1)
    per_page = request.args.get("per_page", type=int, default=20)
    per_page = max(10, min(per_page, 100))
    effective_level = effective_admin_level(current_user)
    can_university = has_university_access(current_user)

    # Lấy trạng thái chờ duyệt cho cấp admin này
    my_pending_status = get_approval_status_for_level(effective_level)
    pending_total = filter_my_pending_items(
        OtherActivity.query, OtherActivity, current_user
    ).count()

    # Mặc định: Tất cả. Nếu có việc cần duyệt thì ưu tiên mở "Cần phê duyệt".
    default_status = "pending" if pending_total > 0 else "all"
    status = normalize_status_filter(raw_status or default_status)

    # Lọc theo trạng thái
    if status == "pending":
        # pending trên UI luôn nghĩa là "cần TÔI xử lý"
        query = filter_my_pending_items(
            OtherActivity.query, OtherActivity, current_user
        )
    else:
        # Các filter khác - lọc theo phạm vi admin trước
        query = filter_items_by_scope(OtherActivity.query, OtherActivity, current_user)
        query = exclude_lower_level_pending(query, OtherActivity, current_user)
        if status == "approved":
            approved_statuses = get_approved_statuses(current_user)
            query = query.filter(OtherActivity.approval_status.in_(approved_statuses))
        elif status == "returned":
            query = query.filter(OtherActivity.approval_status == "returned")

    # Dữ liệu filter theo phạm vi (Khoa/Phòng ban, Bộ môn, Người dùng)
    org_units, divisions, users, filtered_user_ids_sq = build_scope_filter_data(
        current_user, org_unit_id, division_id
    )

    # Lọc theo Khoa/Phòng ban hoặc Bộ môn mà không join trùng bảng User
    if org_unit_id or division_id:
        query = query.filter(
            OtherActivity.user_id.in_(select(filtered_user_ids_sq.c.id))
        )

    if year:
        query = query.filter(OtherActivity.year == year)

    if user_id:
        query = query.filter(OtherActivity.user_id == user_id)

    pagination = db.paginate(
        query.order_by(OtherActivity.created_at.desc()),
        page=page,
        per_page=per_page,
        error_out=False,
    )
    pending_filtered_count = pagination.total if status == "pending" else None
    activities = pagination.items

    # Tính giờ và kiểm tra quyền
    for act in activities:
        act.hours = calculate_other_activity_hours_from_model(act)
        can_approve, _ = check_approval_chain(act, current_user)
        act.can_approve = can_approve
        act.approval_action_level = get_approval_action_level(act, current_user)
        act.can_return = (
            can_return_item(act, current_user) and act.approval_status != "approved"
        )
        act.can_reject = act.approval_status == "approved" and can_university

    # Lấy danh sách users (theo phạm vi) và years
    years = (
        db.session.query(OtherActivity.year)
        .distinct()
        .order_by(OtherActivity.year.desc())
        .all()
    )
    years = [y[0] for y in years]

    return render_template(
        "admin/activities/list.html",
        activities=activities,
        pagination=pagination,
        per_page=per_page,
        org_units=org_units,
        divisions=divisions,
        users=users,
        years=years,
        selected_status=status,
        selected_org_unit_id=org_unit_id,
        selected_division_id=division_id,
        selected_year=year,
        selected_user_id=user_id,
        type_choices=OTHER_ACTIVITY_TYPE_CHOICES,
        my_pending_status=my_pending_status,
        admin_level=effective_level,
        pending_total=pending_total,
        pending_filtered_count=pending_filtered_count,
        pagination_base_url=_build_pagination_base("admin.list_all_activities"),
    )


@admin_bp.route("/activities/<int:act_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_activity(act_id):
    """Duyệt hoạt động theo quy trình 3 cấp"""
    result = apply_approval_action_by_id(
        model_class=OtherActivity,
        item_id=act_id,
        action="approve",
        actor=current_user,
        include_lower_pending=True,
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    return redirect(request.referrer or url_for("admin.list_all_activities"))


@admin_bp.route("/activities/<int:act_id>/reject", methods=["POST"])
@login_required
@university_admin_required  # Chỉ Admin Trường
def reject_activity(act_id):
    """Hủy duyệt hoạt động - Chỉ Admin Trường"""
    result = apply_approval_action_by_id(
        model_class=OtherActivity,
        item_id=act_id,
        action="reject",
        actor=current_user,
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    return redirect(request.referrer or url_for("admin.list_all_activities"))


@admin_bp.route("/activities/<int:act_id>/return", methods=["POST"])
@login_required
@admin_required
def return_activity(act_id):
    """Trả lại hoạt động với lý do"""
    result = apply_approval_action_by_id(
        model_class=OtherActivity,
        item_id=act_id,
        action="return",
        actor=current_user,
        reason=request.form.get("reason", ""),
    )
    for msg, category in result.flashes or []:
        flash(msg, category)
    return redirect(request.referrer or url_for("admin.list_all_activities"))


@admin_bp.route("/activities/<int:act_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_activity(act_id):
    """Xóa hoạt động (admin)"""
    act = get_scoped_item_or_none_in_scope(OtherActivity, act_id, actor=current_user)
    if not act:
        flash("Hoạt động này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(request.referrer or url_for("admin.list_all_activities"))
    title = act.title[:50]
    db.session.delete(act)
    db.session.commit()

    flash(f"Đã xóa hoạt động: {title}...", "success")
    return redirect(request.referrer or url_for("admin.list_all_activities"))


@admin_bp.route("/activities/<int:act_id>/view")
@login_required
@admin_required
def view_activity(act_id):
    """Xem chi tiết hoạt động (admin)"""
    act = get_scoped_item_or_none_in_scope(OtherActivity, act_id, actor=current_user)
    if not act:
        flash("Hoạt động này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_all_activities"))
    act.hours = calculate_other_activity_hours_from_model(act)

    return render_template("admin/activities/view.html", activity=act)


@admin_bp.route("/activities/<int:act_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_activity(act_id):
    """Sửa hoạt động (admin)"""
    from app.blueprints.activities.routes import _update_activity_from_form

    act = get_scoped_item_or_none_in_scope(OtherActivity, act_id, actor=current_user)
    if not act:
        flash("Hoạt động này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.list_all_activities"))

    if request.method == "POST":
        _update_activity_from_form(act, request.form)
        db.session.commit()
        flash(f"Đã cập nhật hoạt động: {act.title[:50]}...", "success")
        return redirect(url_for("admin.list_all_activities"))

    return render_template(
        "admin/activities/form.html",
        action="edit",
        activity=act,
        type_choices=OTHER_ACTIVITY_TYPE_CHOICES,
        current_year=datetime.now().year,
    )


# =============================================================================
# BATCH APPROVAL
# =============================================================================


@admin_bp.route("/approve-all", methods=["POST"])
@login_required
@admin_required
def approve_all_pending():
    """Duyệt tất cả các mục chờ duyệt"""
    item_type = request.form.get("type", "all")
    next_url = _safe_next_url(
        request.form.get("next") or request.referrer,
        url_for("admin.dashboard"),
    )

    def batch_approve(model_class, item_type_name: str) -> int:
        approved_count = 0
        items = filter_my_pending_items(
            model_class.query, model_class, current_user
        ).all()
        for item in items:
            res = apply_approval_action(
                item=item,
                item_type=item_type_name,  # type: ignore[arg-type]
                action="approve",
                actor=current_user,
                commit=False,
                collect_flashes=False,
            )
            if res.ok:
                approved_count += 1
        return approved_count

    count = 0
    if item_type in ("all", "publications"):
        count += batch_approve(Publication, "publication")
    if item_type in ("all", "projects"):
        count += batch_approve(Project, "project")
    if item_type in ("all", "activities"):
        count += batch_approve(OtherActivity, "activity")

    db.session.commit()

    flash(f"Đã duyệt {count} mục.", "success")
    return redirect(next_url)
