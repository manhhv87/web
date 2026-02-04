"""
VNU-UET Research Hours Calculator.
Tinh gio nghien cuu theo Quy che (Quyet dinh 2706/QD-DHCN ngay 21/11/2024).

Ho tro:
- Bang 1: Quy doi gio cho an pham khoa hoc
- Bang 2: Quy doi gio cho hoat dong KHCN va chuyen giao tri thuc
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .db_models import Publication, Project, OtherActivity


@dataclass
class HoursConfig:
    """Cau hinh so gio theo Quy che VNU-UET"""

    # 1. Bai bao khoa hoc
    hours_journal_wos_scopus_q1_q2: float = 1800.0  # 1.1
    hours_journal_wos_scopus_q3_q4: float = 1400.0  # 1.1
    hours_journal_vnu_special: float = 900.0  # 1.2a - Chuyen san VNU
    hours_journal_rev: float = 900.0  # 1.2b - Tap chi Dien tu Truyen thong (REV)
    hours_journal_international_reputable: float = (
        900.0  # 1.3 - Tap chi quoc te uy tin ngoai WoS/Scopus
    )
    hours_journal_domestic_gte_1: float = 800.0  # 1.4a >= 1 diem
    hours_journal_domestic_gte_05: float = 600.0  # 1.4b >= 0.5 diem
    hours_journal_domestic_lt_05: float = 300.0  # 1.4c < 0.5 diem

    # 2. Bao cao khoa hoc
    hours_conference_wos_scopus: float = 900.0
    hours_conference_international: float = 600.0
    hours_conference_national: float = 500.0

    # 3. Sach, giao trinh
    hours_monograph_international: float = 2700.0
    hours_monograph_domestic: float = 1500.0
    hours_textbook_international: float = 1800.0
    hours_textbook_domestic: float = 900.0
    hours_book_chapter_reputable: float = 1200.0
    hours_book_chapter_international: float = 900.0

    # 4. San pham so huu tri tue
    hours_patent_international: float = 3000.0
    hours_patent_vietnam: float = 1800.0
    hours_utility_solution: float = 1200.0

    # 4.4 Giai thuong
    hours_award_international: float = 1800.0
    hours_award_national: float = 1200.0

    # 4.5 Trien lam
    hours_exhibition_international: float = 900.0
    hours_exhibition_national: float = 600.0
    hours_exhibition_provincial: float = 400.0

    # Dieu chinh
    republished_book_max_ratio: float = 1.0 / 3.0  # Tai ban toi da 1/3
    patent_stage_1_ratio: float = 1.0 / 3.0  # Giai doan 1: 1/3
    patent_stage_2_ratio: float = 2.0 / 3.0  # Giai doan 2: 2/3

    # ==========================================================================
    # BANG 2 - HOAT DONG KHCN VA CHUYEN GIAO TRI THUC
    # ==========================================================================

    # 1. De tai, du an cac cap
    # 1.1 - De tai cap Nha nuoc
    hours_project_national_total: float = 1000.0
    hours_project_national_leader: float = 500.0  # Chu tri
    hours_project_national_secretary: float = 250.0  # Thu ky
    hours_project_national_member: float = 250.0  # Thanh vien

    # 1.2 - De tai cap DHQGHN/Bo
    hours_project_vnu_total: float = 800.0
    hours_project_vnu_leader: float = 400.0
    hours_project_vnu_secretary: float = 200.0
    hours_project_vnu_member: float = 200.0

    # 1.3 - De tai cap Truong
    hours_project_university_total: float = 300.0
    hours_project_university_leader: float = 300.0
    # Cap truong chi co chu tri, khong co thu ky va thanh vien rieng

    # 2. De tai hop tac, dich vu KHCN
    # Cong thuc: 100 + 1000 * (gia tri tai tro ty dong) / so nam
    cooperation_base_hours: float = 100.0
    cooperation_multiplier: float = 1000.0  # Nhan voi gia tri ty dong
    cooperation_leader_ratio: float = 0.50  # 50% cho chu tri
    cooperation_secretary_ratio: float = 0.25  # 25% cho thu ky
    cooperation_member_ratio: float = 0.25  # 25% cho thanh vien

    # 3. Hoat dong KHCN khac (toi da 250 gio/nam)
    other_activity_max_hours_per_year: float = 250.0

    # 3.1 - Huong dan SV NCKH
    hours_student_research_university: float = 75.0  # Cap truong tro len (75/nhom)
    hours_student_research_faculty: float = 30.0  # Cap khoa (30/nhom)

    # 3.2 - Huan luyen doi tuyen SV
    hours_team_training: float = 75.0  # 75/doi tuyen

    # 3.3 - San pham KHCN trien lam
    hours_exhibition_product: float = 45.0  # 45/san pham


# Default configuration instance
DEFAULT_CONFIG = HoursConfig()


def get_base_hours(
    publication_type: str,
    quartile: Optional[str] = None,
    domestic_points: float = 0.0,
    patent_stage: Optional[str] = None,
    is_republished: bool = False,
    config: HoursConfig = DEFAULT_CONFIG,
) -> float:
    """
    Tinh so gio co ban dua tren loai an pham.

    Args:
        publication_type: Loai an pham (tu PublicationType enum)
        quartile: Q1, Q2, Q3, Q4 (cho WoS/Scopus)
        domestic_points: Diem HDGSNN (cho tap chi trong nuoc)
        patent_stage: stage_1, stage_2, granted (cho patent)
        is_republished: Co phai sach tai ban khong
        config: Cau hinh so gio

    Returns:
        So gio co ban (chua tinh % tac gia)
    """
    hours = 0.0

    # 1. Bai bao khoa hoc
    if publication_type == "journal_wos_scopus":
        if quartile in ("Q1", "Q2"):
            hours = config.hours_journal_wos_scopus_q1_q2
        else:  # Q3, Q4
            hours = config.hours_journal_wos_scopus_q3_q4

    elif publication_type == "journal_vnu_special":
        hours = config.hours_journal_vnu_special

    elif publication_type == "journal_rev":
        hours = config.hours_journal_rev

    elif publication_type == "journal_international_reputable":
        hours = config.hours_journal_international_reputable

    elif publication_type == "journal_domestic":
        if domestic_points >= 1.0:
            hours = config.hours_journal_domestic_gte_1
        elif domestic_points >= 0.5:
            hours = config.hours_journal_domestic_gte_05
        else:
            hours = config.hours_journal_domestic_lt_05

    # 2. Bao cao khoa hoc
    elif publication_type == "conference_wos_scopus":
        hours = config.hours_conference_wos_scopus

    elif publication_type == "conference_international":
        hours = config.hours_conference_international

    elif publication_type == "conference_national":
        hours = config.hours_conference_national

    # 3. Sach, giao trinh
    elif publication_type == "monograph_international":
        hours = config.hours_monograph_international

    elif publication_type == "monograph_domestic":
        hours = config.hours_monograph_domestic

    elif publication_type == "textbook_international":
        hours = config.hours_textbook_international

    elif publication_type == "textbook_domestic":
        hours = config.hours_textbook_domestic

    elif publication_type == "book_chapter_reputable":
        hours = config.hours_book_chapter_reputable

    elif publication_type == "book_chapter_international":
        hours = config.hours_book_chapter_international

    # 4. San pham so huu tri tue
    elif publication_type == "patent_international":
        hours = config.hours_patent_international

    elif publication_type == "patent_vietnam":
        hours = config.hours_patent_vietnam

    elif publication_type == "utility_solution":
        hours = config.hours_utility_solution

    # 4.4 Giai thuong
    elif publication_type == "award_international":
        hours = config.hours_award_international

    elif publication_type == "award_national":
        hours = config.hours_award_national

    # 4.5 Trien lam
    elif publication_type == "exhibition_international":
        hours = config.hours_exhibition_international

    elif publication_type == "exhibition_national":
        hours = config.hours_exhibition_national

    elif publication_type == "exhibition_provincial":
        hours = config.hours_exhibition_provincial

    # Dieu chinh cho sach tai ban (bao gom book_chapter)
    if is_republished and publication_type in (
        "monograph_international",
        "monograph_domestic",
        "textbook_international",
        "textbook_domestic",
        "book_chapter_reputable",
        "book_chapter_international",
    ):
        hours *= config.republished_book_max_ratio

    # Dieu chinh cho patent theo giai doan (Quy che muc e)
    # Stage 1: Don dang ky duoc chap nhan -> 1/3 tong gio
    # Stage 2: Duoc cap bang van ban -> 2/3 tong gio
    # Nguoi dung nhap MOI giai doan lam 1 ban ghi rieng, tong = 100%
    if publication_type in (
        "patent_international",
        "patent_vietnam",
        "utility_solution",
    ):
        if patent_stage == "stage_1":
            hours *= config.patent_stage_1_ratio
        elif patent_stage == "stage_2":
            hours *= config.patent_stage_2_ratio
        else:
            # Khong co giai doan hop le -> 0 gio (bat buoc chon)
            hours = 0.0

    return hours


def calculate_author_hours(
    base_hours: float,
    author_role: str,
    total_authors: int,
    contribution_percentage: Optional[float] = None,
) -> float:
    """
    Tinh so gio cua tac gia dua tren vai tro.

    Quy tac theo Hoi dong Giao su Nha nuoc:
    - 2/3 gio chia deu cho tat ca tac gia
    - 1/3 gio bonus cho tac gia chinh:
      + Tac gia dau: +1/6
      + Tac gia lien he: +1/6
      + Tac gia dau + lien he (cung nguoi): +1/3

    Args:
        base_hours: So gio co ban
        author_role: first, corresponding, first_corresponding, middle
        total_authors: Tong so tac gia
        contribution_percentage: % dong gop (override, 0-100)

    Returns:
        So gio cua tac gia
    """
    if base_hours <= 0:
        return 0.0

    # Neu co contribution_percentage thi dung truc tiep
    if contribution_percentage is not None and contribution_percentage > 0:
        return base_hours * (contribution_percentage / 100.0)

    if total_authors <= 0:
        total_authors = 1

    # 2/3 chia deu cho tat ca tac gia
    base_share = base_hours * (2.0 / 3.0) / total_authors

    # 1/3 bonus cho tac gia chinh
    bonus_share = 0.0
    role = (author_role or "middle").lower()

    if role == "first_corresponding":
        # Tac gia dau dong thoi la tac gia lien he
        bonus_share = base_hours * (1.0 / 3.0)
    elif role in ("first", "corresponding"):
        # Chi la tac gia dau hoac chi la tac gia lien he
        bonus_share = base_hours * (1.0 / 6.0)
    # middle = 0 bonus

    return base_share + bonus_share


def calculate_publication_hours(
    pub: "Publication", config: HoursConfig = DEFAULT_CONFIG
) -> Dict[str, float]:
    """
    Tinh toan day du so gio cho mot an pham.

    Args:
        pub: Publication object
        config: Cau hinh so gio

    Returns:
        Dict voi base_hours va author_hours
    """
    base_hours = get_base_hours(
        publication_type=pub.publication_type,
        quartile=pub.quartile,
        domestic_points=pub.domestic_points or 0.0,
        patent_stage=pub.patent_stage,
        is_republished=pub.is_republished or False,
        config=config,
    )

    author_hours = calculate_author_hours(
        base_hours=base_hours,
        author_role=pub.author_role or "middle",
        total_authors=pub.total_authors or 1,
        contribution_percentage=pub.contribution_percentage,
    )

    return {
        "base_hours": round(base_hours, 2),
        "author_hours": round(author_hours, 2),
    }


def calculate_yearly_summary(
    publications: List["Publication"],
    year: Optional[int] = None,
    config: HoursConfig = DEFAULT_CONFIG,
) -> Dict:
    """
    Tinh tong hop theo nam.

    Args:
        publications: Danh sach an pham
        year: Nam (None = tat ca)
        config: Cau hinh so gio

    Returns:
        Dict voi thong ke chi tiet
    """
    if year:
        publications = [p for p in publications if p.year == year]

    total_base_hours = 0.0
    total_author_hours = 0.0
    by_type = {}
    by_quartile = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}

    for pub in publications:
        hours = calculate_publication_hours(pub, config)
        total_base_hours += hours["base_hours"]
        total_author_hours += hours["author_hours"]

        # Group by type
        pub_type = pub.publication_type
        if pub_type not in by_type:
            by_type[pub_type] = {"count": 0, "hours": 0.0}
        by_type[pub_type]["count"] += 1
        by_type[pub_type]["hours"] += hours["author_hours"]

        # Count quartiles
        if pub.quartile in by_quartile:
            by_quartile[pub.quartile] += 1

    return {
        "year": year,
        "total_publications": len(publications),
        "total_base_hours": round(total_base_hours, 2),
        "total_author_hours": round(total_author_hours, 2),
        "by_type": by_type,
        "by_quartile": by_quartile,
        "wos_scopus_count": sum(by_quartile.values()),
    }


# =============================================================================
# PUBLICATION TYPE OPTIONS FOR FORMS
# =============================================================================

PUBLICATION_TYPE_CHOICES = [
    # 1. Bài báo khoa học
    ("journal_wos_scopus", "1.1 - Tạp chí WoS/Scopus (Q1-Q4)"),
    (
        "journal_vnu_special",
        "1.2a - Chuyên san VNU (phê duyệt đầu tư đạt chuẩn Scopus)",
    ),
    ("journal_rev", "1.2b - Tạp chí Điện tử Truyền thông (REV)"),
    (
        "journal_international_reputable",
        "1.3 - Tạp chí quốc tế uy tín (ngoài WoS/Scopus)",
    ),
    ("journal_domestic", "1.4 - Tạp chí trong nước"),
    # 2. Báo cáo hội nghị
    ("conference_wos_scopus", "2.1 - Hội nghị WoS/Scopus"),
    ("conference_international", "2.2 - Hội nghị quốc tế"),
    ("conference_national", "2.3 - Hội nghị quốc gia"),
    # 3. Sách
    ("monograph_international", "3.1 - Sách chuyên khảo quốc tế"),
    ("monograph_domestic", "3.2 - Sách chuyên khảo trong nước"),
    ("textbook_international", "3.3 - Giáo trình quốc tế"),
    ("textbook_domestic", "3.4 - Giáo trình trong nước"),
    ("book_chapter_reputable", "3.5 - Chương sách (NXB uy tín)"),
    ("book_chapter_international", "3.6 - Chương sách quốc tế"),
    # 4. Sở hữu trí tuệ
    ("patent_international", "4.1 - Bằng sáng chế quốc tế"),
    ("patent_vietnam", "4.2 - Bằng sáng chế Việt Nam"),
    ("utility_solution", "4.3 - Giải pháp hữu ích"),
    ("award_international", "4.4a - Giải thưởng quốc tế"),
    ("award_national", "4.4b - Giải thưởng quốc gia"),
    ("exhibition_international", "4.5a - Triển lãm quốc tế"),
    ("exhibition_national", "4.5b - Triển lãm quốc gia"),
    ("exhibition_provincial", "4.5c - Triển lãm cấp tỉnh"),
]

QUARTILE_CHOICES = [
    ("Q1", "Q1"),
    ("Q2", "Q2"),
    ("Q3", "Q3"),
    ("Q4", "Q4"),
]

AUTHOR_ROLE_CHOICES = [
    ("first", "Tác giả đầu"),
    ("corresponding", "Tác giả liên hệ"),
    ("first_corresponding", "Tác giả đầu + Liên hệ"),
    ("middle", "Đồng tác giả"),
]

PATENT_STAGE_CHOICES = [
    ("stage_1", "Giai đoạn 1 – Đơn đăng ký được chấp nhận (1/3 giờ)"),
    ("stage_2", "Giai đoạn 2 – Được cấp bằng văn bản (2/3 giờ)"),
]


# =============================================================================
# HOURS REFERENCE TABLE (for display)
# =============================================================================

# =============================================================================
# PROJECT HOURS CALCULATOR (BẢNG 2, MỤC 1-2)
# =============================================================================


def calculate_project_hours(
    project_level: str,
    role: str,
    funding_amount: float = 0.0,
    duration_years: int = 1,
    status: str = "completed",
    total_members: int = 1,
    config: HoursConfig = DEFAULT_CONFIG,
) -> Dict[str, float]:
    """
    Tính số giờ cho đề tài/dự án.

    QUAN TRONG: Theo quy chế, cột "Thành viên" là TỔNG giờ cho TẤT CẢ thành viên khác,
    không phải giờ cho MỖI thành viên. Vì vậy cần chia đều cho số thành viên khác.

    Ví dụ: Đề tài cấp Nhà nước, 5 người (1 chủ trì + 1 thư ký + 3 thành viên khác)
    - Chủ trì: 500 giờ
    - Thư ký: 250 giờ
    - Mỗi thành viên khác: 250 / 3 = 83.33 giờ

    Args:
        project_level: national, vnu_ministry, university, cooperation
        role: leader, secretary, member
        funding_amount: Giá trị tài trợ (ty đồng) - chỉ dùng cho cooperation
        duration_years: Số năm thực hiện - chỉ dùng cho cooperation
        status: ongoing, completed, extended
        total_members: Tổng số thành viên (bao gồm chủ trì, thư ký và thành viên khác)
        config: Cấu hình số giờ
    Returns:
        Dict với total_hours, user_hours và chi tiết phân chia
    """
    # Đề tài gia hạn không tính giờ (theo quy chế mục f)
    if status == "extended":
        return {
            "total_hours": 0.0,
            "user_hours": 0.0,
            "leader_hours": 0.0,
            "secretary_hours": 0.0,
            "member_pool_hours": 0.0,
            "member_each_hours": 0.0,
            "other_members_count": 0,
        }

    total_hours = 0.0
    leader_hours = 0.0
    secretary_hours = 0.0
    member_pool_hours = 0.0  # TỔNG giờ cho TẤT CẢ thành viên khác (chia đều)
    user_hours = 0.0

    if project_level == "national":
        total_hours = config.hours_project_national_total  # 1000
        leader_hours = config.hours_project_national_leader  # 500
        secretary_hours = config.hours_project_national_secretary  # 250
        member_pool_hours = (
            config.hours_project_national_member
        )  # 250 (TỔNG cho tất cả TV khác)

    elif project_level == "vnu_ministry":
        total_hours = config.hours_project_vnu_total  # 800
        leader_hours = config.hours_project_vnu_leader  # 400
        secretary_hours = config.hours_project_vnu_secretary  # 200
        member_pool_hours = (
            config.hours_project_vnu_member
        )  # 200 (TỔNG cho tất cả TV khác)

    elif project_level == "university":
        total_hours = config.hours_project_university_total  # 300
        leader_hours = config.hours_project_university_leader  # 300
        secretary_hours = 0.0
        member_pool_hours = 0.0  # Cấp trường chỉ có chủ trì

    elif project_level == "cooperation":
        # Công thức: 100 + 1000 * (giá trị tỷ đồng) / số năm
        if duration_years <= 0:
            duration_years = 1
        total_hours = (
            config.cooperation_base_hours
            + config.cooperation_multiplier * funding_amount / duration_years
        )
        leader_hours = total_hours * config.cooperation_leader_ratio  # 50%
        secretary_hours = total_hours * config.cooperation_secretary_ratio  # 25%
        member_pool_hours = (
            total_hours * config.cooperation_member_ratio
        )  # 25% (TỔNG cho tất cả TV khác)

    # Tính số thành viên khác (trừ chủ trì và thư ký)
    if project_level == "university":
        other_members_count = 0  # Cấp trường chỉ có chủ trì
    else:
        # Tổng thành viên - 1 chủ trì - 1 thư ký = số thành viên khác
        other_members_count = max(0, total_members - 2)

    # Tính giờ cho mỗi thành viên khác (chia đều từ member_pool_hours)
    member_each_hours = 0.0
    if other_members_count > 0 and member_pool_hours > 0:
        member_each_hours = member_pool_hours / other_members_count

    # Tính giờ cho người dùng dựa trên vai trò
    if role == "leader":
        user_hours = leader_hours
    elif role == "secretary":
        user_hours = secretary_hours
    else:  # member
        user_hours = member_each_hours

    return {
        "total_hours": round(total_hours, 2),
        "user_hours": round(user_hours, 2),
        "leader_hours": round(leader_hours, 2),
        "secretary_hours": round(secretary_hours, 2),
        "member_pool_hours": round(member_pool_hours, 2),  # Tổng giờ cho tất cả TV khác
        "member_each_hours": round(member_each_hours, 2),  # Giờ cho mỗi TV khác
        "other_members_count": other_members_count,
    }


def calculate_project_hours_from_model(
    project: "Project", config: HoursConfig = DEFAULT_CONFIG
) -> Dict[str, float]:
    """
    Tinh gio tu Project model (tổng giờ toàn bộ đề tài).
    """
    return calculate_project_hours(
        project_level=project.project_level,
        role=project.role,
        funding_amount=project.funding_amount or 0.0,
        duration_years=project.duration_years or 1,
        status=project.status or "completed",
        total_members=project.total_members or 1,
        config=config,
    )


def calculate_project_hours_per_year(
    project: "Project", config: HoursConfig = DEFAULT_CONFIG
) -> float:
    """
    Tính giờ đề tài cho MỖI NĂM khi thống kê theo năm.

    - Đề tài hợp tác (cooperation): Công thức đã chia cho duration_years,
      nên kết quả ĐÃ LÀ giờ/năm → giữ nguyên, không chia thêm.
    - Đề tài cấp Nhà nước/ĐHQGHN/Bộ/Trường: Giờ là TỔNG cho toàn bộ đề tài,
      cần chia đều cho số năm xuất hiện (end_year - start_year + 1).

    Ví dụ: Đề tài cấp Nhà nước, chủ trì, start_year=2024, end_year=2025
    - Tổng user_hours = 500
    - Số năm xuất hiện = 2 (2024, 2025)
    - Giờ mỗi năm = 500 / 2 = 250
    """
    hours = calculate_project_hours_from_model(project, config)
    user_hours = hours["user_hours"]
    if user_hours == 0:
        return 0.0

    # Đề tài hợp tác: công thức đã chia cho duration_years → kết quả là giờ/năm
    if project.project_level == "cooperation":
        return round(user_hours, 2)

    # Các cấp khác: chia đều cho số năm xuất hiện
    span_years = max(1, project.end_year - project.start_year + 1)
    return round(user_hours / span_years, 2)


# =============================================================================
# OTHER ACTIVITY HOURS CALCULATOR (BẢNG 2, MỤC 3)
# =============================================================================


def calculate_other_activity_hours(
    activity_type: str,
    quantity: int = 1,
    config: HoursConfig = DEFAULT_CONFIG,
) -> float:
    """
    Tính số giờ cho hoạt động KHCN khác.

    ưu ý: Tối đa 250 giờ/năm cho toàn bộ mục 3.

    Args:
        activity_type: Loại hoạt động
        quantity: Số lượng (nhóm, đội, sản phẩm)
        config: Cấu hình số giờ

    Returns:
        Số giờ
    """
    hours_per_unit = 0.0

    if activity_type == "student_research_university":
        hours_per_unit = config.hours_student_research_university  # 75/nhóm
    elif activity_type == "student_research_faculty":
        hours_per_unit = config.hours_student_research_faculty  # 30/nhóm
    elif activity_type == "team_training":
        hours_per_unit = config.hours_team_training  # 75/đội
    elif activity_type == "exhibition_product":
        hours_per_unit = config.hours_exhibition_product  # 45/sản phẩm

    return round(hours_per_unit * quantity, 2)


def calculate_other_activity_hours_from_model(
    activity: "OtherActivity", config: HoursConfig = DEFAULT_CONFIG
) -> float:
    """
    Tinh gio tu OtherActivity model.
    """
    return calculate_other_activity_hours(
        activity_type=activity.activity_type,
        quantity=activity.quantity or 1,
        config=config,
    )


def calculate_yearly_other_activities_total(
    activities: List["OtherActivity"],
    year: int,
    config: HoursConfig = DEFAULT_CONFIG,
) -> Dict:
    """
    Tính tổng giờ hoạt động KHCN khác trong năm.
    Áp dụng giới hạn tối đa 250 giờ/năm.
    """
    year_activities = [a for a in activities if a.year == year]

    total_raw_hours = 0.0
    by_type = {}

    for act in year_activities:
        hours = calculate_other_activity_hours_from_model(act, config)
        total_raw_hours += hours

        if act.activity_type not in by_type:
            by_type[act.activity_type] = {"count": 0, "hours": 0.0}
        by_type[act.activity_type]["count"] += act.quantity or 1
        by_type[act.activity_type]["hours"] += hours

    # Áp dụng giới hạn 250 giờ/năm
    capped_hours = min(total_raw_hours, config.other_activity_max_hours_per_year)

    return {
        "year": year,
        "total_raw_hours": round(total_raw_hours, 2),
        "capped_hours": round(capped_hours, 2),
        "is_capped": total_raw_hours > config.other_activity_max_hours_per_year,
        "by_type": by_type,
        "activity_count": len(year_activities),
    }


# =============================================================================
# TỔNG HỢP TẤT CẢ GIỜ NGHIÊN CỨU
# =============================================================================


def calculate_total_research_hours(
    publications: List["Publication"],
    projects: List["Project"],
    other_activities: List["OtherActivity"],
    year: Optional[int] = None,
    config: HoursConfig = DEFAULT_CONFIG,
) -> Dict:
    """
    Tính tổng hợp tất cả giờ nghiên cứu (an phẩm + đề tài + hoạt động khác).
    """
    # 1. Ấn phẩm khoa học (Bảng 1)
    pub_summary = calculate_yearly_summary(publications, year, config)

    # 2. Đề tài, dự án (Bảng 2, Mục 1-2)
    if year:
        year_projects = [p for p in projects if p.start_year <= year <= p.end_year]
    else:
        year_projects = projects

    project_hours = 0.0
    if year:
        # Chia đều giờ cho mỗi năm trong khoảng start_year..end_year
        for proj in year_projects:
            project_hours += calculate_project_hours_per_year(proj, config)
    else:
        # Tổng hợp tất cả: tính tổng giờ (không chia)
        for proj in year_projects:
            hours = calculate_project_hours_from_model(proj, config)
            project_hours += hours["user_hours"]

    # 3. Hoạt động KHCN khác (Bảng 2, mục 3)
    if year:
        other_summary = calculate_yearly_other_activities_total(
            other_activities, year, config
        )
        other_hours = other_summary["capped_hours"]
    else:
        # Tính tổng tất cả các năm với cấp riêng từng năm
        years = sorted(set(a.year for a in other_activities))
        other_hours = 0.0
        for y in years:
            y_summary = calculate_yearly_other_activities_total(
                other_activities, y, config
            )
            other_hours += y_summary["capped_hours"]

    # Tổng hợp
    total_hours = pub_summary["total_author_hours"] + project_hours + other_hours

    return {
        "year": year,
        "publication_hours": pub_summary["total_author_hours"],
        "publication_count": pub_summary["total_publications"],
        "project_hours": round(project_hours, 2),
        "project_count": len(year_projects),
        "other_activity_hours": round(other_hours, 2),
        "total_hours": round(total_hours, 2),
    }


HOURS_REFERENCE = {
    "journal_wos_scopus_q1_q2": {
        "name": "1.1 - Tạp chí WoS/Scopus Q1/Q2",
        "hours": 1800,
    },
    "journal_wos_scopus_q3_q4": {
        "name": "1.1 - Tạp chí WoS/Scopus Q3/Q4",
        "hours": 1400,
    },
    "journal_vnu_special": {
        "name": "1.2a - Chuyên san VNU (đạt chuẩn Scopus)",
        "hours": 900,
    },
    "journal_rev": {"name": "1.2b - Tạp chí Điện tử Truyền thông (REV)", "hours": 900},
    "journal_international_reputable": {
        "name": "1.3 - Tạp chí quốc tế uy tín (ngoài WoS/Scopus)",
        "hours": 900,
    },
    "journal_domestic_gte_1": {
        "name": "1.4a - Tạp chí trong nước >= 1 điểm",
        "hours": 800,
    },
    "journal_domestic_gte_05": {
        "name": "1.4b - Tạp chí trong nước >= 0.5 điểm",
        "hours": 600,
    },
    "journal_domestic_lt_05": {
        "name": "1.4c - Tạp chí trong nước < 0.5 điểm",
        "hours": 300,
    },
    "conference_wos_scopus": {"name": "Hội nghị WoS/Scopus", "hours": 900},
    "conference_international": {"name": "Hội nghị quốc tế", "hours": 600},
    "conference_national": {"name": "Hội nghị quốc gia", "hours": 500},
    "monograph_international": {"name": "Sách chuyên khảo quốc tế", "hours": 2700},
    "monograph_domestic": {"name": "Sách chuyên khảo trong nước", "hours": 1500},
    "textbook_international": {"name": "Giáo trình quốc tế", "hours": 1800},
    "textbook_domestic": {"name": "Giáo trình trong nước", "hours": 900},
    "book_chapter_reputable": {"name": "Chương sách (NXB uy tín)", "hours": 1200},
    "book_chapter_international": {"name": "Chương sách quốc tế", "hours": 900},
    "patent_international": {"name": "Bằng sáng chế quốc tế", "hours": 3000},
    "patent_vietnam": {"name": "Bằng sáng chế Việt Nam", "hours": 1800},
    "utility_solution": {"name": "Giải pháp hữu ích", "hours": 1200},
    "award_international": {"name": "Giải thưởng quốc tế", "hours": 1800},
    "award_national": {"name": "Giải thưởng quốc gia", "hours": 1200},
    "exhibition_international": {"name": "Triển lãm quốc tế", "hours": 900},
    "exhibition_national": {"name": "Triển lãm quốc gia", "hours": 600},
    "exhibition_provincial": {"name": "Triển lãm cấp tỉnh", "hours": 400},
}


# =============================================================================
# BANG 2 - CHOICES VA REFERENCE
# =============================================================================

PROJECT_LEVEL_CHOICES = [
    ("national", "1.1 - Đề tài cấp Nhà nước và tương đương"),
    ("vnu_ministry", "1.2 - Đề tài cấp ĐHQGHN/Bộ và tương đương"),
    ("university", "1.3 - Đề tài cấp Trường hoặc tương đương"),
    ("cooperation", "2 - Đề tài hợp tác, dịch vụ KH&CN"),
]

PROJECT_ROLE_CHOICES = [
    ("leader", "Chủ trì"),
    ("secretary", "Thư ký khoa học"),
    ("member", "Thành viên"),
]

PROJECT_STATUS_CHOICES = [
    ("ongoing", "Đang thực hiện"),
    ("completed", "Đã nghiệm thu"),
    ("extended", "Gia hạn (không tính giờ)"),
]

OTHER_ACTIVITY_TYPE_CHOICES = [
    ("student_research_university", "3.1a - Hướng dẫn SV NCKH (cấp trường trở lên)"),
    ("student_research_faculty", "3.1b - Hướng dẫn SV NCKH (cấp khoa)"),
    ("team_training", "3.2 - Huấn luyện đội tuyển SV tham dự cuộc thi NCKH"),
    ("exhibition_product", "3.3 - Sản phẩm KHCN tham gia triển lãm/cuộc thi"),
]

# Bảng quy đổi giờ cho Bảng 2
HOURS_REFERENCE_TABLE2 = {
    "project_national": {
        "name": "1.1 - Đề tài cấp Nhà nước",
        "total": 1000,
        "leader": 500,
        "secretary": 250,
        "member": 250,
    },
    "project_vnu_ministry": {
        "name": "1.2 - Đề tài cấp ĐHQGHN/Bộ",
        "total": 800,
        "leader": 400,
        "secretary": 200,
        "member": 200,
    },
    "project_university": {
        "name": "1.3 - Đề tài cấp Trường",
        "total": 300,
        "leader": 300,
        "secretary": "-",
        "member": "-",
    },
    "project_cooperation": {
        "name": "2 - Đề tài hợp tác/Dịch vụ KHCN",
        "formula": "100 + 1000×(giá trị tỷ đồng)/số năm",
        "leader": "50%",
        "secretary": "25%",
        "member": "25%",
    },
    "student_research_university": {
        "name": "3.1a - Hướng dẫn SV NCKH (cấp trường)",
        "hours": 75,
        "unit": "nhóm",
    },
    "student_research_faculty": {
        "name": "3.1b - Hướng dẫn SV NCKH (cấp khoa)",
        "hours": 30,
        "unit": "nhóm",
    },
    "team_training": {
        "name": "3.2 - Huấn luyện đội tuyển SV",
        "hours": 75,
        "unit": "đội tuyển",
    },
    "exhibition_product": {
        "name": "3.3 - Sản phẩm KHCN triển lãm/cuộc thi",
        "hours": 45,
        "unit": "sản phẩm",
    },
}
