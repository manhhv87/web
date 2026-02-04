"""
Reports routes for VNU-UET Research Hours Web Application.
"""

import csv
import io
from datetime import datetime

import re
import unicodedata
from urllib.parse import quote

from flask import Blueprint, render_template, request, Response, make_response
from flask_login import login_required, current_user

from app.db_models import Publication, Project, OtherActivity
from app.hours_calculator import (
    calculate_yearly_summary,
    calculate_publication_hours,
    calculate_project_hours_from_model,
    calculate_project_hours_per_year,
    calculate_yearly_other_activities_total,
    calculate_total_research_hours,
    OTHER_ACTIVITY_TYPE_CHOICES,
    PROJECT_LEVEL_CHOICES,
    DEFAULT_CONFIG,
)

report_bp = Blueprint("reports", __name__)

# Mapping từ publication_type key sang tên tiếng Việt
PUB_TYPE_DISPLAY = {
    "journal_wos_scopus": "Tạp chí WoS/Scopus",
    "journal_vnu_special": "Chuyên san VNU",
    "journal_rev": "Tạp chí Điện tử Truyền thông (REV)",
    "journal_international_reputable": "Tạp chí quốc tế uy tín (ngoài WoS/Scopus)",
    "journal_domestic": "Tạp chí trong nước",
    "conference_wos_scopus": "Hội nghị WoS/Scopus",
    "conference_international": "Hội nghị quốc tế",
    "conference_national": "Hội nghị quốc gia",
    "monograph_international": "Sách chuyên khảo (quốc tế)",
    "monograph_domestic": "Sách chuyên khảo (trong nước)",
    "textbook_international": "Giáo trình (quốc tế)",
    "textbook_domestic": "Giáo trình (trong nước)",
    "book_chapter_reputable": "Chương sách (NXB uy tín)",
    "book_chapter_international": "Chương sách (quốc tế)",
    "patent_international": "Bằng sáng chế (quốc tế)",
    "patent_vietnam": "Bằng sáng chế (Việt Nam)",
    "utility_solution": "Giải pháp hữu ích",
    "award_international": "Giải thưởng quốc tế",
    "award_national": "Giải thưởng quốc gia",
    "exhibition_international": "Triển lãm quốc tế",
    "exhibition_national": "Triển lãm quốc gia",
    "exhibition_provincial": "Triển lãm cấp tỉnh",
}


def _to_ascii_filename(name: str, default: str) -> str:
    """Return an ASCII-safe filename for HTTP headers (latin-1 safe)."""
    # Strip accents/diacritics
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    # Replace unsafe characters with underscores
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return s if s else default


def _set_download_headers(
    response, filename_utf8: str, content_type: str, default_ascii: str
) -> None:
    """Set RFC 5987 compatible Content-Disposition with UTF-8 filename + ASCII fallback."""
    filename_ascii = _to_ascii_filename(filename_utf8, default_ascii)
    response.headers["Content-Type"] = content_type
    response.headers["Content-Disposition"] = (
        f"attachment; filename={filename_ascii}; "
        f"filename*=UTF-8''{quote(filename_utf8)}"
    )


@report_bp.route("/")
@login_required
def report_index():
    """Trang báo cáo"""
    # Get all years from publications, projects, and activities
    pub_years = {
        y[0]
        for y in Publication.query.with_entities(Publication.year)
        .filter_by(user_id=current_user.id)
        .distinct()
        .all()
    }
    # Projects span start_year to end_year
    projects = Project.query.filter_by(user_id=current_user.id).all()
    proj_years = set()
    for p in projects:
        for y in range(p.start_year, p.end_year + 1):
            proj_years.add(y)
    act_years = {
        y[0]
        for y in OtherActivity.query.with_entities(OtherActivity.year)
        .filter_by(user_id=current_user.id)
        .distinct()
        .all()
    }
    years = sorted(pub_years | proj_years | act_years, reverse=True)

    return render_template("reports/index.html", years=years)


@report_bp.route("/yearly/<int:year>")
@login_required
def yearly_report(year):
    """Báo cáo theo năm"""
    # 1. Ấn phẩm
    publications = (
        Publication.query.filter_by(user_id=current_user.id, year=year)
        .order_by(Publication.created_at.desc())
        .all()
    )
    pub_summary = calculate_yearly_summary(publications, year)

    # 2. Đề tài/dự án (project spans start_year..end_year)
    projects = (
        Project.query.filter(
            Project.user_id == current_user.id,
            Project.start_year <= year,
            Project.end_year >= year,
        )
        .order_by(Project.created_at.desc())
        .all()
    )
    project_total_hours = 0.0
    for proj in projects:
        hours = calculate_project_hours_from_model(proj)
        per_year = calculate_project_hours_per_year(proj)
        proj.calc_total_hours = hours["total_hours"]
        proj.calc_user_hours = hours["user_hours"]
        proj.calc_user_hours_per_year = per_year
        project_total_hours += per_year

    # 3. Hoạt động KHCN khác
    activities = (
        OtherActivity.query.filter_by(user_id=current_user.id, year=year)
        .order_by(OtherActivity.created_at.desc())
        .all()
    )
    all_user_activities = OtherActivity.query.filter_by(user_id=current_user.id).all()
    activity_summary = calculate_yearly_other_activities_total(all_user_activities, year)

    # Tổng hợp tất cả
    grand_total = (
        pub_summary["total_author_hours"]
        + project_total_hours
        + activity_summary["capped_hours"]
    )

    return render_template(
        "reports/yearly.html",
        year=year,
        publications=publications,
        summary=pub_summary,
        projects=projects,
        project_total_hours=round(project_total_hours, 2),
        activities=activities,
        activity_summary=activity_summary,
        grand_total=round(grand_total, 2),
        user=current_user,
        pub_type_display=PUB_TYPE_DISPLAY,
        max_activity_hours=DEFAULT_CONFIG.other_activity_max_hours_per_year,
    )


@report_bp.route("/summary")
@login_required
def full_summary():
    """Báo cáo tổng hợp tất cả các năm"""
    # Query all data
    publications = (
        Publication.query.filter_by(user_id=current_user.id)
        .order_by(Publication.year.desc())
        .all()
    )
    projects = Project.query.filter_by(user_id=current_user.id).all()
    other_activities = OtherActivity.query.filter_by(user_id=current_user.id).all()

    # Overall publication summary
    pub_overall = calculate_yearly_summary(publications)

    # Overall totals
    overall_total = calculate_total_research_hours(
        publications, projects, other_activities
    )

    # Publication groups (grouped from pub_overall["by_type"])
    pub_groups = [
        {"key": "journal", "label": "Tạp chí", "count": 0, "color": "#11998e"},
        {"key": "conference", "label": "Hội nghị", "count": 0, "color": "#4facfe"},
        {"key": "book", "label": "Sách/Giáo trình", "count": 0, "color": "#667eea"},
        {"key": "ip_award", "label": "SHTT & Giải thưởng", "count": 0, "color": "#f5576c"},
    ]
    _PUB_GROUP_MAP = {
        "journal_wos_scopus": "journal", "journal_vnu_special": "journal",
        "journal_rev": "journal", "journal_international_reputable": "journal",
        "journal_domestic": "journal",
        "conference_wos_scopus": "conference", "conference_international": "conference",
        "conference_national": "conference",
        "monograph_international": "book", "monograph_domestic": "book",
        "textbook_international": "book", "textbook_domestic": "book",
        "book_chapter_reputable": "book", "book_chapter_international": "book",
        "patent_international": "ip_award", "patent_vietnam": "ip_award",
        "utility_solution": "ip_award", "award_international": "ip_award",
        "award_national": "ip_award", "exhibition_international": "ip_award",
        "exhibition_national": "ip_award", "exhibition_provincial": "ip_award",
    }
    for pub_type, data in pub_overall.get("by_type", {}).items():
        group_key = _PUB_GROUP_MAP.get(pub_type)
        if group_key:
            for g in pub_groups:
                if g["key"] == group_key:
                    g["count"] += data["count"]
                    break

    # Project breakdown by level
    _PROJ_LEVEL_LABELS = {
        "national": "Cấp Nhà nước",
        "vnu_ministry": "Cấp ĐHQGHN/Bộ",
        "university": "Cấp Trường",
        "cooperation": "Hợp tác/Dịch vụ",
    }
    _PROJ_LEVEL_COLORS = {
        "national": "#667eea",
        "vnu_ministry": "#4facfe",
        "university": "#11998e",
        "cooperation": "#f5576c",
    }
    project_by_level = []
    _proj_counts = {}
    for p in projects:
        _proj_counts[p.project_level] = _proj_counts.get(p.project_level, 0) + 1
    for level_key, label in _PROJ_LEVEL_LABELS.items():
        cnt = _proj_counts.get(level_key, 0)
        if cnt > 0:
            project_by_level.append({
                "label": label, "count": cnt,
                "color": _PROJ_LEVEL_COLORS.get(level_key, "#666"),
            })

    # Activity breakdown by type (sum quantity across all years)
    _ACT_TYPE_LABELS = {
        "student_research_university": "HD SV NCKH (cấp trường+)",
        "student_research_faculty": "HD SV NCKH (cấp khoa)",
        "team_training": "Huấn luyện đội tuyển",
        "exhibition_product": "SP triển lãm/cuộc thi",
    }
    _ACT_TYPE_COLORS = {
        "student_research_university": "#667eea",
        "student_research_faculty": "#4facfe",
        "team_training": "#11998e",
        "exhibition_product": "#f5576c",
    }
    activity_by_type = []
    _act_counts = {}
    for a in other_activities:
        _act_counts[a.activity_type] = _act_counts.get(a.activity_type, 0) + a.quantity
    for type_key, label in _ACT_TYPE_LABELS.items():
        cnt = _act_counts.get(type_key, 0)
        if cnt > 0:
            activity_by_type.append({
                "label": label, "count": cnt,
                "color": _ACT_TYPE_COLORS.get(type_key, "#666"),
            })

    # Collect all years from all sources
    pub_years = set(p.year for p in publications)
    proj_years = set()
    for p in projects:
        for y in range(p.start_year, p.end_year + 1):
            proj_years.add(y)
    act_years = set(a.year for a in other_activities)
    all_years = sorted(pub_years | proj_years | act_years, reverse=True)

    # Per-year breakdown
    yearly_data = []
    for year in all_years:
        pub_summary = calculate_yearly_summary(publications, year)

        # Projects for this year
        year_projects = [
            p for p in projects if p.start_year <= year <= p.end_year
        ]
        proj_hours = 0.0
        for proj in year_projects:
            proj_hours += calculate_project_hours_per_year(proj)

        # Activities for this year
        act_summary = calculate_yearly_other_activities_total(
            other_activities, year
        )

        year_total = (
            pub_summary["total_author_hours"]
            + proj_hours
            + act_summary["capped_hours"]
        )

        yearly_data.append({
            "year": year,
            "pub": pub_summary,
            "project_count": len(year_projects),
            "project_hours": round(proj_hours, 2),
            "activity_count": act_summary["activity_count"],
            "activity_hours": round(act_summary["capped_hours"], 2),
            "activity_is_capped": act_summary["is_capped"],
            "total_hours": round(year_total, 2),
        })

    return render_template(
        "reports/summary.html",
        pub_overall=pub_overall,
        overall_total=overall_total,
        yearly_data=yearly_data,
        pub_groups=pub_groups,
        project_by_level=project_by_level,
        activity_by_type=activity_by_type,
        total_projects=len(projects),
        total_activities=sum(a.quantity for a in other_activities),
        user=current_user,
        pub_type_display=PUB_TYPE_DISPLAY,
        max_activity_hours=DEFAULT_CONFIG.other_activity_max_hours_per_year,
    )


@report_bp.route("/export/csv")
@login_required
def export_csv():
    """Xuất báo cáo tổng hợp ra CSV (tất cả: ấn phẩm + đề tài + HĐ khác)"""
    year = request.args.get("year", type=int)

    # --- Fetch data ---
    pub_query = Publication.query.filter_by(user_id=current_user.id)
    if year:
        pub_query = pub_query.filter_by(year=year)
    publications = pub_query.order_by(Publication.year.desc()).all()

    projects = Project.query.filter_by(user_id=current_user.id).all()
    other_activities = OtherActivity.query.filter_by(user_id=current_user.id).all()

    if year:
        projects = [p for p in projects if p.start_year <= year <= p.end_year]
        other_activities = [a for a in other_activities if a.year == year]

    output = io.StringIO()
    writer = csv.writer(output)

    # ===== Sheet 1: Yearly Summary =====
    writer.writerow(["BÁO CÁO TỔNG HỢP GIỜ NGHIÊN CỨU"])
    writer.writerow([f"Họ tên: {current_user.full_name}"])
    if current_user.department:
        writer.writerow([f"Đơn vị: {current_user.department}"])
    writer.writerow([f"Ngày xuất: {datetime.now().strftime('%d/%m/%Y')}"])
    writer.writerow([])

    # Yearly breakdown table
    writer.writerow(["TỔNG HỢP THEO NĂM"])
    writer.writerow([
        "Năm",
        "SL Ấn phẩm", "SL Đề tài", "SL HĐ khác",
        "Giờ Ấn phẩm", "Giờ Đề tài", "Giờ HĐ khác",
        "Tổng giờ",
    ])

    # Compute all years
    all_pubs = Publication.query.filter_by(user_id=current_user.id).all()
    all_projs = Project.query.filter_by(user_id=current_user.id).all()
    all_acts = OtherActivity.query.filter_by(user_id=current_user.id).all()

    pub_years = set(p.year for p in all_pubs)
    proj_years = set()
    for p in all_projs:
        for y in range(p.start_year, p.end_year + 1):
            proj_years.add(y)
    act_years = set(a.year for a in all_acts)
    all_years = sorted(pub_years | proj_years | act_years, reverse=True)

    if year:
        all_years = [year]

    grand_pub_h = grand_proj_h = grand_act_h = 0
    for yr in all_years:
        ps = calculate_yearly_summary(all_pubs, yr)
        yr_projs = [p for p in all_projs if p.start_year <= yr <= p.end_year]
        proj_h = sum(calculate_project_hours_per_year(p) for p in yr_projs)
        act_s = calculate_yearly_other_activities_total(all_acts, yr)
        total_h = ps["total_author_hours"] + proj_h + act_s["capped_hours"]
        grand_pub_h += ps["total_author_hours"]
        grand_proj_h += proj_h
        grand_act_h += act_s["capped_hours"]
        writer.writerow([
            yr,
            ps["total_publications"], len(yr_projs), act_s["activity_count"],
            round(ps["total_author_hours"], 2), round(proj_h, 2), round(act_s["capped_hours"], 2),
            round(total_h, 2),
        ])

    writer.writerow([
        "TỔNG", "", "", "",
        round(grand_pub_h, 2), round(grand_proj_h, 2), round(grand_act_h, 2),
        round(grand_pub_h + grand_proj_h + grand_act_h, 2),
    ])
    writer.writerow([])

    # ===== Sheet 2: Publication details =====
    writer.writerow(["DANH SÁCH ẤN PHẨM"])
    writer.writerow([
        "STT", "Năm", "Tên ấn phẩm", "Loại", "Venue/NXB",
        "Quartile", "Điểm HĐGSNN", "Tổng tác giả", "Vai trò",
        "Giờ cơ bản", "Giờ tác giả", "DOI", "Ghi chú",
    ])
    for i, pub in enumerate(publications, 1):
        writer.writerow([
            i, pub.year, pub.title, pub.publication_type_display,
            pub.venue_name or pub.publisher or "",
            pub.quartile or "",
            pub.domestic_points if pub.domestic_points else "",
            pub.total_authors, pub.author_role_display,
            pub.base_hours, pub.author_hours,
            pub.doi or "", pub.notes or "",
        ])
    writer.writerow([])

    # ===== Sheet 3: Project details =====
    _proj_level_map = dict(PROJECT_LEVEL_CHOICES)
    writer.writerow(["DANH SÁCH ĐỀ TÀI, DỰ ÁN"])
    writer.writerow([
        "STT", "Năm BĐ", "Năm KT", "Tên đề tài", "Mã đề tài",
        "Cấp", "Vai trò", "Số thành viên", "Giờ người dùng", "Ghi chú",
    ])
    for i, proj in enumerate(projects, 1):
        hours = calculate_project_hours_from_model(proj)
        writer.writerow([
            i, proj.start_year, proj.end_year, proj.title,
            proj.project_code or "",
            _proj_level_map.get(proj.project_level, proj.project_level),
            proj.role, proj.total_members,
            round(hours["user_hours"], 2),
            proj.notes or "",
        ])
    writer.writerow([])

    # ===== Sheet 4: Activity details =====
    _act_type_map = dict(OTHER_ACTIVITY_TYPE_CHOICES)
    writer.writerow(["DANH SÁCH HOẠT ĐỘNG KHCN KHÁC"])
    writer.writerow([
        "STT", "Năm", "Loại", "Tên/Mô tả", "Số lượng", "Giờ", "Ghi chú",
    ])
    for i, act in enumerate(other_activities, 1):
        writer.writerow([
            i, act.year,
            _act_type_map.get(act.activity_type, act.activity_type),
            act.title or "", act.quantity, act.hours or 0,
            act.notes or "",
        ])

    # Create response
    output.seek(0)
    filename = f"VNU_baocao_{current_user.full_name.replace(' ', '_')}"
    if year:
        filename += f"_{year}"
    filename += f"_{datetime.now().strftime('%Y%m%d')}.csv"

    csv_bytes = output.getvalue().encode("utf-8-sig")

    response = make_response(csv_bytes)
    _set_download_headers(
        response,
        filename_utf8=filename,
        content_type="text/csv; charset=utf-8",
        default_ascii="VNU_report.csv",
    )

    return response


@report_bp.route("/export/summary-txt")
@login_required
def export_summary_txt():
    """Xuất báo cáo tổng hợp dạng text (ấn phẩm + đề tài + HĐ khác)"""
    year = request.args.get("year", type=int)

    # --- Fetch data ---
    pub_query = Publication.query.filter_by(user_id=current_user.id)
    if year:
        pub_query = pub_query.filter_by(year=year)
    publications = pub_query.order_by(Publication.year.desc()).all()

    all_pubs = Publication.query.filter_by(user_id=current_user.id).all()
    all_projs = Project.query.filter_by(user_id=current_user.id).all()
    all_acts = OtherActivity.query.filter_by(user_id=current_user.id).all()

    projects = all_projs
    other_activities = all_acts
    if year:
        projects = [p for p in all_projs if p.start_year <= year <= p.end_year]
        other_activities = [a for a in all_acts if a.year == year]

    # Compute years
    pub_years = set(p.year for p in all_pubs)
    proj_years = set()
    for p in all_projs:
        for y in range(p.start_year, p.end_year + 1):
            proj_years.add(y)
    act_years = set(a.year for a in all_acts)
    all_years = sorted(pub_years | proj_years | act_years, reverse=True)
    if year:
        all_years = [year]

    # Generate text report
    lines = []
    lines.append("=" * 80)
    lines.append("BÁO CÁO TỔNG HỢP GIỜ NGHIÊN CỨU KHOA HỌC")
    lines.append("Theo Quy chế VNU-UET (QĐ 2706/QĐ-ĐHCN ngày 21/11/2024)")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Họ tên: {current_user.full_name}")
    if current_user.department:
        lines.append(f"Đơn vị: {current_user.department}")
    if current_user.employee_id:
        lines.append(f"Mã cán bộ: {current_user.employee_id}")
    lines.append(f"Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    if year:
        lines.append(f"Năm: {year}")
    lines.append("")

    # ===== Section 1: Yearly Summary Table =====
    lines.append("-" * 80)
    lines.append("TỔNG HỢP THEO NĂM")
    lines.append("-" * 80)
    header = f"{'Năm':<6} {'SL ẤP':>6} {'SL ĐT':>6} {'SL HĐ':>6} | {'Giờ ẤP':>10} {'Giờ ĐT':>10} {'Giờ HĐ':>10} {'Tổng':>10}"
    lines.append(header)
    lines.append("-" * 80)

    grand_pub_h = grand_proj_h = grand_act_h = 0.0
    for yr in all_years:
        ps = calculate_yearly_summary(all_pubs, yr)
        yr_projs = [p for p in all_projs if p.start_year <= yr <= p.end_year]
        proj_h = sum(calculate_project_hours_per_year(p) for p in yr_projs)
        act_s = calculate_yearly_other_activities_total(all_acts, yr)
        total_h = ps["total_author_hours"] + proj_h + act_s["capped_hours"]
        grand_pub_h += ps["total_author_hours"]
        grand_proj_h += proj_h
        grand_act_h += act_s["capped_hours"]
        lines.append(
            f"{yr:<6} {ps['total_publications']:>6} {len(yr_projs):>6} {act_s['activity_count']:>6}"
            f" | {ps['total_author_hours']:>10.2f} {proj_h:>10.2f} {act_s['capped_hours']:>10.2f} {total_h:>10.2f}"
        )

    lines.append("-" * 80)
    grand_total = grand_pub_h + grand_proj_h + grand_act_h
    lines.append(
        f"{'TỔNG':<6} {'':>6} {'':>6} {'':>6}"
        f" | {grand_pub_h:>10.2f} {grand_proj_h:>10.2f} {grand_act_h:>10.2f} {grand_total:>10.2f}"
    )
    lines.append("")

    # ===== Section 2: Publication statistics =====
    summary = calculate_yearly_summary(publications, year)
    lines.append("-" * 80)
    lines.append("THỐNG KÊ ẤN PHẨM")
    lines.append("-" * 80)
    lines.append(f"Tổng số ấn phẩm:        {summary['total_publications']:>10}")
    lines.append(f"Số bài WoS/Scopus:      {summary['wos_scopus_count']:>10}")
    lines.append(f"  - Q1:                 {summary['by_quartile']['Q1']:>10}")
    lines.append(f"  - Q2:                 {summary['by_quartile']['Q2']:>10}")
    lines.append(f"  - Q3:                 {summary['by_quartile']['Q3']:>10}")
    lines.append(f"  - Q4:                 {summary['by_quartile']['Q4']:>10}")
    lines.append(f"Tổng giờ ấn phẩm:       {summary['total_author_hours']:>10.2f} giờ")
    lines.append("")

    # Per type breakdown
    if summary["by_type"]:
        lines.append(f"{'Loại':<40} {'SL':>8} {'Giờ':>12}")
        lines.append("-" * 62)
        for pub_type, data in summary["by_type"].items():
            type_name = PUB_TYPE_DISPLAY.get(pub_type, pub_type)
            lines.append(f"{type_name:<40} {data['count']:>8} {data['hours']:>12.2f}")
        lines.append("")

    # ===== Section 3: Publication list =====
    lines.append("-" * 80)
    lines.append("DANH SÁCH ẤN PHẨM")
    lines.append("-" * 80)
    for i, pub in enumerate(publications, 1):
        lines.append(f"{i}. {pub.title}")
        lines.append(f"   Năm: {pub.year} | Loại: {pub.publication_type_display}")
        lines.append(f"   Vai trò: {pub.author_role_display} | Giờ: {pub.author_hours}")
        if pub.doi:
            lines.append(f"   DOI: {pub.doi}")
        lines.append("")

    # ===== Section 4: Project list =====
    _proj_level_map = dict(PROJECT_LEVEL_CHOICES)
    lines.append("-" * 80)
    lines.append("DANH SÁCH ĐỀ TÀI, DỰ ÁN")
    lines.append("-" * 80)
    if projects:
        for i, proj in enumerate(projects, 1):
            hours = calculate_project_hours_from_model(proj)
            lines.append(f"{i}. {proj.title}")
            lines.append(f"   Năm: {proj.start_year}-{proj.end_year} | Cấp: {_proj_level_map.get(proj.project_level, proj.project_level)}")
            lines.append(f"   Vai trò: {proj.role} | Thành viên: {proj.total_members} | Giờ: {round(hours['user_hours'], 2)}")
            if proj.project_code:
                lines.append(f"   Mã đề tài: {proj.project_code}")
            lines.append("")
    else:
        lines.append("(Không có dữ liệu)")
        lines.append("")

    # ===== Section 5: Activity list =====
    _act_type_map = dict(OTHER_ACTIVITY_TYPE_CHOICES)
    lines.append("-" * 80)
    lines.append("DANH SÁCH HOẠT ĐỘNG KHCN KHÁC")
    lines.append("-" * 80)
    if other_activities:
        for i, act in enumerate(other_activities, 1):
            lines.append(f"{i}. {act.title or _act_type_map.get(act.activity_type, act.activity_type)}")
            lines.append(f"   Năm: {act.year} | Loại: {_act_type_map.get(act.activity_type, act.activity_type)}")
            lines.append(f"   Số lượng: {act.quantity} | Giờ: {act.hours or 0}")
            lines.append("")
    else:
        lines.append("(Không có dữ liệu)")
        lines.append("")

    # ===== Footer =====
    lines.append("=" * 80)
    lines.append(f"TỔNG GIỜ NGHIÊN CỨU:    {grand_total:>10.2f} giờ")
    lines.append("=" * 80)

    # Create response
    content = "\n".join(lines)
    filename = f"VNU_baocao_{current_user.full_name.replace(' ', '_')}"
    if year:
        filename += f"_{year}"
    filename += f"_{datetime.now().strftime('%Y%m%d')}.txt"

    txt_bytes = content.encode("utf-8-sig")

    response = make_response(txt_bytes)
    _set_download_headers(
        response,
        filename_utf8=filename,
        content_type="text/plain; charset=utf-8",
        default_ascii="VNU_report.txt",
    )

    return response
