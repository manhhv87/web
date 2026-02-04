"""Admin organization management routes (departments/org units/divisions)."""

from __future__ import annotations

from flask_login import login_required

from . import admin_bp
from .helpers import *  # noqa: F403

# =============================================================================
# DEPARTMENT MANAGEMENT
# =============================================================================


@admin_bp.route("/departments")
@login_required
@admin_required
def manage_departments():
    """Quản lý bộ môn"""
    departments = Department.query.order_by(Department.name).all()
    return render_template("admin/departments/list.html", departments=departments)


# =============================================================================
# ORGANIZATION UNITS & DIVISIONS (DB is the source of truth)
# =============================================================================


@admin_bp.route("/org-units")
@login_required
@university_admin_required
def manage_org_units():
    """Quản lý Khoa/Phòng ban (OrganizationUnit)"""
    from sqlalchemy import func

    org_units = OrganizationUnit.query.order_by(
        OrganizationUnit.unit_type, OrganizationUnit.name
    ).all()

    div_counts = dict(
        db.session.query(Division.organization_unit_id, func.count(Division.id))
        .group_by(Division.organization_unit_id)
        .all()
    )
    user_counts = dict(
        db.session.query(User.organization_unit_id, func.count(User.id))
        .group_by(User.organization_unit_id)
        .all()
    )

    # Pass counts separately to template (division_count is a read-only property)
    return render_template(
        "admin/org_units/list.html",
        org_units=org_units,
        div_counts=div_counts,
        user_counts=user_counts,
    )


@admin_bp.route("/org-units/add", methods=["GET", "POST"])
@login_required
@university_admin_required
def add_org_unit():
    """Thêm Khoa/Phòng ban"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        unit_type = request.form.get("unit_type", "faculty").strip()
        description = request.form.get("description", "").strip()
        is_active = request.form.get("is_active") == "on"

        errors = []
        if not name:
            errors.append("Tên Khoa/Phòng ban không được để trống.")
        if unit_type not in ("faculty", "office"):
            errors.append("Loại đơn vị không hợp lệ (faculty/office).")

        if OrganizationUnit.query.filter_by(name=name).first():
            errors.append("Tên Khoa/Phòng ban đã tồn tại.")
        if code and OrganizationUnit.query.filter_by(code=code).first():
            errors.append("Mã đơn vị đã tồn tại.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "admin/org_units/form.html",
                action="add",
                org_unit=None,
                form_data={
                    "name": name,
                    "code": code,
                    "unit_type": unit_type,
                    "description": description,
                    "is_active": is_active,
                },
            )

        ou = OrganizationUnit(
            name=name,
            code=code or None,
            unit_type=unit_type,
            description=description or None,
            is_active=is_active,
        )
        db.session.add(ou)
        db.session.commit()
        flash(f"Đã thêm đơn vị: {name}", "success")
        return redirect(url_for("admin.manage_org_units"))

    return render_template(
        "admin/org_units/form.html", action="add", org_unit=None, form_data=None
    )


@admin_bp.route("/org-units/<int:org_unit_id>/edit", methods=["GET", "POST"])
@login_required
@university_admin_required
def edit_org_unit(org_unit_id):
    """Sửa Khoa/Phòng ban"""
    from sqlalchemy import func

    ou = OrganizationUnit.query.get_or_404(org_unit_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        unit_type = request.form.get("unit_type", "faculty").strip()
        description = request.form.get("description", "").strip()
        is_active = request.form.get("is_active") == "on"

        errors = []
        if not name:
            errors.append("Tên Khoa/Phòng ban không được để trống.")
        if unit_type not in ("faculty", "office"):
            errors.append("Loại đơn vị không hợp lệ (faculty/office).")

        existing = OrganizationUnit.query.filter(
            OrganizationUnit.name == name, OrganizationUnit.id != ou.id
        ).first()
        if existing:
            errors.append("Tên Khoa/Phòng ban đã tồn tại.")

        if code:
            existing = OrganizationUnit.query.filter(
                OrganizationUnit.code == code, OrganizationUnit.id != ou.id
            ).first()
            if existing:
                errors.append("Mã đơn vị đã tồn tại.")

        # Safety: do not allow switching faculty->office while divisions/users with divisions exist
        if ou.unit_type == "faculty" and unit_type == "office":
            active_divs = Division.query.filter_by(
                organization_unit_id=ou.id, is_active=True
            ).count()
            users_with_div = User.query.filter(
                User.organization_unit_id == ou.id, User.division_id.isnot(None)
            ).count()
            if active_divs > 0 or users_with_div > 0:
                errors.append(
                    "Không thể đổi loại sang 'office' khi đơn vị vẫn còn Bộ môn hoạt động hoặc còn người dùng đang gán Bộ môn. "
                    "Hãy tắt Bộ môn hoặc chuyển người dùng trước."
                )

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "admin/org_units/form.html",
                action="edit",
                org_unit=ou,
                form_data={
                    "name": name,
                    "code": code,
                    "unit_type": unit_type,
                    "description": description,
                    "is_active": is_active,
                },
            )

        ou.name = name
        ou.code = code or None
        ou.unit_type = unit_type
        ou.description = description or None
        ou.is_active = is_active
        db.session.commit()
        flash(f"Đã cập nhật đơn vị: {name}", "success")
        return redirect(url_for("admin.manage_org_units"))

    return render_template(
        "admin/org_units/form.html", action="edit", org_unit=ou, form_data=None
    )


@admin_bp.route("/org-units/<int:org_unit_id>/delete", methods=["POST"])
@login_required
@university_admin_required
def delete_org_unit(org_unit_id):
    """Xóa Khoa/Phòng ban (chỉ cho phép khi không có Division/User)"""
    ou = OrganizationUnit.query.get_or_404(org_unit_id)

    div_count = Division.query.filter_by(organization_unit_id=ou.id).count()
    user_count = User.query.filter_by(organization_unit_id=ou.id).count()
    if div_count > 0 or user_count > 0:
        flash(
            f"Không thể xóa đơn vị khi còn {div_count} Bộ môn và {user_count} người dùng. "
            "Hãy chuyển dữ liệu hoặc tắt (is_active) thay vì xóa.",
            "error",
        )
        return redirect(url_for("admin.manage_org_units"))

    name = ou.name
    db.session.delete(ou)
    db.session.commit()
    flash(f"Đã xóa đơn vị: {name}", "success")
    return redirect(url_for("admin.manage_org_units"))


@admin_bp.route("/divisions")
@login_required
@faculty_admin_required
def manage_divisions():
    """Quản lý Bộ môn (Division)"""
    from sqlalchemy import func

    org_units, scoped_divisions, _scoped_users, _ = build_scope_filter_data(
        current_user
    )
    allowed_org_unit_ids = {ou.id for ou in org_units}
    org_unit_id = request.args.get("org_unit_id", type=int)

    if org_unit_id and org_unit_id not in allowed_org_unit_ids:
        org_unit_id = None

    divisions = scoped_divisions
    if org_unit_id:
        divisions = [d for d in divisions if d.organization_unit_id == org_unit_id]
    divisions = sorted(divisions, key=lambda d: (d.organization_unit_id, d.name))

    user_counts = dict(
        db.session.query(User.division_id, func.count(User.id))
        .filter(User.division_id.isnot(None))
        .group_by(User.division_id)
        .all()
    )
    for d in divisions:
        d.user_count = user_counts.get(d.id, 0)

    return render_template(
        "admin/divisions/list.html",
        divisions=divisions,
        org_units=org_units,
        selected_org_unit_id=org_unit_id,
    )


@admin_bp.route("/divisions/add", methods=["GET", "POST"])
@login_required
@faculty_admin_required
def add_division():
    """Thêm Bộ môn"""
    org_units, _scoped_divisions, _scoped_users, _ = build_scope_filter_data(
        current_user
    )
    allowed_org_unit_ids = {ou.id for ou in org_units}

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        organization_unit_id = request.form.get("organization_unit_id", type=int)
        description = request.form.get("description", "").strip()
        is_active = request.form.get("is_active") == "on"

        errors = []
        if not name:
            errors.append("Tên Bộ môn không được để trống.")
        if not organization_unit_id:
            errors.append("Vui lòng chọn Khoa.")
        elif organization_unit_id not in allowed_org_unit_ids:
            errors.append("Khoa không thuộc phạm vi quản lý của bạn.")
        else:
            ou = OrganizationUnit.query.get(organization_unit_id)
            if not ou:
                errors.append("Khoa không hợp lệ.")
            elif ou.unit_type != "faculty":
                errors.append("Chỉ có thể tạo Bộ môn cho đơn vị loại 'faculty' (Khoa).")

        if organization_unit_id and code:
            existing = Division.query.filter_by(
                code=code, organization_unit_id=organization_unit_id
            ).first()
            if existing:
                errors.append("Mã Bộ môn đã tồn tại trong Khoa này.")

        if organization_unit_id and name:
            existing = Division.query.filter_by(
                name=name, organization_unit_id=organization_unit_id
            ).first()
            if existing:
                errors.append("Tên Bộ môn đã tồn tại trong Khoa này.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "admin/divisions/form.html",
                action="add",
                division=None,
                org_units=org_units,
                form_data={
                    "name": name,
                    "code": code,
                    "organization_unit_id": organization_unit_id,
                    "description": description,
                    "is_active": is_active,
                },
            )

        div = Division(
            name=name,
            code=code or None,
            organization_unit_id=organization_unit_id,
            description=description or None,
            is_active=is_active,
        )
        db.session.add(div)
        db.session.commit()
        flash(f"Đã thêm Bộ môn: {name}", "success")
        return redirect(url_for("admin.manage_divisions"))

    return render_template(
        "admin/divisions/form.html",
        action="add",
        division=None,
        org_units=org_units,
        form_data=None,
    )


@admin_bp.route("/divisions/<int:division_id>/edit", methods=["GET", "POST"])
@login_required
@faculty_admin_required
def edit_division(division_id):
    """Sửa Bộ môn"""
    div = Division.query.get_or_404(division_id)
    org_units, _scoped_divisions, _scoped_users, _ = build_scope_filter_data(
        current_user
    )
    allowed_org_unit_ids = {ou.id for ou in org_units}

    if div.organization_unit_id not in allowed_org_unit_ids:
        flash("Bộ môn này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.manage_divisions"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        organization_unit_id = request.form.get("organization_unit_id", type=int)
        description = request.form.get("description", "").strip()
        is_active = request.form.get("is_active") == "on"

        errors = []
        if not name:
            errors.append("Tên Bộ môn không được để trống.")
        if not organization_unit_id:
            errors.append("Vui lòng chọn Khoa.")
        elif organization_unit_id not in allowed_org_unit_ids:
            errors.append("Khoa không thuộc phạm vi quản lý của bạn.")
        else:
            ou = OrganizationUnit.query.get(organization_unit_id)
            if not ou:
                errors.append("Khoa không hợp lệ.")
            elif ou.unit_type != "faculty":
                errors.append("Chỉ có thể gán Bộ môn cho đơn vị loại 'faculty' (Khoa).")

        # Prevent moving division to another org if users are assigned
        if organization_unit_id and organization_unit_id != div.organization_unit_id:
            users_cnt = User.query.filter_by(division_id=div.id).count()
            if users_cnt > 0:
                errors.append(
                    "Không thể chuyển Bộ môn sang Khoa khác khi vẫn còn người dùng đang gán Bộ môn này."
                )

        if organization_unit_id and code:
            existing = Division.query.filter(
                Division.code == code,
                Division.organization_unit_id == organization_unit_id,
                Division.id != div.id,
            ).first()
            if existing:
                errors.append("Mã Bộ môn đã tồn tại trong Khoa này.")

        if organization_unit_id and name:
            existing = Division.query.filter(
                Division.name == name,
                Division.organization_unit_id == organization_unit_id,
                Division.id != div.id,
            ).first()
            if existing:
                errors.append("Tên Bộ môn đã tồn tại trong Khoa này.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "admin/divisions/form.html",
                action="edit",
                division=div,
                org_units=org_units,
                form_data={
                    "name": name,
                    "code": code,
                    "organization_unit_id": organization_unit_id,
                    "description": description,
                    "is_active": is_active,
                },
            )

        div.name = name
        div.code = code or None
        div.organization_unit_id = organization_unit_id
        div.description = description or None
        div.is_active = is_active
        db.session.commit()
        flash(f"Đã cập nhật Bộ môn: {name}", "success")
        return redirect(url_for("admin.manage_divisions"))

    return render_template(
        "admin/divisions/form.html",
        action="edit",
        division=div,
        org_units=org_units,
        form_data=None,
    )


@admin_bp.route("/divisions/<int:division_id>/delete", methods=["POST"])
@login_required
@faculty_admin_required
def delete_division(division_id):
    """Xóa Bộ môn (chỉ cho phép khi không có User gán)"""
    div = Division.query.get_or_404(division_id)
    org_units, _scoped_divisions, _scoped_users, _ = build_scope_filter_data(
        current_user
    )
    allowed_org_unit_ids = {ou.id for ou in org_units}
    if div.organization_unit_id not in allowed_org_unit_ids:
        flash("Bộ môn này nằm ngoài phạm vi bạn đang làm việc.", "error")
        return redirect(url_for("admin.manage_divisions"))

    user_count = User.query.filter_by(division_id=div.id).count()
    if user_count > 0:
        flash(
            f"Không thể xóa Bộ môn có {user_count} người dùng. Hãy chuyển họ sang Bộ môn khác trước.",
            "error",
        )
        return redirect(url_for("admin.manage_divisions"))

    name = div.name
    db.session.delete(div)
    db.session.commit()
    flash(f"Đã xóa Bộ môn: {name}", "success")
    return redirect(url_for("admin.manage_divisions"))


def manage_departments():
    """Quản lý bộ môn"""
    departments = Department.query.order_by(Department.name).all()
    return render_template("admin/departments/list.html", departments=departments)


@admin_bp.route("/departments/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_department():
    """Thêm bộ môn mới"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Tên bộ môn không được để trống.", "error")
            return render_template(
                "admin/departments/form.html", action="add", department=None
            )

        if Department.query.filter_by(name=name).first():
            flash("Tên bộ môn đã tồn tại.", "error")
            return render_template(
                "admin/departments/form.html", action="add", department=None
            )

        if code and Department.query.filter_by(code=code).first():
            flash("Mã bộ môn đã tồn tại.", "error")
            return render_template(
                "admin/departments/form.html", action="add", department=None
            )

        dept = Department(
            name=name,
            code=code or None,
            description=description or None,
        )
        db.session.add(dept)
        db.session.commit()

        flash(f"Đã thêm bộ môn: {name}", "success")
        return redirect(url_for("admin.manage_departments"))

    return render_template("admin/departments/form.html", action="add", department=None)


@admin_bp.route("/departments/<int:dept_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_department(dept_id):
    """Sửa bộ môn"""
    dept = Department.query.get_or_404(dept_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        description = request.form.get("description", "").strip()
        is_active = request.form.get("is_active") == "on"

        if not name:
            flash("Tên bộ môn không được để trống.", "error")
            return render_template(
                "admin/departments/form.html", action="edit", department=dept
            )

        # Kiểm tra trùng tên
        existing = Department.query.filter(
            Department.name == name, Department.id != dept.id
        ).first()
        if existing:
            flash("Tên bộ môn đã tồn tại.", "error")
            return render_template(
                "admin/departments/form.html", action="edit", department=dept
            )

        # Kiểm tra trùng mã
        if code:
            existing = Department.query.filter(
                Department.code == code, Department.id != dept.id
            ).first()
            if existing:
                flash("Mã bộ môn đã tồn tại.", "error")
                return render_template(
                    "admin/departments/form.html", action="edit", department=dept
                )

        dept.name = name
        dept.code = code or None
        dept.description = description or None
        dept.is_active = is_active
        db.session.commit()

        flash(f"Đã cập nhật bộ môn: {name}", "success")
        return redirect(url_for("admin.manage_departments"))

    return render_template(
        "admin/departments/form.html", action="edit", department=dept
    )


@admin_bp.route("/departments/<int:dept_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_department(dept_id):
    """Xóa bộ môn"""
    dept = Department.query.get_or_404(dept_id)

    # Kiểm tra còn thành viên không
    member_count = User.query.filter_by(department_id=dept.id).count()
    if member_count > 0:
        flash(
            f"Không thể xóa bộ môn có {member_count} thành viên. Hãy chuyển họ sang bộ môn khác trước.",
            "error",
        )
        return redirect(url_for("admin.manage_departments"))

    name = dept.name
    db.session.delete(dept)
    db.session.commit()

    flash(f"Đã xóa bộ môn: {name}", "success")
    return redirect(url_for("admin.manage_departments"))


@admin_bp.route("/departments/<int:dept_id>/members")
@login_required
@admin_required
def department_members(dept_id):
    """Xem thành viên và báo cáo của bộ môn"""
    dept = Department.query.get_or_404(dept_id)
    year = request.args.get("year", type=int, default=datetime.now().year)

    members = (
        User.query.filter_by(department_id=dept.id, is_active=True)
        .order_by(User.full_name)
        .all()
    )

    member_data = []
    for user in members:
        pubs = Publication.query.filter_by(
            user_id=user.id, is_approved=True, year=year
        ).all()
        projects = (
            Project.query.filter_by(user_id=user.id, is_approved=True)
            .filter(Project.start_year <= year, Project.end_year >= year)
            .all()
        )
        activities = OtherActivity.query.filter_by(
            user_id=user.id, is_approved=True, year=year
        ).all()

        summary = calculate_total_research_hours(pubs, projects, activities, year=year)

        # Q stats
        q_stats = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
        for pub in pubs:
            if pub.quartile in q_stats:
                q_stats[pub.quartile] += 1

        member_data.append(
            {
                "user": user,
                "pub_count": len(pubs),
                "project_count": len(projects),
                "activity_count": len(activities),
                "total_hours": summary["total_hours"],
                "q_stats": q_stats,
            }
        )

    # Tổng hợp bộ môn
    dept_total = {
        "member_count": len(members),
        "pub_count": sum(m["pub_count"] for m in member_data),
        "project_count": sum(m["project_count"] for m in member_data),
        "total_hours": sum(m["total_hours"] for m in member_data),
        "q_stats": {
            q: sum(m["q_stats"][q] for m in member_data)
            for q in ["Q1", "Q2", "Q3", "Q4"]
        },
    }

    # Danh sách năm
    years = set()
    for pub in Publication.query.with_entities(Publication.year).distinct():
        years.add(pub.year)
    years.add(datetime.now().year)
    years = sorted(years, reverse=True)

    return render_template(
        "admin/departments/members.html",
        department=dept,
        member_data=member_data,
        dept_total=dept_total,
        selected_year=year,
        years=years,
    )
