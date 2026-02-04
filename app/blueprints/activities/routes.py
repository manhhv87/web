"""
Other Activities CRUD routes - Hoạt động KHCN khác (Bảng 2, Mục 3).
VNU-UET Research Hours Web Application.

Bao gồm:
- 3.1a: Hướng dẫn SV NCKH cấp trường (75 giờ/nhóm)
- 3.1b: Hướng dẫn SV NCKH cấp khoa (30 giờ/nhóm)
- 3.2: Huấn luyện đội tuyển SV (75 giờ/đội)
- 3.3: Sản phẩm KHCN triển lãm (45 giờ/sản phẩm)

Lưu ý: Tối đa 250 giờ/năm cho toàn bộ mục 3.
"""

from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.db_models import db, OtherActivity
from app.hours_calculator import (
    calculate_other_activity_hours_from_model,
    calculate_yearly_other_activities_total,
    OTHER_ACTIVITY_TYPE_CHOICES,
    DEFAULT_CONFIG,
)

activity_bp = Blueprint("activities", __name__)


@activity_bp.route("/")
@login_required
def list_activities():
    """Danh sách hoạt động KHCN khác"""
    # Filter params
    year = request.args.get("year", type=int)
    activity_type = request.args.get("type")
    status = request.args.get("status")

    query = OtherActivity.query.filter_by(user_id=current_user.id)

    if year:
        query = query.filter_by(year=year)

    if activity_type:
        query = query.filter_by(activity_type=activity_type)

    if status:
        if status == "approved":
            query = query.filter_by(approval_status="approved")
        elif status == "returned":
            query = query.filter_by(approval_status="returned")
        elif status == "pending":
            query = query.filter(
                OtherActivity.approval_status.in_(
                    ["pending", "department_approved", "faculty_approved"]
                )
            )

    activities = query.order_by(
        OtherActivity.year.desc(), OtherActivity.created_at.desc()
    ).all()

    # Tính giờ cho mỗi hoạt động
    for act in activities:
        act.hours = calculate_other_activity_hours_from_model(act)

    # Get unique years for filter
    years_query = (
        db.session.query(OtherActivity.year)
        .filter_by(user_id=current_user.id)
        .distinct()
        .order_by(OtherActivity.year.desc())
    )
    years = [y[0] for y in years_query.all()]

    # Tổng hợp theo năm được chọn (hoặc tất cả)
    all_user_activities = OtherActivity.query.filter_by(user_id=current_user.id).all()

    yearly_summaries = []
    yearly_summary_map = {}
    for y in years:
        summary = calculate_yearly_other_activities_total(all_user_activities, y)
        yearly_summaries.append(summary)
        yearly_summary_map[y] = summary

    # Tổng giờ hiển thị
    if year:
        current_summary = calculate_yearly_other_activities_total(
            all_user_activities, year
        )
    else:
        current_summary = None

    return render_template(
        "activities/list.html",
        activities=activities,
        years=years,
        selected_year=year,
        selected_type=activity_type,
        selected_status=status,
        type_choices=OTHER_ACTIVITY_TYPE_CHOICES,
        yearly_summaries=yearly_summaries,
        yearly_summary_map=yearly_summary_map,
        current_summary=current_summary,
        max_hours_per_year=DEFAULT_CONFIG.other_activity_max_hours_per_year,
    )


@activity_bp.route("/add", methods=["GET", "POST"])
@login_required
def add_activity():
    """Thêm hoạt động KHCN mới"""
    if request.method == "POST":
        act = _create_activity_from_form(request.form)

        if act:
            # Xác định action: save_draft hoặc submit
            action = request.form.get("action", "save_draft")
            if action == "submit":
                act.approval_status = "pending"
                msg = f"Đã gửi hoạt động để duyệt: {act.title[:50]}..."
            else:
                act.approval_status = "draft"
                msg = f"Đã lưu nháp: {act.title[:50]}..."

            db.session.add(act)
            db.session.commit()
            flash(msg, "success")
            return redirect(url_for("activities.list_activities"))

    return render_template(
        "activities/form.html",
        action="add",
        activity=None,
        type_choices=OTHER_ACTIVITY_TYPE_CHOICES,
        current_year=datetime.now().year,
    )


@activity_bp.route("/edit/<int:act_id>", methods=["GET", "POST"])
@login_required
def edit_activity(act_id):
    """Sửa hoạt động KHCN"""
    act = OtherActivity.query.filter_by(
        id=act_id, user_id=current_user.id
    ).first_or_404()

    # Kiem tra quyen sua: chi cho phep khi chua duoc duyet
    if not act.can_edit:
        flash(
            "Hoạt động đã được duyệt, không thể sửa. Vui lòng liên hệ admin.", "error"
        )
        return redirect(url_for("activities.list_activities"))

    if request.method == "POST":
        error = _update_activity_from_form(act, request.form)
        if error:
            flash(error, "error")
            return render_template(
                "activities/form.html",
                action="edit",
                activity=act,
                type_choices=OTHER_ACTIVITY_TYPE_CHOICES,
                current_year=datetime.now().year,
            )

        # Xác định action: save_draft hoặc submit
        action = request.form.get("action", "save_draft")
        if action == "submit":
            act.approval_status = "pending"
            act.rejection_reason = None
            act.returned_at = None
            msg = f"Đã gửi hoạt động để duyệt: {act.title[:50]}..."
        else:
            if act.approval_status != "returned":
                act.approval_status = "draft"
            msg = f"Đã lưu nháp: {act.title[:50]}..."

        db.session.commit()
        flash(msg, "success")
        return redirect(url_for("activities.list_activities"))

    return render_template(
        "activities/form.html",
        action="edit",
        activity=act,
        type_choices=OTHER_ACTIVITY_TYPE_CHOICES,
        current_year=datetime.now().year,
    )


@activity_bp.route("/delete/<int:act_id>", methods=["POST"])
@login_required
def delete_activity(act_id):
    """Xóa hoạt động KHCN"""
    act = OtherActivity.query.filter_by(
        id=act_id, user_id=current_user.id
    ).first_or_404()

    # Kiem tra quyen xoa: chi cho phep khi chua duoc duyet
    if not act.can_delete:
        flash(
            "Hoạt động không thể xóa ở trạng thái hiện tại. Nếu cần xóa, hãy liên hệ admin.",
            "error",
        )
        return redirect(url_for("activities.list_activities"))

    title = act.title[:50]
    db.session.delete(act)
    db.session.commit()
    flash(f"Đã xóa hoạt động: {title}...", "success")
    return redirect(url_for("activities.list_activities"))


@activity_bp.route("/view/<int:act_id>")
@login_required
def view_activity(act_id):
    """Xem chi tiết hoạt động"""
    act = OtherActivity.query.filter_by(
        id=act_id, user_id=current_user.id
    ).first_or_404()

    # Tính giờ
    act.hours = calculate_other_activity_hours_from_model(act)

    # Kiểm tra giới hạn năm
    all_user_activities = OtherActivity.query.filter_by(user_id=current_user.id).all()
    year_summary = calculate_yearly_other_activities_total(
        all_user_activities, act.year
    )

    return render_template(
        "activities/view.html",
        activity=act,
        year_summary=year_summary,
        max_hours_per_year=DEFAULT_CONFIG.other_activity_max_hours_per_year,
    )


def _validate_activity_form(form) -> str | None:
    """Validate form hoạt động. Trả về thông báo lỗi hoặc None."""
    activity_type = form.get("activity_type", "")
    if not activity_type:
        return "Vui lòng chọn loại hoạt động."

    title = form.get("title", "").strip()
    # Title không bắt buộc cho: student_research_university, student_research_faculty,
    # team_training, exhibition_product
    title_optional_types = (
        "student_research_university",
        "student_research_faculty",
        "team_training",
        "exhibition_product",
    )
    if activity_type not in title_optional_types and not title:
        return "Tên hoạt động không được để trống."

    year = form.get("year", type=int)
    if not year or year < 2000 or year > datetime.now().year + 1:
        return "Năm không hợp lệ."

    quantity = form.get("quantity", 0, type=int)
    if not quantity or quantity < 1:
        return "Số lượng phải >= 1."

    # Tên cuộc thi bắt buộc cho team_training
    if activity_type == "team_training":
        event_name = form.get("event_name", "").strip()
        if not event_name:
            return "Vui lòng nhập tên cuộc thi."

    # Tên hội chợ/triển lãm bắt buộc cho exhibition_product
    if activity_type == "exhibition_product":
        event_name = form.get("event_name", "").strip()
        if not event_name:
            return "Vui lòng nhập tên hội chợ/triển lãm/cuộc thi."

    return None


def _create_activity_from_form(form) -> OtherActivity | None:
    """Tạo OtherActivity từ form data. Trả về None nếu có lỗi."""
    error = _validate_activity_form(form)
    if error:
        flash(error, "error")
        return None

    act = OtherActivity(
        user_id=current_user.id,
        title=form.get("title", "").strip(),
        activity_type=form.get("activity_type"),
        year=form.get("year", type=int),
        quantity=form.get("quantity", 1, type=int) or 1,
        student_names=form.get("student_names", "").strip() or None,
        event_name=form.get("event_name", "").strip() or None,
        achievement=form.get("achievement", "").strip() or None,
        notes=form.get("notes", "").strip() or None,
    )

    # Tính giờ
    act.hours = calculate_other_activity_hours_from_model(act)

    return act


def _update_activity_from_form(act: OtherActivity, form) -> str | None:
    """Cập nhật OtherActivity từ form data. Trả về lỗi hoặc None."""
    error = _validate_activity_form(form)
    if error:
        return error

    act.title = form.get("title", "").strip()
    act.activity_type = form.get("activity_type")
    act.year = form.get("year", type=int)
    act.quantity = form.get("quantity", 1, type=int) or 1
    act.student_names = form.get("student_names", "").strip() or None
    act.event_name = form.get("event_name", "").strip() or None
    act.achievement = form.get("achievement", "").strip() or None
    act.notes = form.get("notes", "").strip() or None

    # Tính lại giờ
    act.hours = calculate_other_activity_hours_from_model(act)

    return None
