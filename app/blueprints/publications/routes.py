"""
Publications CRUD routes for VNU-UET Research Hours Web Application.
"""

import re
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.db_models import db, Publication
from app.hours_calculator import (
    calculate_publication_hours,
    PUBLICATION_TYPE_CHOICES,
    QUARTILE_CHOICES,
    AUTHOR_ROLE_CHOICES,
    PATENT_STAGE_CHOICES,
)

pub_bp = Blueprint("publications", __name__)


@pub_bp.route("/")
@login_required
def list_publications():
    """Danh sách ấn phẩm của user"""
    # Filter params
    year = request.args.get("year", type=int)
    pub_type = request.args.get("type")
    status = request.args.get("status")

    query = Publication.query.filter_by(user_id=current_user.id)

    if year:
        query = query.filter_by(year=year)

    if pub_type:
        query = query.filter_by(publication_type=pub_type)

    if status:
        if status == "approved":
            query = query.filter_by(approval_status="approved")
        elif status == "returned":
            query = query.filter_by(approval_status="returned")
        elif status == "pending":
            query = query.filter(
                Publication.approval_status.in_(
                    ["pending", "department_approved", "faculty_approved"]
                )
            )

    publications = query.order_by(
        Publication.year.desc(), Publication.created_at.desc()
    ).all()

    # Get unique years for filter
    years_query = (
        db.session.query(Publication.year)
        .filter_by(user_id=current_user.id)
        .distinct()
        .order_by(Publication.year.desc())
    )
    years = [y[0] for y in years_query.all()]

    return render_template(
        "publications/list.html",
        publications=publications,
        years=years,
        selected_year=year,
        selected_type=pub_type,
        selected_status=status,
        pub_type_choices=PUBLICATION_TYPE_CHOICES,
    )


@pub_bp.route("/add", methods=["GET", "POST"])
@login_required
def add_publication():
    """Thêm ấn phẩm mới"""
    if request.method == "POST":
        pub = _create_publication_from_form(request.form)

        if pub:
            # Xác định action: save_draft hoặc submit
            action = request.form.get("action", "save_draft")
            if action == "submit":
                pub.approval_status = "pending"
                msg = f"Đã gửi ấn phẩm để duyệt: {pub.title[:50]}..."
            else:
                pub.approval_status = "draft"
                msg = f"Đã lưu nháp: {pub.title[:50]}..."

            db.session.add(pub)
            db.session.commit()
            flash(msg, "success")
            return redirect(url_for("publications.list_publications"))

    return render_template(
        "publications/form.html",
        action="add",
        publication=None,
        pub_type_choices=PUBLICATION_TYPE_CHOICES,
        quartile_choices=QUARTILE_CHOICES,
        author_role_choices=AUTHOR_ROLE_CHOICES,
        patent_stage_choices=PATENT_STAGE_CHOICES,
        current_year=datetime.now().year,
    )


@pub_bp.route("/edit/<int:pub_id>", methods=["GET", "POST"])
@login_required
def edit_publication(pub_id):
    """Sửa ấn phẩm"""
    pub = Publication.query.filter_by(id=pub_id, user_id=current_user.id).first_or_404()

    # Kiem tra quyen sua: chi cho phep khi chua duoc duyet
    if not pub.can_edit:
        flash(
            "Ấn phẩm không thể sửa ở trạng thái hiện tại. Nếu cần chỉnh sửa, hãy liên hệ admin hoặc đợi bị trả lại.",
            "error",
        )
        return redirect(url_for("publications.list_publications"))

    if request.method == "POST":
        error = _update_publication_from_form(pub, request.form)
        if error:
            flash(error, "error")
            return render_template(
                "publications/form.html",
                action="edit",
                publication=pub,
                pub_type_choices=PUBLICATION_TYPE_CHOICES,
                quartile_choices=QUARTILE_CHOICES,
                author_role_choices=AUTHOR_ROLE_CHOICES,
                patent_stage_choices=PATENT_STAGE_CHOICES,
                current_year=datetime.now().year,
            )

        # Xác định action: save_draft hoặc submit
        action = request.form.get("action", "save_draft")
        if action == "submit":
            pub.approval_status = "pending"
            # Reset rejection_reason nếu đang sửa item bị returned
            pub.rejection_reason = None
            pub.returned_at = None
            msg = f"Đã gửi ấn phẩm để duyệt: {pub.title[:50]}..."
        else:
            # Nếu đang ở trạng thái returned, giữ nguyên để user còn thấy lý do
            if pub.approval_status != "returned":
                pub.approval_status = "draft"
            msg = f"Đã lưu nháp: {pub.title[:50]}..."

        db.session.commit()
        flash(msg, "success")
        return redirect(url_for("publications.list_publications"))

    return render_template(
        "publications/form.html",
        action="edit",
        publication=pub,
        pub_type_choices=PUBLICATION_TYPE_CHOICES,
        quartile_choices=QUARTILE_CHOICES,
        author_role_choices=AUTHOR_ROLE_CHOICES,
        patent_stage_choices=PATENT_STAGE_CHOICES,
        current_year=datetime.now().year,
    )


@pub_bp.route("/delete/<int:pub_id>", methods=["POST"])
@login_required
def delete_publication(pub_id):
    """Xóa ấn phẩm"""
    pub = Publication.query.filter_by(id=pub_id, user_id=current_user.id).first_or_404()

    # Kiem tra quyen xoa: chi cho phep khi chua duoc duyet
    if not pub.can_delete:
        flash(
            "Ấn phẩm không thể xóa ở trạng thái hiện tại. Nếu cần xóa, hãy liên hệ admin.",
            "error",
        )
        return redirect(url_for("publications.list_publications"))

    title = pub.title[:50]
    db.session.delete(pub)
    db.session.commit()
    flash(f"Đã xóa ấn phẩm: {title}...", "success")
    return redirect(url_for("publications.list_publications"))


@pub_bp.route("/view/<int:pub_id>")
@login_required
def view_publication(pub_id):
    """Xem chi tiết ấn phẩm"""
    pub = Publication.query.filter_by(id=pub_id, user_id=current_user.id).first_or_404()
    return render_template("publications/view.html", publication=pub)


def _validate_issn(value: str) -> bool:
    """Validate ISSN format: XXXX-XXXX (8 chữ số, có hoặc không có dấu gạch ngang).

    Chấp nhận: 1234-5678, 12345678
    """
    cleaned = value.strip().replace("-", "").replace(" ", "")
    if len(cleaned) != 8:
        return False
    # 7 ký tự đầu phải là số, ký tự cuối có thể là số hoặc X
    return cleaned[:7].isdigit() and (cleaned[7].isdigit() or cleaned[7].upper() == "X")


def _validate_isbn(value: str) -> bool:
    """Validate ISBN format: ISBN-10 hoặc ISBN-13.

    Chấp nhận: 978-3-16-148410-0, 9783161484100, 0-306-40615-2, 0306406152
    """
    cleaned = value.strip().replace("-", "").replace(" ", "")
    if len(cleaned) == 10:
        # ISBN-10: 9 số + 1 check digit (số hoặc X)
        return cleaned[:9].isdigit() and (cleaned[9].isdigit() or cleaned[9].upper() == "X")
    if len(cleaned) == 13:
        # ISBN-13: 13 số
        return cleaned.isdigit()
    return False


def _validate_required_fields(form, pub_type) -> str | None:
    """Validate tất cả các trường bắt buộc. Trả về thông báo lỗi hoặc None."""
    # venue_name: not required for monograph/textbook (title = book name)
    hide_venue = (
        pub_type.startswith("monograph")
        or pub_type.startswith("textbook")
    )
    if not hide_venue and not form.get("venue_name", "").strip():
        return "Vui lòng nhập tên nơi công bố (tạp chí/hội nghị/NXB)."
    if not form.get("all_authors", "").strip():
        return "Vui lòng nhập danh sách tác giả."
    total_authors = form.get("total_authors", 0, type=int)
    if not total_authors or total_authors < 1:
        return "Tổng số tác giả phải >= 1."
    if not form.get("author_role", "").strip():
        return "Vui lòng chọn vai trò tác giả."

    # --- Tạp chí: yêu cầu ISSN ---
    if pub_type.startswith("journal_"):
        issn = form.get("issn", "").strip()
        if not issn:
            return "Vui lòng nhập ISSN cho tạp chí."
        if not _validate_issn(issn):
            return "ISSN không đúng định dạng. Vui lòng nhập đúng 8 chữ số (VD: 1234-5678)."
        if pub_type == "journal_domestic":
            dp = form.get("domestic_points", "").strip()
            if not dp:
                return "Vui lòng nhập điểm HĐGSNN cho tạp chí trong nước."
            try:
                dp_val = float(dp)
                if dp_val < 0 or dp_val > 2:
                    return "Điểm HĐGSNN phải nằm trong khoảng 0 - 2."
            except ValueError:
                return "Điểm HĐGSNN không hợp lệ."

    # --- Hội nghị: yêu cầu ISBN ---
    if pub_type.startswith("conference_"):
        isbn = form.get("isbn", "").strip()
        if not isbn:
            return "Vui lòng nhập ISBN cho kỷ yếu hội nghị."
        if not _validate_isbn(isbn):
            return "ISBN không đúng định dạng. Vui lòng nhập ISBN-10 (10 chữ số) hoặc ISBN-13 (13 chữ số). VD: 978-3-16-148410-0."

    # --- Sách: yêu cầu ISBN + NXB ---
    if pub_type.startswith("monograph") or pub_type.startswith("textbook") or pub_type.startswith("book_chapter"):
        isbn = form.get("isbn", "").strip()
        if not isbn:
            return "Vui lòng nhập ISBN cho sách."
        if not _validate_isbn(isbn):
            return "ISBN không đúng định dạng. Vui lòng nhập ISBN-10 (10 chữ số) hoặc ISBN-13 (13 chữ số). VD: 978-3-16-148410-0."
        if not form.get("publisher", "").strip():
            return "Vui lòng nhập nhà xuất bản."

    # --- Sáng chế ---
    if pub_type.startswith("patent") or pub_type == "utility_solution":
        patent_stage = form.get("patent_stage", "")
        if not patent_stage:
            return "Vui lòng chọn giai đoạn sáng chế."
        if patent_stage not in ("stage_1", "stage_2"):
            return "Giai đoạn sáng chế không hợp lệ."
        # Số bằng bắt buộc ở giai đoạn 2 (đã được cấp bằng)
        if patent_stage == "stage_2" and not form.get("patent_number", "").strip():
            return "Vui lòng nhập số bằng sáng chế/giải pháp hữu ích."

    return None


def _create_publication_from_form(form) -> Publication:
    """Tạo Publication từ form data"""
    pub_type = form.get("publication_type")

    if not pub_type:
        flash("Vui lòng chọn loại ấn phẩm.", "error")
        return None

    title = form.get("title", "").strip()
    if not title:
        flash("Tên ấn phẩm không được để trống.", "error")
        return None

    year = form.get("year", type=int)
    if not year or year < 1900 or year > datetime.now().year + 1:
        flash("Năm không hợp lệ.", "error")
        return None

    # Validate all required fields
    error = _validate_required_fields(form, pub_type)
    if error:
        flash(error, "error")
        return None

    pub = Publication(
        user_id=current_user.id,
        title=title,
        year=year,
        publication_type=pub_type,
        venue_name=form.get("venue_name", "").strip() or None,
        all_authors=form.get("all_authors", "").strip() or None,
        total_authors=form.get("total_authors", 1, type=int) or 1,
        author_role=form.get("author_role", "middle"),
        doi=form.get("doi", "").strip() or None,
        url=form.get("url", "").strip() or None,
        notes=form.get("notes", "").strip() or None,
    )

    # Type-specific fields
    _set_type_specific_fields(pub, form)

    # Calculate hours
    hours = calculate_publication_hours(pub)
    pub.base_hours = hours["base_hours"]
    pub.author_hours = hours["author_hours"]

    return pub


def _update_publication_from_form(pub: Publication, form) -> str | None:
    """Cập nhật Publication từ form data. Trả về lỗi hoặc None."""
    pub_type = form.get("publication_type")
    title = form.get("title", "").strip()

    if not pub_type:
        return "Vui lòng chọn loại ấn phẩm."
    if not title:
        return "Tên ấn phẩm không được để trống."

    year = form.get("year", type=int)
    if not year or year < 1900 or year > datetime.now().year + 1:
        return "Năm không hợp lệ."

    error = _validate_required_fields(form, pub_type)
    if error:
        return error

    pub.title = title
    pub.year = year
    pub.publication_type = pub_type
    pub.venue_name = form.get("venue_name", "").strip() or None
    pub.all_authors = form.get("all_authors", "").strip() or None
    pub.total_authors = form.get("total_authors", 1, type=int) or 1
    pub.author_role = form.get("author_role", "middle")
    pub.doi = form.get("doi", "").strip() or None
    pub.url = form.get("url", "").strip() or None
    pub.notes = form.get("notes", "").strip() or None

    # Type-specific fields
    _set_type_specific_fields(pub, form)

    # Recalculate hours
    hours = calculate_publication_hours(pub)
    pub.base_hours = hours["base_hours"]
    pub.author_hours = hours["author_hours"]

    return None


def _set_type_specific_fields(pub: Publication, form) -> None:
    """Set các trường đặc thù theo loại ấn phẩm"""
    pub_type = pub.publication_type

    # Reset all type-specific fields
    pub.quartile = None
    pub.domestic_points = 0.0
    pub.issn = None
    pub.isbn = None
    pub.patent_stage = None
    pub.patent_number = None
    pub.publisher = None
    pub.is_republished = False
    pub.contribution_percentage = None

    # All journal types: save ISSN and quartile
    if pub_type.startswith("journal_"):
        pub.issn = form.get("issn", "").strip() or None
        pub.quartile = form.get("quartile", "").strip() or None
        if pub_type == "journal_domestic":
            pub.domestic_points = form.get("domestic_points", 0.0, type=float)
        if pub_type == "journal_international_reputable":
            pub.publisher = form.get("publisher", "").strip() or None

    # All conference types: save ISBN
    elif pub_type.startswith("conference_"):
        pub.isbn = form.get("isbn", "").strip() or None

    # Books
    elif pub_type in (
        "monograph_international",
        "monograph_domestic",
        "textbook_international",
        "textbook_domestic",
        "book_chapter_reputable",
        "book_chapter_international",
    ):
        pub.publisher = form.get("publisher", "").strip() or None
        pub.isbn = form.get("isbn", "").strip() or None
        pub.is_republished = form.get("is_republished") == "on"

    # Patents
    elif pub_type in ("patent_international", "patent_vietnam", "utility_solution"):
        pub.patent_stage = form.get("patent_stage", "stage_1")
        pub.patent_number = form.get("patent_number", "").strip() or None

    # Contribution percentage (optional override)
    contrib = form.get("contribution_percentage", "").strip()
    if contrib:
        try:
            val = float(contrib)
            if val < 0 or val > 100:
                pub.contribution_percentage = None
            else:
                pub.contribution_percentage = val
        except ValueError:
            pub.contribution_percentage = None
