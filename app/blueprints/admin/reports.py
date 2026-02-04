"""Admin reporting routes."""

from __future__ import annotations

from flask_login import login_required

from . import admin_bp
from .helpers import *  # noqa: F403

# =============================================================================
# REPORTS
# =============================================================================


@admin_bp.route("/reports")
@login_required
@admin_required
def reports():
    """Báo cáo tổng hợp chi tiết (admin)"""
    year = request.args.get("year", type=int, default=datetime.now().year)
    user_id = request.args.get("user_id", type=int)
    org_unit_id = request.args.get("org_unit_id", type=int)
    division_id = request.args.get("division_id", type=int)
    effective_level = effective_admin_level(current_user)

    # Lấy tất cả users theo filter (loại trừ admin@vnu.edu.vn)
    query = User.query.filter_by(is_active=True).filter(
        User.email != "admin@vnu.edu.vn"
    )
    query = filter_users_by_scope(query, current_user)

    # Dữ liệu filter theo phạm vi (Khoa/Phòng ban, Bộ môn, Người dùng)
    org_units, divisions, scoped_users, filtered_user_ids_sq = build_scope_filter_data(
        current_user, org_unit_id, division_id
    )

    if org_unit_id or division_id:
        query = query.filter(User.id.in_(select(filtered_user_ids_sq.c.id)))
    if user_id:
        query = query.filter(User.id == user_id)

    selected_user = next((u for u in scoped_users if u.id == user_id), None)
    selected_user_name = selected_user.full_name if selected_user else None

    users = query.order_by(User.department, User.full_name).all()

    report_data = []
    department_totals = {}  # Tổng hợp theo bộ môn

    # Thống kê tổng hợp theo loại ấn phẩm cho toàn khoa
    faculty_pub_by_type = {}
    faculty_project_by_level = {}
    faculty_activity_by_type = {}

    for user in users:
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

        # Thống kê chi tiết theo loại ấn phẩm
        pub_by_type = {}
        for pub in pubs:
            ptype = pub.publication_type
            if ptype not in pub_by_type:
                pub_by_type[ptype] = {"count": 0, "hours": 0}
            pub_by_type[ptype]["count"] += 1
            pub_by_type[ptype]["hours"] += pub.author_hours
            # Tổng hợp toàn khoa
            if ptype not in faculty_pub_by_type:
                faculty_pub_by_type[ptype] = {"count": 0, "hours": 0}
            faculty_pub_by_type[ptype]["count"] += 1
            faculty_pub_by_type[ptype]["hours"] += pub.author_hours

        # Thống kê chi tiết theo cấp đề tài
        project_by_level = {}
        for proj in projects:
            plevel = proj.project_level
            hours = calculate_project_hours_from_model(proj)
            if plevel not in project_by_level:
                project_by_level[plevel] = {"count": 0, "hours": 0}
            project_by_level[plevel]["count"] += 1
            project_by_level[plevel]["hours"] += (
                hours["user_hours"] if proj.status != "extended" else 0
            )
            # Tổng hợp toàn khoa
            if plevel not in faculty_project_by_level:
                faculty_project_by_level[plevel] = {"count": 0, "hours": 0}
            faculty_project_by_level[plevel]["count"] += 1
            faculty_project_by_level[plevel]["hours"] += (
                hours["user_hours"] if proj.status != "extended" else 0
            )

        # Thống kê chi tiết theo loại hoạt động KHCN khác
        activity_by_type = {}
        for act in activities:
            atype = act.activity_type
            act_hours = calculate_other_activity_hours_from_model(act)
            if atype not in activity_by_type:
                activity_by_type[atype] = {"count": 0, "hours": 0, "quantity": 0}
            activity_by_type[atype]["count"] += 1
            activity_by_type[atype]["hours"] += act_hours
            activity_by_type[atype]["quantity"] += act.quantity
            # Tổng hợp toàn khoa
            if atype not in faculty_activity_by_type:
                faculty_activity_by_type[atype] = {
                    "count": 0,
                    "hours": 0,
                    "quantity": 0,
                }
            faculty_activity_by_type[atype]["count"] += 1
            faculty_activity_by_type[atype]["hours"] += act_hours
            faculty_activity_by_type[atype]["quantity"] += act.quantity

        # Thống kê Q1-Q4
        q_stats = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
        for pub in pubs:
            if pub.quartile in q_stats:
                q_stats[pub.quartile] += 1

        # Thống kê theo nhóm ấn phẩm
        pub_groups = {
            "wos_scopus": 0,  # journal_wos_scopus + conference_wos_scopus
            "international": 0,  # Quốc tế khác (ngoài WoS/Scopus)
            "domestic": 0,  # Trong nước
            "book": 0,  # Sách, giáo trình, chương sách
            "ip_award": 0,  # SHTT, giải thưởng, triển lãm
        }
        wos_scopus_types = ["journal_wos_scopus", "conference_wos_scopus"]
        international_types = [
            "journal_international_reputable",
            "conference_international",
        ]
        domestic_types = [
            "journal_vnu_special",
            "journal_rev",
            "journal_domestic",
            "conference_national",
        ]
        book_types = [
            "monograph_international",
            "monograph_domestic",
            "textbook_international",
            "textbook_domestic",
            "book_chapter_reputable",
            "book_chapter_international",
        ]
        ip_award_types = [
            "patent_international",
            "patent_vietnam",
            "utility_solution",
            "award_international",
            "award_national",
            "exhibition_international",
            "exhibition_national",
            "exhibition_provincial",
        ]

        for pub in pubs:
            ptype = pub.publication_type
            if ptype in wos_scopus_types:
                pub_groups["wos_scopus"] += 1
            elif ptype in international_types:
                pub_groups["international"] += 1
            elif ptype in domestic_types:
                pub_groups["domestic"] += 1
            elif ptype in book_types:
                pub_groups["book"] += 1
            elif ptype in ip_award_types:
                pub_groups["ip_award"] += 1

        user_data = {
            "user": user,
            "pub_count": len(pubs),
            "project_count": len(projects),
            "activity_count": len(activities),
            "publication_hours": summary["publication_hours"],
            "project_hours": summary["project_hours"],
            "activity_hours": summary["other_activity_hours"],
            "total_hours": summary["total_hours"],
            "pub_by_type": pub_by_type,
            "project_by_level": project_by_level,
            "activity_by_type": activity_by_type,
            "q_stats": q_stats,
            "pub_groups": pub_groups,
        }
        report_data.append(user_data)

        # Tổng hợp theo bộ môn
        if user.user_division:
            dept = (
                user.user_division.full_name
                if effective_level == "university"
                else user.user_division.name
            )
        else:
            dept = user.department or "Chưa xác định"
        if dept not in department_totals:
            department_totals[dept] = {
                "user_count": 0,
                "pub_count": 0,
                "project_count": 0,
                "activity_count": 0,
                "publication_hours": 0,
                "project_hours": 0,
                "activity_hours": 0,
                "total_hours": 0,
                "q_stats": {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0},
                "pub_by_type": {},
                "project_by_level": {},
                "activity_by_type": {},
                "pub_groups": {
                    "wos_scopus": 0,
                    "international": 0,
                    "domestic": 0,
                    "book": 0,
                    "ip_award": 0,
                },
            }
        department_totals[dept]["user_count"] += 1
        department_totals[dept]["pub_count"] += len(pubs)
        department_totals[dept]["project_count"] += len(projects)
        department_totals[dept]["activity_count"] += len(activities)
        department_totals[dept]["publication_hours"] += summary["publication_hours"]
        department_totals[dept]["project_hours"] += summary["project_hours"]
        department_totals[dept]["activity_hours"] += summary["other_activity_hours"]
        department_totals[dept]["total_hours"] += summary["total_hours"]
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            department_totals[dept]["q_stats"][q] += q_stats[q]
        # Thêm thống kê theo loại cho bộ môn
        for ptype, pdata in pub_by_type.items():
            if ptype not in department_totals[dept]["pub_by_type"]:
                department_totals[dept]["pub_by_type"][ptype] = {"count": 0, "hours": 0}
            department_totals[dept]["pub_by_type"][ptype]["count"] += pdata["count"]
            department_totals[dept]["pub_by_type"][ptype]["hours"] += pdata["hours"]
        for plevel, pdata in project_by_level.items():
            if plevel not in department_totals[dept]["project_by_level"]:
                department_totals[dept]["project_by_level"][plevel] = {
                    "count": 0,
                    "hours": 0,
                }
            department_totals[dept]["project_by_level"][plevel]["count"] += pdata[
                "count"
            ]
            department_totals[dept]["project_by_level"][plevel]["hours"] += pdata[
                "hours"
            ]
        for atype, adata in activity_by_type.items():
            if atype not in department_totals[dept]["activity_by_type"]:
                department_totals[dept]["activity_by_type"][atype] = {
                    "count": 0,
                    "hours": 0,
                    "quantity": 0,
                }
            department_totals[dept]["activity_by_type"][atype]["count"] += adata[
                "count"
            ]
            department_totals[dept]["activity_by_type"][atype]["hours"] += adata[
                "hours"
            ]
            department_totals[dept]["activity_by_type"][atype]["quantity"] += adata[
                "quantity"
            ]
        # Thêm thống kê theo nhóm ấn phẩm cho bộ môn
        for grp in ["wos_scopus", "international", "domestic", "book", "ip_award"]:
            department_totals[dept]["pub_groups"][grp] += pub_groups[grp]

    # Tổng cộng toàn khoa
    faculty_total = {
        "user_count": sum(d["user_count"] for d in department_totals.values()),
        "pub_count": sum(d["pub_count"] for d in department_totals.values()),
        "project_count": sum(d["project_count"] for d in department_totals.values()),
        "activity_count": sum(d["activity_count"] for d in department_totals.values()),
        "publication_hours": sum(
            d["publication_hours"] for d in department_totals.values()
        ),
        "project_hours": sum(d["project_hours"] for d in department_totals.values()),
        "activity_hours": sum(d["activity_hours"] for d in department_totals.values()),
        "total_hours": sum(d["total_hours"] for d in department_totals.values()),
        "q_stats": {
            q: sum(d["q_stats"][q] for d in department_totals.values())
            for q in ["Q1", "Q2", "Q3", "Q4"]
        },
        "pub_by_type": faculty_pub_by_type,
        "project_by_level": faculty_project_by_level,
        "activity_by_type": faculty_activity_by_type,
        "pub_groups": {
            grp: sum(d["pub_groups"][grp] for d in department_totals.values())
            for grp in ["wos_scopus", "international", "domestic", "book", "ip_award"]
        },
    }

    # Sắp xếp theo tổng giờ giảm dần
    report_data.sort(key=lambda x: x["total_hours"], reverse=True)

    # Lấy danh sách năm
    years = set()
    for pub in Publication.query.with_entities(Publication.year).distinct():
        years.add(pub.year)
    for proj in Project.query.all():
        for y in range(proj.start_year, proj.end_year + 1):
            years.add(y)
    for act in OtherActivity.query.with_entities(OtherActivity.year).distinct():
        years.add(act.year)
    years.add(datetime.now().year)
    years = sorted(years, reverse=True)

    selected_org_unit = next((ou for ou in org_units if ou.id == org_unit_id), None)
    selected_division = next((div for div in divisions if div.id == division_id), None)
    if selected_division:
        selected_division_name = (
            selected_division.full_name
            if effective_level == "university"
            else selected_division.name
        )
    else:
        selected_division_name = None

    # Department admin luôn cố định trong 1 bộ môn -> hiển thị tên bộ môn thay vì "Toàn bộ môn"
    if effective_level == "department" and not selected_division_name and divisions:
        selected_division_name = divisions[0].name
        if division_id is None:
            division_id = divisions[0].id

    division_id_by_name = {
        (div.full_name if effective_level == "university" else div.name): div.id
        for div in divisions
    }

    if effective_level == "university":
        base_scope_title = "Toàn trường"
    elif effective_level == "faculty":
        base_scope_title = "Toàn khoa"
    elif effective_level == "department":
        base_scope_title = "Toàn bộ môn"
    else:
        base_scope_title = "Toàn phạm vi"

    scope_title = (
        selected_division_name
        or (selected_org_unit.name if selected_org_unit else None)
        or base_scope_title
    )

    return render_template(
        "admin/reports.html",
        report_data=report_data,
        department_totals=department_totals,
        faculty_total=faculty_total,
        org_units=org_units,
        divisions=divisions,
        scoped_users=scoped_users,
        division_id_by_name=division_id_by_name,
        selected_year=year,
        selected_org_unit_id=org_unit_id,
        selected_division_id=division_id,
        selected_division_name=selected_division_name,
        selected_user_id=user_id,
        selected_user_name=selected_user_name,
        scope_title=scope_title,
        admin_level=effective_level,
        years=years,
        pub_type_choices=PUBLICATION_TYPE_CHOICES,
        project_level_choices=PROJECT_LEVEL_CHOICES,
        activity_type_choices=OTHER_ACTIVITY_TYPE_CHOICES,
    )
