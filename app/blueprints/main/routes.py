"""
Main routes for VNU-UET Research Hours Web Application.
"""

from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_required, current_user

from app.db_models import User, Publication, Project, OtherActivity, AdminRole
from app.hours_calculator import (
    calculate_yearly_summary,
    calculate_total_research_hours,
    calculate_project_hours_from_model,
    calculate_project_hours_per_year,
    calculate_yearly_other_activities_total,
    HOURS_REFERENCE,
    HOURS_REFERENCE_TABLE2,
)

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Trang chủ"""
    # Kiem tra da co admin chua - neu chua thi chuyen den trang setup
    # Ưu tiên AdminRole (nguồn chuẩn), fallback admin_level legacy
    admin_exists = AdminRole.query.filter_by(is_active=True).first()
    if not admin_exists:
        admin_exists = User.query.filter(
            User.admin_level.in_(["department", "faculty", "university"])
        ).first()
    if not admin_exists:
        return redirect(url_for("auth.setup"))

    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    """Dashboard cá nhân - hiển thị cho tất cả user kể cả admin."""
    # Admin ở chế độ admin → redirect sang admin dashboard
    from app.services.approval import ACT_AS_USER_MODE_KEY

    if current_user.is_admin and not session.get(ACT_AS_USER_MODE_KEY, False):
        return redirect(url_for("admin.dashboard"))

    # Lay nam hien tai hoac nam duoc chon
    current_year = datetime.now().year
    selected_year = request.args.get("year", type=int, default=current_year)

    # Lay tat ca publications cua user
    all_publications = (
        Publication.query.filter_by(user_id=current_user.id)
        .order_by(Publication.year.desc(), Publication.created_at.desc())
        .all()
    )

    # Publications cua nam duoc chon
    year_publications = [p for p in all_publications if p.year == selected_year]

    # Lay tat ca projects cua user
    all_projects = (
        Project.query.filter_by(user_id=current_user.id)
        .order_by(Project.start_year.desc())
        .all()
    )

    # Projects trong nam duoc chon (dang thuc hien hoac ket thuc trong nam do)
    year_projects = [
        p for p in all_projects if p.start_year <= selected_year <= p.end_year
    ]

    # Tinh gio cho moi project (chia đều theo số năm cho hiển thị per-year)
    for proj in all_projects:
        hours = calculate_project_hours_from_model(proj)
        proj.total_hours = hours["total_hours"]
        proj.user_hours = hours["user_hours"]
        proj.user_hours_per_year = calculate_project_hours_per_year(proj)

    # Lay tat ca other activities cua user
    all_activities = (
        OtherActivity.query.filter_by(user_id=current_user.id)
        .order_by(OtherActivity.year.desc())
        .all()
    )

    # Activities cua nam duoc chon
    year_activities = [a for a in all_activities if a.year == selected_year]

    # Tinh tong hop publications CHO NAM DUOC CHON
    pub_summary = calculate_yearly_summary(all_publications, selected_year)

    # Tinh tong hop CHO NAM DUOC CHON
    total_summary = calculate_total_research_hours(
        all_publications, all_projects, list(all_activities), year=selected_year
    )

    # Thong ke theo nam (publications) - de hien thi bang
    years = sorted(set(p.year for p in all_publications), reverse=True)

    # Them nam hien tai vao danh sach neu chua co
    if current_year not in years:
        years = [current_year] + years
    years = sorted(years, reverse=True)

    # Danh sach nam cho dropdown
    available_years = years.copy()

    yearly_stats = []
    for year in years:
        # Tinh tong hop day du cho tung nam (Bang 1 + Bang 2)
        year_total = calculate_total_research_hours(
            all_publications, all_projects, list(all_activities), year=year
        )
        year_pub_summary = calculate_yearly_summary(all_publications, year)
        year_project_count = sum(
            1 for p in all_projects if p.start_year <= year <= p.end_year
        )
        year_activity_count = sum(1 for a in all_activities if a.year == year)
        year_pub_summary["total_research_hours"] = year_total["total_hours"]
        year_pub_summary["project_hours"] = year_total["project_hours"]
        year_pub_summary["activity_hours"] = year_total["other_activity_hours"]
        year_pub_summary["total_projects"] = year_project_count
        year_pub_summary["total_activities"] = year_activity_count
        yearly_stats.append(year_pub_summary)

    # Tinh tong gio projects CHO NAM DUOC CHON (chia đều giờ theo số năm)
    total_project_hours = sum(
        p.user_hours_per_year for p in year_projects if p.status != "extended"
    )

    # Tinh tong gio activities CHO NAM DUOC CHON (co gioi han 250 gio)
    if year_activities:
        activity_summary = calculate_yearly_other_activities_total(
            list(all_activities), selected_year
        )
        total_activity_hours = activity_summary["capped_hours"]
    else:
        total_activity_hours = 0.0

    # Đếm số lượng chờ duyệt cho năm được chọn
    pending_publications = (
        Publication.query.filter_by(user_id=current_user.id, is_approved=False)
        .filter(Publication.year == selected_year)
        .count()
    )

    pending_projects = (
        Project.query.filter_by(user_id=current_user.id, is_approved=False)
        .filter(Project.start_year <= selected_year, Project.end_year >= selected_year)
        .count()
    )

    pending_activities = OtherActivity.query.filter_by(
        user_id=current_user.id, is_approved=False, year=selected_year
    ).count()

    return render_template(
        "dashboard.html",
        publications=all_publications[:10],  # 10 an pham gan nhat
        projects=all_projects[:5],  # 5 de tai gan nhat
        other_activities=all_activities[:5],  # 5 hoat dong gan nhat
        summary=pub_summary,
        total_summary=total_summary,
        yearly_stats=yearly_stats,
        total_project_hours=total_project_hours,
        total_activity_hours=total_activity_hours,
        project_count=len(year_projects),
        activity_count=len(year_activities),
        selected_year=selected_year,
        current_year=current_year,
        available_years=available_years,
        pending_publications=pending_publications,
        pending_projects=pending_projects,
        pending_activities=pending_activities,
    )


@main_bp.route("/hours-reference")
def hours_reference():
    """Bảng quy đổi giờ"""
    return render_template(
        "hours_reference.html",
        hours_ref=HOURS_REFERENCE,
        hours_ref_table2=HOURS_REFERENCE_TABLE2,
    )
