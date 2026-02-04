"""
Projects CRUD routes - Đề tài, dự án KHCN (Bảng 2, Mục 1-2).
VNU-UET Research Hours Web Application.
"""

from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.db_models import db, Project
from app.hours_calculator import (
    calculate_project_hours_from_model,
    calculate_project_hours_per_year,
    PROJECT_LEVEL_CHOICES,
    PROJECT_ROLE_CHOICES,
    PROJECT_STATUS_CHOICES,
)

project_bp = Blueprint("projects", __name__)


@project_bp.route("/")
@login_required
def list_projects():
    """Danh sách đề tài/dự án của người dùng"""
    # Filter params
    year = request.args.get("year", type=int)
    level = request.args.get("level")
    progress_status = request.args.get("progress")
    approval_status = request.args.get("approval_status")

    query = Project.query.filter_by(user_id=current_user.id)

    if year:
        query = query.filter(Project.start_year <= year, Project.end_year >= year)

    if level:
        query = query.filter_by(project_level=level)

    if progress_status:
        query = query.filter_by(status=progress_status)

    if approval_status:
        if approval_status == "approved":
            query = query.filter_by(approval_status="approved")
        elif approval_status == "returned":
            query = query.filter_by(approval_status="returned")
        elif approval_status == "pending":
            query = query.filter(
                Project.approval_status.in_(
                    ["pending", "department_approved", "faculty_approved"]
                )
            )

    projects = query.order_by(
        Project.start_year.desc(), Project.created_at.desc()
    ).all()

    # Tính giờ cho mỗi đề tài
    for proj in projects:
        hours = calculate_project_hours_from_model(proj)
        proj.total_hours = hours["total_hours"]
        proj.user_hours = hours["user_hours"]
        proj.user_hours_per_year = calculate_project_hours_per_year(proj)

    # Get unique years for filter
    all_projects = Project.query.filter_by(user_id=current_user.id).all()
    years = set()
    for p in all_projects:
        for y in range(p.start_year, p.end_year + 1):
            years.add(y)
    years = sorted(years, reverse=True)

    # Tổng hợp
    total_hours = sum(p.user_hours for p in projects)

    return render_template(
        "projects/list.html",
        projects=projects,
        years=years,
        selected_year=year,
        selected_level=level,
        selected_progress=progress_status,
        selected_approval=approval_status,
        level_choices=PROJECT_LEVEL_CHOICES,
        progress_choices=PROJECT_STATUS_CHOICES,
        total_hours=total_hours,
    )


@project_bp.route("/add", methods=["GET", "POST"])
@login_required
def add_project():
    """Th?m ?? t?i/d? ?n m?i"""
    if request.method == "POST":
        proj = _create_project_from_form(request.form)

        if proj:
            # X?c ??nh action: save_draft ho?c submit
            action = request.form.get("action", "save_draft")
            if action == "submit":
                proj.approval_status = "pending"
                msg = f"?? g?i ?? t?i ?? duy?t: {proj.title[:50]}..."
            else:
                proj.approval_status = "draft"
                msg = f"?? l?u nh?p: {proj.title[:50]}..."

            db.session.add(proj)
            db.session.commit()
            flash(msg, "success")
            return redirect(url_for("projects.list_projects"))

    return render_template(
        "projects/form.html",
        action="add",
        project=None,
        level_choices=PROJECT_LEVEL_CHOICES,
        role_choices=PROJECT_ROLE_CHOICES,
        status_choices=PROJECT_STATUS_CHOICES,
        current_year=datetime.now().year,
    )


@project_bp.route("/edit/<int:proj_id>", methods=["GET", "POST"])
@login_required
def edit_project(proj_id):
    """Sửa đề tài/dự án"""
    proj = Project.query.filter_by(id=proj_id, user_id=current_user.id).first_or_404()

    # Kiểm tra quyền sửa: chỉ cho phép khi chưa được duyệt
    if not proj.can_edit:
        flash(
            "Đề tài không thể sửa ở trạng thái hiện tại. Nếu cần chỉnh sửa, hãy liên hệ admin hoặc đợi bị trả lại.",
            "error",
        )
        return redirect(url_for("projects.list_projects"))

    if request.method == "POST":
        error = _update_project_from_form(proj, request.form)
        if error:
            flash(error, "error")
            return render_template(
                "projects/form.html",
                action="edit",
                project=proj,
                level_choices=PROJECT_LEVEL_CHOICES,
                role_choices=PROJECT_ROLE_CHOICES,
                status_choices=PROJECT_STATUS_CHOICES,
                current_year=datetime.now().year,
            )

        # Xác định action: save_draft hoặc submit
        action = request.form.get("action", "save_draft")
        if action == "submit":
            proj.approval_status = "pending"
            proj.rejection_reason = None
            proj.returned_at = None
            msg = f"Đã gửi đề tài để duyệt: {proj.title[:50]}..."
        else:
            if proj.approval_status != "returned":
                proj.approval_status = "draft"
            msg = f"Đã lưu nháp: {proj.title[:50]}..."

        db.session.commit()
        flash(msg, "success")
        return redirect(url_for("projects.list_projects"))

    return render_template(
        "projects/form.html",
        action="edit",
        project=proj,
        level_choices=PROJECT_LEVEL_CHOICES,
        role_choices=PROJECT_ROLE_CHOICES,
        status_choices=PROJECT_STATUS_CHOICES,
        current_year=datetime.now().year,
    )


@project_bp.route("/delete/<int:proj_id>", methods=["POST"])
@login_required
def delete_project(proj_id):
    """Xóa đề tài/dự án"""
    proj = Project.query.filter_by(id=proj_id, user_id=current_user.id).first_or_404()

    # Kiểm tra quyền xoá: chỉ cho phép khi đang ở trạng thái draft/returned
    if not proj.can_delete:
        flash(
            "Đề tài không thể xóa ở trạng thái hiện tại. Nếu cần xóa, hãy liên hệ admin.",
            "error",
        )
        return redirect(url_for("projects.list_projects"))

    title = proj.title[:50]
    db.session.delete(proj)
    db.session.commit()
    flash(f"Đã xóa đề tài: {title}...", "success")
    return redirect(url_for("projects.list_projects"))


@project_bp.route("/view/<int:proj_id>")
@login_required
def view_project(proj_id):
    """Xem chi tiết đề tài/dự án"""
    proj = Project.query.filter_by(id=proj_id, user_id=current_user.id).first_or_404()

    # Tính giờ với chi tiết phân chia
    hours_detail = calculate_project_hours_from_model(proj)
    proj.total_hours = hours_detail["total_hours"]
    proj.user_hours = hours_detail["user_hours"]
    proj.user_hours_per_year = calculate_project_hours_per_year(proj)
    span_years = max(1, proj.end_year - proj.start_year + 1)

    return render_template(
        "projects/view.html",
        project=proj,
        hours_detail=hours_detail,
        span_years=span_years,
    )


def _validate_project_form(form) -> str | None:
    """Validate form đề tài. Trả về thông báo lỗi hoặc None."""
    title = form.get("title", "").strip()
    if not title:
        return "Tên đề tài không được để trống."

    project_code = form.get("project_code", "").strip()
    if not project_code:
        return "Mã đề tài không được để trống."

    project_level = form.get("project_level", "")
    if not project_level:
        return "Vui lòng chọn cấp đề tài."

    start_year = form.get("start_year", type=int)
    end_year = form.get("end_year", type=int)
    if not start_year or not end_year:
        return "Vui lòng nhập năm bắt đầu và năm kết thúc."
    if start_year < 1900 or end_year < 1900:
        return "Năm không hợp lệ."
    if end_year < start_year:
        return "Năm kết thúc phải >= năm bắt đầu."

    status = form.get("status", "")
    if not status:
        return "Vui lòng chọn trạng thái đề tài."

    role = form.get("role", "")
    if not role:
        return "Vui lòng chọn vai trò của bạn."

    total_members = form.get("total_members", 0, type=int)
    if not total_members or total_members < 1:
        return "Tổng số thành viên phải >= 1."

    # Đề tài hợp tác: bắt buộc giá trị tài trợ
    if project_level == "cooperation":
        funding_str = form.get("funding_amount", "").strip()
        if not funding_str:
            return "Vui lòng nhập giá trị tài trợ cho đề tài hợp tác."
        try:
            val = float(funding_str)
            if val <= 0:
                return "Giá trị tài trợ phải > 0."
        except ValueError:
            return "Giá trị tài trợ không hợp lệ."

    return None


def _create_project_from_form(form) -> Project | None:
    """Tạo Project từ form data. Trả về None nếu có lỗi."""
    error = _validate_project_form(form)
    if error:
        flash(error, "error")
        return None

    proj = Project(
        user_id=current_user.id,
        title=form.get("title", "").strip(),
        project_code=form.get("project_code", "").strip() or None,
        project_level=form.get("project_level"),
        start_year=form.get("start_year", type=int),
        end_year=form.get("end_year", type=int),
        status=form.get("status", "ongoing"),
        role=form.get("role", "member"),
        total_members=form.get("total_members", 1, type=int) or 1,
        funding_agency=form.get("funding_agency", "").strip() or None,
        description=form.get("description", "").strip() or None,
        notes=form.get("notes", "").strip() or None,
    )
    proj.duration_years = max(1, proj.end_year - proj.start_year)

    # Giá trị tài trợ và số năm thực hiện (cho đề tài hợp tác)
    if proj.project_level == "cooperation":
        funding_str = form.get("funding_amount", "").strip()
        if funding_str:
            try:
                proj.funding_amount = float(funding_str)
            except ValueError:
                proj.funding_amount = 0.0
        # Cho phép nhập duration_years riêng (dùng trong công thức)
        manual_duration = form.get("duration_years", type=int)
        if manual_duration and manual_duration >= 1:
            proj.duration_years = manual_duration
    else:
        proj.funding_amount = 0.0

    # Tính giờ
    hours = calculate_project_hours_from_model(proj)
    proj.total_hours = hours["total_hours"]
    proj.user_hours = hours["user_hours"]

    return proj


def _update_project_from_form(proj: Project, form) -> str | None:
    """Cập nhật Project từ form data. Trả về lỗi hoặc None."""
    error = _validate_project_form(form)
    if error:
        return error

    proj.title = form.get("title", "").strip()
    proj.project_code = form.get("project_code", "").strip() or None
    proj.project_level = form.get("project_level")
    proj.start_year = form.get("start_year", type=int)
    proj.end_year = form.get("end_year", type=int)
    proj.duration_years = max(1, proj.end_year - proj.start_year)
    proj.status = form.get("status", "ongoing")
    proj.role = form.get("role", "member")
    proj.total_members = form.get("total_members", 1, type=int) or 1
    proj.funding_agency = form.get("funding_agency", "").strip() or None
    proj.description = form.get("description", "").strip() or None
    proj.notes = form.get("notes", "").strip() or None

    # Giá trị tài trợ và số năm thực hiện (cho đề tài hợp tác)
    if proj.project_level == "cooperation":
        funding_str = form.get("funding_amount", "").strip()
        if funding_str:
            try:
                proj.funding_amount = float(funding_str)
            except ValueError:
                proj.funding_amount = 0.0
        # Cho phép nhập duration_years riêng (dùng trong công thức)
        manual_duration = form.get("duration_years", type=int)
        if manual_duration and manual_duration >= 1:
            proj.duration_years = manual_duration
    else:
        proj.funding_amount = 0.0

    # Tính lại giờ
    hours = calculate_project_hours_from_model(proj)
    proj.total_hours = hours["total_hours"]
    proj.user_hours = hours["user_hours"]

    return None
