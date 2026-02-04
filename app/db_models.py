"""
Database models for VNU-UET Research Hours Web Application.
Supports all publication types from the official regulation (Quy che).
"""

import re
from sqlalchemy.orm import object_session

from datetime import datetime
from enum import Enum
from sqlalchemy import inspect, text, select

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


# =============================================================================
# SHARED VALIDATORS
# =============================================================================

# Password: >= 8 ký tự, bắt đầu bằng chữ, có ít nhất 1 chữ số và 1 ký tự đặc biệt
_PASSWORD_RE = re.compile(r"^[A-Za-z](?=.*\d)(?=.*[^A-Za-z0-9]).{7,}$")
PASSWORD_POLICY_MSG = (
    "Mật khẩu phải có ít nhất 8 ký tự, bắt đầu bằng chữ cái, "
    "chứa ít nhất 1 chữ số và 1 ký tự đặc biệt."
)

# Email: basic RFC 5322 format validation
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
EMAIL_POLICY_MSG = "Email không hợp lệ. Vui lòng nhập đúng định dạng (vd: ten@domain.com)."

# Mã cán bộ: chữ cái viết hoa + số, ví dụ CB090708
_EMPLOYEE_ID_RE = re.compile(r"^[A-Z]{1,5}\d{4,10}$")
EMPLOYEE_ID_POLICY_MSG = (
    "Mã cán bộ phải gồm 1-5 chữ cái viết hoa và 4-10 chữ số (ví dụ: CB090708)."
)


def validate_password(password: str) -> str | None:
    """Return error message if invalid, else None."""
    if not password or not _PASSWORD_RE.match(password):
        return PASSWORD_POLICY_MSG
    return None


def validate_email(email: str) -> str | None:
    """Return error message if invalid, else None."""
    if not email or not _EMAIL_RE.match(email):
        return EMAIL_POLICY_MSG
    if len(email) > 254:
        return "Email quá dài (tối đa 254 ký tự)."
    return None


def validate_employee_id(employee_id: str) -> str | None:
    """Return error message if invalid, else None. Empty string is acceptable."""
    if not employee_id:
        return None
    if not _EMPLOYEE_ID_RE.match(employee_id):
        return EMPLOYEE_ID_POLICY_MSG
    return None


# =============================================================================
# APPROVAL STATUS ENUM
# =============================================================================


class ApprovalStatus(str, Enum):
    """Trạng thái duyệt - Quy trình 3 cấp"""

    DRAFT = "draft"  # Nháp (chưa gửi duyệt)
    PENDING = "pending"  # Chờ Bộ môn xác nhận
    DEPARTMENT_APPROVED = "department_approved"  # Bộ môn đã xác nhận, chờ Khoa
    FACULTY_APPROVED = "faculty_approved"  # Khoa đã duyệt, chờ Trường/PKHCN
    APPROVED = "approved"  # Đã phê duyệt (hoàn tất)
    RETURNED = "returned"  # Đã trả lại (cần sửa)


# Map trạng thái duyệt → nhãn hiển thị (UI)
APPROVAL_STATUS_DISPLAY_MAP = {
    "draft": "Nháp",
    "pending": "Chờ duyệt (Bộ môn)",
    "department_approved": "Đã xác nhận (Bộ môn) / Chờ duyệt (Khoa)",
    "faculty_approved": "Đã duyệt (Khoa) / Chờ phê duyệt (Trường)",
    "approved": "Đã phê duyệt",
    "returned": "Bị trả lại",
}


def approval_status_to_display(status: str) -> str:
    return APPROVAL_STATUS_DISPLAY_MAP.get(status or "", status or "")


class AdminLevel(str, Enum):
    """Cấp độ admin - Phân quyền 3 cấp"""

    NONE = "none"  # Không phải admin (user thường)
    DEPARTMENT = "department"  # Admin cấp Bộ môn
    FACULTY = "faculty"  # Admin cấp Khoa
    UNIVERSITY = "university"  # Admin cấp Trường (PKHCN)


# =============================================================================
# ENUMS - Loại ấn phẩm theo Quy chế
# =============================================================================


class PublicationType(str, Enum):
    """Loại ấn phẩm khoa học"""

    # 1. Bài báo khoa học
    JOURNAL_WOS_SCOPUS = "journal_wos_scopus"  # 1.1 - WoS/Scopus Q1-Q4
    JOURNAL_VNU_SPECIAL = "journal_vnu_special"  # 1.2a - Chuyên san VNU
    JOURNAL_REV = "journal_rev"  # 1.2b - Tạp chí Điện tử Truyền thông (REV)
    JOURNAL_INTERNATIONAL_REPUTABLE = "journal_international_reputable"  # 1.3 - Tạp chí quốc tế uy tín ngoài WoS/Scopus
    JOURNAL_DOMESTIC = "journal_domestic"  # 1.4 - Tạp chí trong nước

    # 2. Báo cáo khoa học
    CONFERENCE_WOS_SCOPUS = "conference_wos_scopus"
    CONFERENCE_INTERNATIONAL = "conference_international"
    CONFERENCE_NATIONAL = "conference_national"

    # 3. Sách, giáo trình
    MONOGRAPH_INTERNATIONAL = "monograph_international"
    MONOGRAPH_DOMESTIC = "monograph_domestic"
    TEXTBOOK_INTERNATIONAL = "textbook_international"
    TEXTBOOK_DOMESTIC = "textbook_domestic"
    BOOK_CHAPTER_REPUTABLE = "book_chapter_reputable"
    BOOK_CHAPTER_INTERNATIONAL = "book_chapter_international"

    # 4. Sản phẩm sở hữu trí tuệ
    PATENT_INTERNATIONAL = "patent_international"
    PATENT_VIETNAM = "patent_vietnam"
    UTILITY_SOLUTION = "utility_solution"

    # 4.4 Giải thưởng
    AWARD_INTERNATIONAL = "award_international"
    AWARD_NATIONAL = "award_national"

    # 4.5 Triển lãm
    EXHIBITION_INTERNATIONAL = "exhibition_international"
    EXHIBITION_NATIONAL = "exhibition_national"
    EXHIBITION_PROVINCIAL = "exhibition_provincial"


class JournalQuartile(str, Enum):
    """Phân hạng tạp chí WoS/Scopus"""

    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


class AuthorRole(str, Enum):
    """Vai trò tác giả"""

    FIRST = "first"
    CORRESPONDING = "corresponding"
    FIRST_CORRESPONDING = "first_corresponding"
    MIDDLE = "middle"


class PatentStage(str, Enum):
    """Giai đoạn sáng chế"""

    STAGE_1 = "stage_1"  # Đơn đăng ký được chấp nhận: 1/3 giờ
    STAGE_2 = "stage_2"  # Được cấp bằng: 2/3 giờ
    GRANTED = "granted"  # Đã được cấp bằng: 100% giờ


# =============================================================================
# ENUMS CHO BẢNG 2 - HOẠT ĐỘNG KHCN
# =============================================================================


class ProjectLevel(str, Enum):
    """Cap de tai/dự án - Mục 1 Bảng 2"""

    NATIONAL = "national"  # 1.1 - Cấp Nhà nước và tương đương
    VNU_MINISTRY = "vnu_ministry"  # 1.2 - Cấp ĐHQGHN, cấp Bộ và tương đương
    UNIVERSITY = "university"  # 1.3 - Cấp Trường hoặc tương đương
    COOPERATION = "cooperation"  # 2 - Đề tài hợp tác, dịch vụ KHCN


class ProjectRole(str, Enum):
    """Vai trò trong đề tài/dự án"""

    LEADER = "leader"  # Chủ trì
    SECRETARY = "secretary"  # Thư ký khoa học
    MEMBER = "member"  # Thành viên


class ProjectStatus(str, Enum):
    """Trạng thái đề tài"""

    ONGOING = "ongoing"  # Đang thực hiện
    COMPLETED = "completed"  # Đã nghiệm thu
    EXTENDED = "extended"  # Gia hạn (không tính giờ)


class UnitType(str, Enum):
    """Loại đơn vị tổ chức"""

    FACULTY = "faculty"  # Khoa - yêu cầu Bộ môn
    OFFICE = "office"  # Phòng ban - không yêu cầu Bộ môn


class OtherActivityType(str, Enum):
    """Loại hoạt động KHCN khác - Mục 3 Bảng 2"""

    STUDENT_RESEARCH_UNIVERSITY = (
        "student_research_university"  # 3.1a - HD SV NCKH cấp trường
    )
    STUDENT_RESEARCH_FACULTY = "student_research_faculty"  # 3.1b - HD SV NCKH cấp khoa
    TEAM_TRAINING = "team_training"  # 3.2 - Huấn luyện đội tuyển
    EXHIBITION_PRODUCT = "exhibition_product"  # 3.3 - Sản phẩm triển lãm KHCN


# =============================================================================
# DEPARTMENT MODEL - Bộ môn/Đơn vị (Legacy - kept for backwards compatibility)
# =============================================================================


class Department(db.Model):
    """Bộ môn/Đơn vị trong Khoa (Legacy model)"""

    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    code = db.Column(db.String(20), unique=True)  # Mã bộ môn
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<Department {self.name}>"

    @property
    def member_count(self):
        """Số thành viên trong bộ môn"""
        return User.query.filter_by(department_id=self.id, is_active=True).count()


# =============================================================================
# ORGANIZATION UNIT MODEL - Khoa/Phòng ban
# =============================================================================


class OrganizationUnit(db.Model):
    """Khoa/Phòng ban - Đơn vị cấp cao nhất"""

    __tablename__ = "organization_units"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    code = db.Column(db.String(20), unique=True)  # Mã đơn vị (VD: CK, DT, PDT)
    unit_type = db.Column(
        db.Enum(
            UnitType,
            name="unit_type_enum",
            values_callable=lambda enum_cls: [
                e.value for e in enum_cls
            ],  # lưu 'faculty'/'office'
            native_enum=False,
            validate_strings=True,
        ),
        nullable=False,
        default=UnitType.FACULTY.value,
    )
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    divisions = db.relationship(
        "Division",
        backref="organization_unit",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<OrganizationUnit {self.name}>"

    @property
    def unit_type_display(self) -> str:
        """Tên hiển thị loại đơn vị"""
        return "Khoa" if self.unit_type == "faculty" else "Phòng ban"

    @property
    def member_count(self):
        """Số thành viên trong đơn vị"""
        return User.query.filter_by(
            organization_unit_id=self.id, is_active=True
        ).count()

    @property
    def division_count(self):
        """Số bộ môn trong đơn vị"""
        return self.divisions.filter_by(is_active=True).count()

    @property
    def requires_division(self) -> bool:
        """Kiểm tra đơn vị có yêu cầu Bộ môn không"""
        return self.unit_type == "faculty"


# =============================================================================
# DIVISION MODEL - Bộ môn (thuộc Khoa)
# =============================================================================


class Division(db.Model):
    """Bộ môn - thuộc về Khoa"""

    __tablename__ = "divisions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(20))  # Mã bộ môn (VD: CHKT, CDT)
    organization_unit_id = db.Column(
        db.Integer, db.ForeignKey("organization_units.id"), nullable=False, index=True
    )
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Unique constraint: name unique within organization unit
    __table_args__ = (
        db.UniqueConstraint(
            "name", "organization_unit_id", name="uq_division_name_org"
        ),
        # Ensure division code is unique within an organization unit
        db.UniqueConstraint(
            "code", "organization_unit_id", name="uq_division_code_org"
        ),
        db.Index("idx_division_org_unit", "organization_unit_id"),
    )

    def __repr__(self):
        return f"<Division {self.name}>"

    @property
    def full_name(self) -> str:
        """Tên đầy đủ bao gồm tên Khoa"""
        return f"{self.name} ({self.organization_unit.name})"

    @property
    def member_count(self):
        """Số thành viên trong bộ môn"""
        return User.query.filter_by(division_id=self.id, is_active=True).count()


# =============================================================================
# USER MODEL
# =============================================================================


class User(UserMixin, db.Model):
    """Người dùng hệ thống"""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))  # Giữ lại cho backwards compatibility
    department_id = db.Column(
        db.Integer, db.ForeignKey("departments.id"), nullable=True
    )  # FK đến bộ môn (legacy)

    # New organizational structure
    organization_unit_id = db.Column(
        db.Integer, db.ForeignKey("organization_units.id"), nullable=True, index=True
    )  # FK đến Khoa/Phòng ban
    division_id = db.Column(
        db.Integer, db.ForeignKey("divisions.id"), nullable=True, index=True
    )  # FK đến Bộ môn (bắt buộc nếu là Khoa)

    employee_id = db.Column(
        db.String(50), unique=True, nullable=True
    )  # Mã cán bộ (unique khi có giá trị)

    avatar_filename = db.Column(db.String(255), nullable=True)  # Ảnh đại diện

    # Hệ thống phân quyền 3 cấp (thay thế is_admin)
    admin_level = db.Column(
        db.String(20), default="none", index=True
    )  # none, department, faculty, university

    # Giữ lại is_admin cho backwards compatibility (sẽ được tính từ admin_level)
    # is_admin = db.Column(db.Boolean, default=False)  # DEPRECATED - dùng admin_level

    is_active = db.Column(db.Boolean, default=True)
    failed_login_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship to Department (legacy)
    dept = db.relationship(
        "Department", backref="members", foreign_keys=[department_id]
    )

    # Relationships to new organizational structure
    org_unit = db.relationship(
        "OrganizationUnit", backref="users", foreign_keys=[organization_unit_id]
    )
    user_division = db.relationship(
        "Division", backref="users", foreign_keys=[division_id]
    )

    # Relationships - chi dinh foreign_keys vi co nhieu FK tro den User
    publications = db.relationship(
        "Publication",
        backref="author",
        lazy="dynamic",
        foreign_keys="Publication.user_id",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email}>"

    @property
    def organization_unit_name(self) -> str:
        """Tên Khoa/Phòng ban"""
        if self.org_unit:
            return self.org_unit.name
        return self.department or "Chưa xác định"

    @property
    def division_name(self) -> str:
        """Tên Bộ môn"""
        if self.user_division:
            return self.user_division.name
        return ""

    @property
    def full_organization_name(self) -> str:
        """Tên đầy đủ đơn vị (Bộ môn - Khoa/Phòng ban)"""
        parts = []
        if self.user_division:
            parts.append(self.user_division.name)
        if self.org_unit:
            parts.append(self.org_unit.name)
        elif self.department:
            parts.append(self.department)
        return " - ".join(parts) if parts else "Chưa xác định"

    # =========================================================================
    # PHÂN QUYỀN 3 CẤP - Properties và Methods
    # =========================================================================

    @property
    def is_admin(self) -> bool:
        """Backwards compatible - True nếu có bất kỳ quyền admin nào"""
        # Ưu tiên kiểm tra từ AdminRole table (mới)
        if hasattr(self, "roles") and self.roles:
            for role in self.roles:
                if role.is_active:
                    return True
        return False

    @property
    def admin_level_display(self) -> str:
        """Tên hiển thị cấp admin cao nhất"""
        highest = self.highest_admin_level
        display_names = {
            "none": "Người dùng",
            "department": "Admin Bộ môn",
            "faculty": "Admin Khoa",
            "university": "Admin Trường",
        }
        return display_names.get(highest, "Không xác định")

    @property
    def admin_level_hierarchy(self) -> int:
        """Thứ tự cấp bậc admin cao nhất (0=none, 1=department, 2=faculty, 3=university)"""
        hierarchy = {"none": 0, "department": 1, "faculty": 2, "university": 3}
        return hierarchy.get(self.highest_admin_level, 0)

    @property
    def highest_admin_level(self) -> str:
        """Lấy cấp admin cao nhất của user (từ AdminRole hoặc admin_level)"""
        # Kiểm tra từ AdminRole table trước
        if hasattr(self, "roles") and self.roles:
            hierarchy = {"university": 3, "faculty": 2, "department": 1}
            max_level = 0
            highest = "none"
            for role in self.roles:
                if role.is_active:
                    level = hierarchy.get(role.role_level, 0)
                    if level > max_level:
                        max_level = level
                        highest = role.role_level
            if highest != "none":
                return highest
        return "none"

    @property
    def active_admin_roles(self):
        """Danh sách các vai trò admin đang hoạt động"""
        if hasattr(self, "roles"):
            return [r for r in self.roles if r.is_active]
        return []

    @property
    def admin_roles_display(self) -> str:
        """Hiển thị tất cả vai trò admin"""
        roles = self.active_admin_roles
        if not roles:
            return "Người dùng"
        return ", ".join([r.full_display for r in roles])

    def has_admin_role(
        self, role_level: str, org_unit_id: int = None, division_id: int = None
    ) -> bool:
        """Kiểm tra user có vai trò admin cụ thể không"""
        for role in self.active_admin_roles:
            if role.role_level == role_level:
                if role_level == "university":
                    return True
                elif role_level == "faculty" and (
                    org_unit_id is None or role.organization_unit_id == org_unit_id
                ):
                    return True
                elif role_level == "department" and (
                    division_id is None or role.division_id == division_id
                ):
                    return True
        return False

    def is_higher_admin_than(self, other_user: "User") -> bool:
        """Kiểm tra có cấp admin cao hơn user khác không"""
        return self.admin_level_hierarchy > other_user.admin_level_hierarchy

    def can_view_admin(self, target_user: "User") -> bool:
        """Kiểm tra có quyền xem thông tin admin khác không"""
        if not self.is_admin:
            return False
        if not target_user.is_admin:
            return True  # Luôn xem được user thường

        # Admin cấp dưới không xem được admin cấp trên
        if self.admin_level_hierarchy < target_user.admin_level_hierarchy:
            return False

        return True

    def can_view_user(self, target_user: "User") -> bool:
        """Kiểm tra có quyền XEM thông tin user khác không"""
        if not self.is_admin:
            return False

        highest = self.highest_admin_level
        if highest == "university":
            return True  # Xem toàn trường
        elif highest == "faculty":
            # Xem trong Khoa hoặc có role faculty cho Khoa đó
            if target_user.organization_unit_id == self.organization_unit_id:
                return True
            # Kiểm tra có role faculty cho Khoa của target_user không
            if self.has_admin_role(
                "faculty", org_unit_id=target_user.organization_unit_id
            ):
                return True
        elif highest == "department":
            # Xem trong Bộ môn
            if target_user.division_id == self.division_id:
                return True
            # Kiểm tra có role department cho Bộ môn của target_user không
            if self.has_admin_role("department", division_id=target_user.division_id):
                return True
        return False

    def can_manage_user(self, target_user: "User") -> bool:
        """Kiểm tra có quyền SỬA thông tin user khác không"""
        if not self.is_admin:
            return False

        highest = self.highest_admin_level
        if highest == "university":
            return True  # Sửa toàn trường
        elif highest == "faculty":
            # Sửa trong Khoa hoặc có role faculty cho Khoa đó
            if target_user.organization_unit_id == self.organization_unit_id:
                return True
            if self.has_admin_role(
                "faculty", org_unit_id=target_user.organization_unit_id
            ):
                return True
        elif highest == "department":
            # Sửa trong Bộ môn
            if target_user.division_id == self.division_id:
                return True
            if self.has_admin_role("department", division_id=target_user.division_id):
                return True
        return False

    def can_assign_admin_level(self, target_level: str) -> bool:
        """Kiểm tra có thể GÁN cấp admin nào cho người khác"""
        # university có thể gán university, faculty, department
        # faculty có thể gán faculty, department (trong Khoa mình)
        # department không có quyền gán
        highest = self.highest_admin_level
        if highest == "university":
            return target_level in ["university", "faculty", "department", "none"]
        elif highest == "faculty":
            return target_level in ["faculty", "department", "none"]
        return False

    def can_approve_item(self, item, action: str) -> bool:
        """
        Kiểm tra có quyền thực hiện hành động duyệt trên item không.

        Args:
            item: Publication, Project, hoặc OtherActivity
            action: 'department_approve', 'faculty_approve', 'university_approve', 'return'
        """
        if not self.is_admin:
            return False

        # Lấy user sở hữu item
        item_user = User.query.get(item.user_id) if hasattr(item, "user_id") else None
        if not item_user:
            return False

        current_status = getattr(item, "approval_status", "pending")
        highest = self.highest_admin_level

        if action == "department_approve":
            # Admin Bộ môn xác nhận: pending → department_approved
            if current_status != "pending":
                return False
            # Kiểm tra có role department cho Bộ môn của item owner
            if self.has_admin_role("department", division_id=item_user.division_id):
                return True
            if highest == "department" and item_user.division_id == self.division_id:
                return True
            return False

        elif action == "faculty_approve":
            # Admin Khoa duyệt: department_approved → faculty_approved
            if current_status != "department_approved":
                return False
            # Kiểm tra có role faculty cho Khoa của item owner
            if self.has_admin_role(
                "faculty", org_unit_id=item_user.organization_unit_id
            ):
                return True
            if (
                highest == "faculty"
                and item_user.organization_unit_id == self.organization_unit_id
            ):
                return True
            return False

        elif action == "university_approve":
            # Admin Trường phê duyệt: faculty_approved → approved
            if current_status != "faculty_approved":
                return False
            if self.has_admin_role("university"):
                return True
            if highest == "university":
                return True
            return False

        elif action == "return":
            # Trả lại - mỗi cấp trả lại item trong phạm vi của mình
            if self.has_admin_role("university") or highest == "university":
                return True
            if self.has_admin_role(
                "faculty", org_unit_id=item_user.organization_unit_id
            ):
                return True
            if (
                highest == "faculty"
                and item_user.organization_unit_id == self.organization_unit_id
            ):
                return True
            if self.has_admin_role("department", division_id=item_user.division_id):
                return True
            if highest == "department" and item_user.division_id == self.division_id:
                return True

        return False

    def get_manageable_users_query(self, exclude_admins: bool = False):
        """
        Trả về query lọc users theo phạm vi quản lý.

        Args:
            exclude_admins: Nếu True, loại trừ các admin khỏi kết quả
        """
        highest = self.highest_admin_level
        if highest == "university":
            query = User.query
        elif highest == "faculty":
            query = User.query.filter_by(organization_unit_id=self.organization_unit_id)
        elif highest == "department":
            query = User.query.filter_by(division_id=self.division_id)
        else:
            return User.query.filter_by(id=-1)  # Empty query

        if exclude_admins:
            # Loại trừ users có AdminRole đang hoạt động
            active_admin_users_sq = (
                db.session.query(AdminRole.user_id)
                .filter(AdminRole.is_active == True)
                .subquery()
            )
            query = query.filter(~User.id.in_(select(active_admin_users_sq.c.user_id)))

        return query

    def get_viewable_users_query(self):
        """
        Trả về query lọc users mà admin này có quyền xem.
        Admin cấp dưới không xem được admin cấp trên.
        """
        highest = self.highest_admin_level

        if highest == "university":
            return User.query  # Xem tất cả
        elif highest == "faculty":
            # Xem users trong Khoa, loại trừ admin cấp cao hơn
            return User.query.filter(
                User.organization_unit_id == self.organization_unit_id,
                db.or_(
                    User.admin_level.in_(["none", "department", "faculty"]),
                    User.admin_level.is_(None),
                ),
            )
        elif highest == "department":
            # Xem users trong Bộ môn, loại trừ admin cấp cao hơn
            return User.query.filter(
                User.division_id == self.division_id,
                db.or_(
                    User.admin_level.in_(["none", "department"]),
                    User.admin_level.is_(None),
                ),
            )
        return User.query.filter_by(id=-1)  # Empty query

    def get_pending_items_for_approval(self, model_class):
        """
        Lấy danh sách items cần duyệt theo cấp admin.

        Args:
            model_class: Publication, Project, hoặc OtherActivity
        """
        from sqlalchemy import or_, and_

        highest = self.highest_admin_level
        if highest == "university" or self.has_admin_role("university"):
            # Admin Trường: faculty_approved (Khoa) + pending (Phòng ban)
            return (
                model_class.query.join(User, model_class.user_id == User.id)
                .join(
                    OrganizationUnit, User.organization_unit_id == OrganizationUnit.id
                )
                .filter(
                    or_(
                        and_(
                            model_class.approval_status == "faculty_approved",
                            OrganizationUnit.unit_type != "office",
                        ),
                        and_(
                            model_class.approval_status == "pending",
                            OrganizationUnit.unit_type == "office",
                        ),
                    )
                )
            )

        if highest == "faculty":
            # Admin Khoa: department_approved trong các Khoa được gán
            org_unit_ids = [
                r.organization_unit_id
                for r in self.active_admin_roles
                if r.role_level == "faculty" and r.organization_unit_id
            ]
            if not org_unit_ids and self.organization_unit_id:
                org_unit_ids = [self.organization_unit_id]
            if not org_unit_ids:
                return model_class.query.filter_by(id=-1)

            return (
                model_class.query.join(User, model_class.user_id == User.id)
                .join(
                    OrganizationUnit, User.organization_unit_id == OrganizationUnit.id
                )
                .filter(
                    model_class.approval_status == "department_approved",
                    User.organization_unit_id.in_(org_unit_ids),
                    OrganizationUnit.unit_type != "office",
                )
            )

        if highest == "department":
            # Admin Bộ môn: pending trong các Bộ môn được gán
            division_ids = [
                r.division_id
                for r in self.active_admin_roles
                if r.role_level == "department" and r.division_id
            ]
            if not division_ids and self.division_id:
                division_ids = [self.division_id]
            if not division_ids:
                return model_class.query.filter_by(id=-1)

            return (
                model_class.query.join(User, model_class.user_id == User.id)
                .join(
                    OrganizationUnit, User.organization_unit_id == OrganizationUnit.id
                )
                .filter(
                    model_class.approval_status == "pending",
                    User.division_id.in_(division_ids),
                    OrganizationUnit.unit_type != "office",
                )
            )

        return model_class.query.filter_by(id=-1)  # Empty query

    def validate_org_structure(self, session=None) -> None:
        """Validate and normalize the new org structure fields.

        Rules:
        - organization_unit_id is required
        - If OrganizationUnit.unit_type == 'faculty' then division_id is required
        - If division_id is provided, it must belong to the selected organization_unit_id
        - If unit_type == 'office', division_id will be cleared (not applicable)
        """
        sess = session or object_session(self) or db.session

        # Admin cấp Trường không bắt buộc thuộc đơn vị nào
        if not self.organization_unit_id:
            # Allow university admin even before AdminRole is attached (legacy admin_level cache)
            if self.highest_admin_level == "university" or self.admin_level == "university":
                return
            raise ValueError("Vui lòng chọn Khoa/Phòng ban (organization_unit_id).")

        org_unit = sess.get(OrganizationUnit, self.organization_unit_id)
        if not org_unit:
            raise ValueError("Khoa/Phòng ban không hợp lệ (organization_unit_id).")

        # Office: division not applicable
        if org_unit.unit_type == "office":
            self.division_id = None
            return

        # Faculty: division required
        if org_unit.unit_type == "faculty":
            requires_division = getattr(org_unit, "requires_division", True)

            if requires_division and not self.division_id:
                raise ValueError("Vui lòng chọn Bộ môn (bắt buộc đối với Khoa).")

            if self.division_id:
                division = sess.get(Division, self.division_id)
                if not division:
                    raise ValueError("Bộ môn không hợp lệ (division_id).")

                if division.organization_unit_id != self.organization_unit_id:
                    raise ValueError("Bộ môn không thuộc Khoa/Phòng ban đã chọn.")
            return

        return


@event.listens_for(User, "before_insert")
def _user_before_insert(mapper, connection, target):
    # Ensure org structure is consistent even if created outside routes (admin scripts, seeds, etc.)
    target.validate_org_structure()


@event.listens_for(User, "before_update")
def _user_before_update(mapper, connection, target):
    # Validate when org-related fields are present (keeps legacy records safe unless modified)
    if target.organization_unit_id is not None or target.division_id is not None:
        target.validate_org_structure()


# =============================================================================
# PUBLICATION MODEL - Tất cả loại án phẩm
# =============================================================================


class Publication(db.Model):
    """
    An phẩm khoa học - hỗ trợ tất cả loại theo Quy chế.
    Tính giờ tự động dựa trên publication_type và các trường liên quan.
    """

    __tablename__ = "publications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    # Thông tin cơ bản
    title = db.Column(db.String(500), nullable=False)
    year = db.Column(db.Integer, nullable=False, index=True)
    publication_type = db.Column(db.String(50), nullable=False, index=True)

    # Thông tin venue (tạp chí, hội nghị, nhà xuất bản)
    venue_name = db.Column(db.String(300))  # Ten tap chi/hoi nghi/NXB

    # Journal specific
    quartile = db.Column(db.String(10))  # Q1, Q2, Q3, Q4
    domestic_points = db.Column(db.Float, default=0.0)  # Điểm HĐGSNN (0-1+)
    issn = db.Column(db.String(20))

    # Conference specific
    isbn = db.Column(db.String(20))  # Cho hội nghị quốc gia

    # Author information
    all_authors = db.Column(db.Text)  # Danh sách tất cả tác giả (comma separated)
    total_authors = db.Column(db.Integer, default=1)
    author_role = db.Column(
        db.String(30), default="middle"
    )  # first, corresponding, first_corresponding, middle
    contribution_percentage = db.Column(db.Float)  # % đóng góp (optional, override)

    # Patent specific
    patent_stage = db.Column(db.String(20))  # stage_1, stage_2, granted
    patent_number = db.Column(db.String(50))

    # Book specific
    publisher = db.Column(db.String(200))  # Nhà xuất bản
    is_republished = db.Column(db.Boolean, default=False)  # Tái bản/biên dịch

    # Calculated hours
    base_hours = db.Column(
        db.Float, default=0.0
    )  # Giờ cơ bản (trước khi tính % tác giả)
    author_hours = db.Column(db.Float, default=0.0)  # Giờ của tác giả (sau khi tính %)

    # Metadata
    doi = db.Column(db.String(100))
    url = db.Column(db.String(500))
    notes = db.Column(db.Text)

    # Approval status (Admin approval system)
    is_approved = db.Column(db.Boolean, default=False)  # Đã được admin duyệt chưa
    approval_status = db.Column(
        db.String(20), default="pending"
    )  # draft, pending, department_approved, faculty_approved, approved, returned
    approved_at = db.Column(db.DateTime, nullable=True)  # Thời gian duyệt
    approved_by = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True
    )  # Admin đã duyệt
    rejection_reason = db.Column(db.Text, nullable=True)  # Lý do trả lại
    returned_at = db.Column(db.DateTime, nullable=True)  # Thời gian trả lại
    returned_by_level = db.Column(
        db.String(20), nullable=True
    )  # Cấp admin trả lại: department, faculty, university

    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Index for common queries
    __table_args__ = (
        db.Index("idx_user_year", "user_id", "year"),
        db.Index("idx_pub_type_year", "publication_type", "year"),
        db.Index("idx_approval_status", "is_approved"),
        db.Index("idx_approval_status_enum", "approval_status"),
    )

    def __repr__(self):
        return f"<Publication {self.title[:50]}... ({self.year})>"

    @property
    def publication_type_display(self) -> str:
        """Ten hien thi cua loai an pham"""
        display_names = {
            # Journals
            "journal_wos_scopus": "Tạp chí WoS/Scopus",
            "journal_vnu_special": "Chuyên san VNU",
            "journal_rev": "Tạp chi Điện tử Truyền thông (REV)",
            "journal_international_reputable": "Tạp chí quốc tế uy tín (ngoài WoS/Scopus)",
            "journal_domestic": "Tạp chí trong nước",
            # Conferences
            "conference_wos_scopus": "Hội nghị WoS/Scopus",
            "conference_international": "Hội nghị quốc tế",
            "conference_national": "Hội nghị quốc gia",
            # Books
            "monograph_international": "Sách chuyên khảo (quốc tế)",
            "monograph_domestic": "Sách chuyên khảo (trong nước)",
            "textbook_international": "Giáo trình (quốc tế)",
            "textbook_domestic": "Giáo trình (trong nước)",
            "book_chapter_reputable": "Chương sách (NXB uy tín)",
            "book_chapter_international": "Chương sách (quốc tế)",
            # IP
            "patent_international": "Bằng độc quyền sáng chế (quốc tế)",
            "patent_vietnam": "Bằng độc quyền sáng chế (Viet Nam)",
            "utility_solution": "Giải pháp hữu ích",
            # Awards
            "award_international": "Giải thưởng quốc tế",
            "award_national": "Giải thưởng quốc gia",
            # Exhibitions
            "exhibition_international": "Triển lãm quốc tế",
            "exhibition_national": "Triển lãm quốc gia",
            "exhibition_provincial": "Triển lãm cấp tỉnh",
        }
        return display_names.get(self.publication_type, self.publication_type)

    @property
    def author_role_display(self) -> str:
        """Tên hiển thị vai trò tác giả"""
        role_names = {
            "first": "Tác giả đầu",
            "corresponding": "Tác giả liên hệ",
            "first_corresponding": "Tác giả đầu + Liên hệ",
            "middle": "Đồng tác giả",
        }
        return role_names.get(self.author_role, self.author_role)

    @property
    def approval_status_display(self) -> str:
        """Tên hiển thị trạng thái duyệt"""
        return approval_status_to_display(self.approval_status)

    @property
    def can_edit(self) -> bool:
        """Kiểm tra có thể sửa không (chưa được duyệt)"""
        return self.approval_status in ("draft", "returned")

    @property
    def can_delete(self) -> bool:
        """Kiểm tra có thể xóa không (chưa được duyệt)"""
        return self.approval_status in ("draft", "returned")


# =============================================================================
# HELPER TABLES
# =============================================================================


class JournalCatalog(db.Model):
    """Danh mục tạp chí quốc tế (Scopus/WoS) - migrated from SQLite publications.db"""

    __tablename__ = "journal_catalog"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(500), nullable=False, index=True)
    publication_type = db.Column(db.String(100))
    region = db.Column(db.String(100))
    indexing = db.Column(db.String(100))
    issn = db.Column(db.String(20))
    e_issn = db.Column(db.String(20))
    sjr_year = db.Column(db.Integer)
    sjr_publisher = db.Column(db.String(300))
    sjr_score = db.Column(db.Float)
    sjr_best_quartile = db.Column(db.String(10))
    sjr_h_index = db.Column(db.Integer)

    __table_args__ = (
        db.Index("idx_journal_catalog_name", "name"),
        db.Index("idx_journal_catalog_issn", "issn"),
        db.Index("idx_journal_catalog_e_issn", "e_issn"),
    )

    def __repr__(self):
        return f"<JournalCatalog {self.name[:50]}>"


class VNUSpecialJournal(db.Model):
    """Danh sách tạp chí VNU đặc biệt (mục 1.2)"""

    __tablename__ = "vnu_special_journals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False, unique=True)
    issn = db.Column(db.String(20))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)


class DomesticJournal(db.Model):
    """Danh sách tạp chí trong nước và điểm HĐGSNN"""

    __tablename__ = "domestic_journals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False, unique=True)
    issn = db.Column(db.String(20))
    points = db.Column(db.Float, default=0.0)  # Điểm HĐGSNN
    category = db.Column(db.String(100))  # Ngành
    is_active = db.Column(db.Boolean, default=True)


class ReputablePublisher(db.Model):
    """Danh sách NXB uy tín (theo mục d. của Quy chế)"""

    __tablename__ = "reputable_publishers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    country = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)


# =============================================================================
# INITIALIZATION HELPERS
# =============================================================================


class REVJournal(db.Model):
    """Tạp chí Điện tử Truyền thông (REV) - mục 1.2b"""

    __tablename__ = "rev_journals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False, unique=True)
    issn = db.Column(db.String(20))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)


# =============================================================================
# PROJECT MODEL - Đề tài, dự án KHCN (Bang 2, mục 1-2)
# =============================================================================


class Project(db.Model):
    """
    Đề tài, dự án KHCN theo Bang 2 của Quy chế.
    Hỗ trợ:
    - 1.1: Đề tài cấp Nhà nước (1000 giờ)
    - 1.2: Đề tài cấp ĐHQGHN/Bộ (800 giờ)
    - 1.3: Đề tài cấp Trường (300 giờ)
    - 2: Đề tài hợp tác, dịch vụ KHCN (công thức đặc biệt)
    """

    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    # Thông tin cơ bản
    title = db.Column(db.String(500), nullable=False)
    project_code = db.Column(db.String(50))  # Mã đề tài
    project_level = db.Column(
        db.String(30), nullable=False
    )  # national, vnu_ministry, university, cooperation

    # Thời gian
    start_year = db.Column(db.Integer, nullable=False)
    end_year = db.Column(db.Integer, nullable=False)
    duration_years = db.Column(db.Integer, default=1)  # Số năm thực hiện

    # Trang thái
    status = db.Column(db.String(20), default="ongoing")  # ongoing, completed, extended

    # Vai trò và thành viên
    role = db.Column(db.String(20), nullable=False)  # leader, secretary, member
    total_members = db.Column(db.Integer, default=1)

    # Cho đề tài hợp tác (mục 2)
    funding_amount = db.Column(db.Float, default=0.0)  # Giá trị tài trợ (ty đồng)

    # Cơ quan quản lý/tài trợ
    funding_agency = db.Column(db.String(300))  # Cơ quan tài trợ

    # Calculated hours
    total_hours = db.Column(db.Float, default=0.0)  # Tổng giờ của đề tài
    user_hours = db.Column(db.Float, default=0.0)  # Giờ của người dùng (theo vai trò)

    # Metadata
    description = db.Column(db.Text)
    notes = db.Column(db.Text)

    # Approval status (Admin approval system)
    is_approved = db.Column(db.Boolean, default=False)
    approval_status = db.Column(
        db.String(20), default="pending"
    )  # draft, pending, department_approved, faculty_approved, approved, returned
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)  # Lý do trả lại
    returned_at = db.Column(db.DateTime, nullable=True)  # Thời gian trả lại
    returned_by_level = db.Column(
        db.String(20), nullable=True
    )  # Cấp admin trả lại: department, faculty, university

    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Index
    __table_args__ = (
        db.Index("idx_project_user_year", "user_id", "start_year"),
        db.Index("idx_project_level", "project_level"),
        db.Index("idx_project_approval", "is_approved"),
        db.Index("idx_project_approval_status", "approval_status"),
    )

    def __repr__(self):
        return f"<Project {self.title[:50]}... ({self.start_year}-{self.end_year})>"

    @property
    def project_level_display(self) -> str:
        """Tên hiển thị cấp đề tài"""
        display_names = {
            "national": "Đề tài cấp Nhà nước",
            "vnu_ministry": "Đề tài cấp ĐHQGHN/Bộ",
            "university": "Đề tài cấp Trường",
            "cooperation": "Đề tài hợp tác/Dịch vụ KHCN",
        }
        return display_names.get(self.project_level, self.project_level)

    @property
    def role_display(self) -> str:
        """Tên hiển thị vai trò"""
        role_names = {
            "leader": "Chủ trì",
            "secretary": "Thư ký khoa học",
            "member": "Thành viên",
        }
        return role_names.get(self.role, self.role)

    @property
    def status_display(self) -> str:
        """Tên hiển thị trạng thái"""
        status_names = {
            "ongoing": "Đang thực hiện",
            "completed": "Đã nghiệm thu",
            "extended": "Gia hạn (không tính giờ)",
        }
        return status_names.get(self.status, self.status)

    @property
    def approval_status_display(self) -> str:
        """Tên hiển thị trạng thái duyệt"""
        return approval_status_to_display(self.approval_status)

    @property
    def can_edit(self) -> bool:
        """Kiểm tra có thể sửa không (chưa được duyệt)"""
        return self.approval_status in ("draft", "returned")

    @property
    def can_delete(self) -> bool:
        """Kiểm tra có thể xóa không (chưa được duyệt)"""
        return self.approval_status in ("draft", "returned")


# =============================================================================
# OTHER ACTIVITY MODEL - Hoat dong KHCN khac (Bang 2, Muc 3)
# =============================================================================


class OtherActivity(db.Model):
    """
    Hoạt động KHCN khác theo Bang 2, Mục 3.
    Tối đa 250 giờ/năm cho mục này.

    - 3.1a: Hướng dẫn SV NCKH cấp trường (75 giờ/nhóm)
    - 3.1b: Hướng dẫn SV NCKH cấp khoa (30 giờ/nhóm)
    - 3.2: Huấn luyện đội tuyển SV (75 giờ/đội)
    - 3.3: Sản phẩm KHCN tham gia triển lãm (45 giờ/sản phẩm)
    """

    __tablename__ = "other_activities"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    # Thông tin cơ bản
    title = db.Column(db.String(500), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)
    year = db.Column(db.Integer, nullable=False, index=True)

    # Số lượng (nhóm, đội, sản phẩm)
    quantity = db.Column(db.Integer, default=1)

    # Chi tiết
    student_names = db.Column(db.Text)  # Tên sinh viên (nếu có)
    event_name = db.Column(db.String(300))  # Tên hội nghị/cuộc thi/triển lãm
    achievement = db.Column(db.String(200))  # Kết quả/giải thưởng (nếu có)

    # Calculated hours
    hours = db.Column(db.Float, default=0.0)

    # Metadata
    notes = db.Column(db.Text)

    # Approval status (Admin approval system)
    is_approved = db.Column(db.Boolean, default=False)
    approval_status = db.Column(
        db.String(20), default="pending"
    )  # draft, pending, department_approved, faculty_approved, approved, returned
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)  # Lý do trả lại
    returned_at = db.Column(db.DateTime, nullable=True)  # Thời gian trả lại
    returned_by_level = db.Column(
        db.String(20), nullable=True
    )  # Cấp admin trả lại: department, faculty, university

    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Index
    __table_args__ = (
        db.Index("idx_activity_user_year", "user_id", "year"),
        db.Index("idx_activity_approval", "is_approved"),
        db.Index("idx_activity_approval_status", "approval_status"),
    )

    def __repr__(self):
        return f"<OtherActivity {self.title[:50]}... ({self.year})>"

    @property
    def activity_type_display(self) -> str:
        """Tên hiển thị loại hoạt động"""
        display_names = {
            "student_research_university": "Hướng dẫn SV NCKH (cấp trường)",
            "student_research_faculty": "Hướng dẫn SV NCKH (cấp khoa)",
            "team_training": "Huấn luyện đội tuyển SV",
            "exhibition_product": "Sản phẩm KHCN tham gia triển lãm",
        }
        return display_names.get(self.activity_type, self.activity_type)

    @property
    def approval_status_display(self) -> str:
        """Tên hiển thị trạng thái duyệt"""
        return approval_status_to_display(self.approval_status)

    @property
    def can_edit(self) -> bool:
        """Kiểm tra có thể sửa không (chưa được duyệt)"""
        return self.approval_status in ("draft", "returned")

    @property
    def can_delete(self) -> bool:
        """Kiểm tra có thể xóa không (chưa được duyệt)"""
        return self.approval_status in ("draft", "returned")


# Thêm relationship vào User - chi dinh foreign_keys vi co nhieu FK tro den User
User.projects = db.relationship(
    "Project", backref="user", lazy="dynamic", foreign_keys="Project.user_id"
)
User.other_activities = db.relationship(
    "OtherActivity",
    backref="user",
    lazy="dynamic",
    foreign_keys="OtherActivity.user_id",
)


# =============================================================================
# APPROVAL STATUS SYNC HELPERS
# =============================================================================


def _sync_is_approved(target):
    """Keep boolean is_approved consistent with approval_status."""
    try:
        target.is_approved = getattr(target, "approval_status", None) == "approved"
    except Exception:
        pass


@event.listens_for(Publication, "before_insert")
@event.listens_for(Publication, "before_update")
def _pub_sync_is_approved(mapper, connection, target):
    _sync_is_approved(target)


@event.listens_for(Project, "before_insert")
@event.listens_for(Project, "before_update")
def _proj_sync_is_approved(mapper, connection, target):
    _sync_is_approved(target)


@event.listens_for(OtherActivity, "before_insert")
@event.listens_for(OtherActivity, "before_update")
def _act_sync_is_approved(mapper, connection, target):
    _sync_is_approved(target)


# =============================================================================
# ADMIN ROLE - Bảng phân quyền admin (cho phép 1 người nhiều vai trò)
# =============================================================================


class AdminRole(db.Model):
    """
    Bảng phân quyền admin - cho phép 1 người có nhiều vai trò admin.

    Ví dụ:
    - Nguyễn Văn A: Admin Trường + Admin Khoa CNTT
    - Trần Thị B: Admin Khoa CNTT + Admin BM CNPM
    """

    __tablename__ = "admin_roles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    # Cấp admin: 'department', 'faculty', 'university'
    role_level = db.Column(db.String(20), nullable=False)

    # Phạm vi quản lý (NULL cho university)
    organization_unit_id = db.Column(
        db.Integer, db.ForeignKey("organization_units.id"), nullable=True
    )
    division_id = db.Column(db.Integer, db.ForeignKey("divisions.id"), nullable=True)

    # Audit
    assigned_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)

    # Relationships
    user = db.relationship("User", foreign_keys=[user_id], backref="roles")
    assigner = db.relationship("User", foreign_keys=[assigned_by])
    org_unit = db.relationship("OrganizationUnit", foreign_keys=[organization_unit_id])
    division = db.relationship("Division", foreign_keys=[division_id])

    # Unique constraint: mỗi user chỉ có 1 role cho mỗi scope
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "role_level",
            "organization_unit_id",
            "division_id",
            name="unique_admin_role",
        ),
        db.CheckConstraint(
            "role_level <> 'university' OR (organization_unit_id IS NULL AND division_id IS NULL)",
            name="ck_admin_role_university_scope",
        ),
        db.CheckConstraint(
            "role_level <> 'faculty' OR (organization_unit_id IS NOT NULL AND division_id IS NULL)",
            name="ck_admin_role_faculty_scope",
        ),
        db.CheckConstraint(
            "role_level <> 'department' OR division_id IS NOT NULL",
            name="ck_admin_role_department_scope",
        ),
        db.Index("idx_admin_role_user", "user_id"),
        db.Index("idx_admin_role_level", "role_level"),
    )

    def __repr__(self):
        scope = ""
        if self.role_level == "university":
            scope = "Toàn trường"
        elif self.role_level == "faculty" and self.org_unit:
            scope = self.org_unit.name
        elif self.role_level == "department" and self.division:
            scope = self.division.name
        return f"<AdminRole {self.role_level}: {scope}>"

    @property
    def role_level_display(self) -> str:
        """Tên hiển thị cấp admin"""
        display_names = {
            "department": "Admin Bộ môn",
            "faculty": "Admin Khoa",
            "university": "Admin Trường",
        }
        return display_names.get(self.role_level, "Không xác định")

    @property
    def scope_display(self) -> str:
        """Tên hiển thị phạm vi"""
        if self.role_level == "university":
            return "Toàn trường"
        elif self.role_level == "faculty" and self.org_unit:
            return self.org_unit.name
        elif self.role_level == "department" and self.division:
            return f"{self.division.name}"
        return "Không xác định"

    @property
    def full_display(self) -> str:
        """Tên đầy đủ vai trò"""
        return f"{self.role_level_display} ({self.scope_display})"

    @classmethod
    def get_user_roles(cls, user_id: int, active_only: bool = True):
        """Lấy tất cả vai trò của user"""
        query = cls.query.filter_by(user_id=user_id)
        if active_only:
            query = query.filter_by(is_active=True)
        return query.all()

    @classmethod
    def get_highest_level(cls, user_id: int) -> str:
        """Lấy cấp admin cao nhất của user"""
        roles = cls.get_user_roles(user_id, active_only=True)
        if not roles:
            return "none"

        hierarchy = {"university": 3, "faculty": 2, "department": 1}
        max_level = 0
        highest = "none"

        for role in roles:
            level = hierarchy.get(role.role_level, 0)
            if level > max_level:
                max_level = level
                highest = role.role_level

        return highest

    @classmethod
    def has_role(
        cls,
        user_id: int,
        role_level: str,
        org_unit_id: int = None,
        division_id: int = None,
    ) -> bool:
        """Kiểm tra user có vai trò cụ thể không"""
        query = cls.query.filter_by(
            user_id=user_id, role_level=role_level, is_active=True
        )
        if role_level == "faculty" and org_unit_id:
            query = query.filter_by(organization_unit_id=org_unit_id)
        elif role_level == "department" and division_id:
            query = query.filter_by(division_id=division_id)

        return query.first() is not None

    @classmethod
    def grant_role(
        cls,
        user_id: int,
        role_level: str,
        organization_unit_id: int = None,
        division_id: int = None,
        assigned_by: int = None,
        notes: str = None,
    ):
        """Cấp vai trò admin cho user"""
        # Kiểm tra đã có chưa
        existing = cls.query.filter_by(
            user_id=user_id,
            role_level=role_level,
            organization_unit_id=organization_unit_id,
            division_id=division_id,
        ).first()

        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.assigned_by = assigned_by
                existing.assigned_at = datetime.utcnow()
                existing.notes = notes
                return existing
            return None  # Đã có rồi

        role = cls(
            user_id=user_id,
            role_level=role_level,
            organization_unit_id=organization_unit_id,
            division_id=division_id,
            assigned_by=assigned_by,
            notes=notes,
        )
        db.session.add(role)
        return role

    @classmethod
    def revoke_role(cls, role_id: int, revoked_by: int = None):
        """Thu hồi vai trò admin"""
        role = cls.query.get(role_id)
        if role:
            role.is_active = False
            user = User.query.get(role.user_id)
            if user:
                user.admin_level = cls.get_highest_level(user.id)
            return role
        return None


def _validate_admin_role_scope(target, session=None) -> None:
    """Validate AdminRole scope consistency."""
    level = (target.role_level or "").strip()
    sess = session or object_session(target) or db.session

    if level not in {"university", "faculty", "department"}:
        raise ValueError("Cấp admin không hợp lệ (role_level).")

    if level == "university":
        if target.organization_unit_id or target.division_id:
            raise ValueError("Admin Trường không được gán Khoa/Bộ môn.")
        return

    if level == "faculty":
        if not target.organization_unit_id:
            raise ValueError("Admin Khoa phải có organization_unit_id.")
        if target.division_id:
            raise ValueError("Admin Khoa không được gán division_id.")
        return

    if level == "department":
        if not target.division_id:
            raise ValueError("Admin Bộ môn phải có division_id.")

        division = sess.get(Division, target.division_id)
        if not division:
            raise ValueError("division_id không hợp lệ.")

        # If provided, org_unit_id must match division's organization_unit_id
        if target.organization_unit_id and division.organization_unit_id != target.organization_unit_id:
            raise ValueError("Bộ môn không thuộc Khoa đã gán.")
        if not target.organization_unit_id:
            target.organization_unit_id = division.organization_unit_id


@event.listens_for(AdminRole, "before_insert")
@event.listens_for(AdminRole, "before_update")
def _admin_role_before_save(mapper, connection, target):
    _validate_admin_role_scope(target)


# =============================================================================
# ADMIN PERMISSION LOG - Lịch sử gán/thu hồi quyền admin
# =============================================================================


class AdminPermissionLog(db.Model):
    """
    Lịch sử gán/thu hồi quyền admin.
    Dùng để audit ai đã gán quyền cho ai, khi nào.
    """

    __tablename__ = "admin_permission_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )  # User được gán/thu hồi quyền
    action = db.Column(db.String(20), nullable=False)  # 'grant', 'revoke', 'change'
    old_level = db.Column(db.String(20))  # Cấp admin trước đó
    new_level = db.Column(db.String(20))  # Cấp admin mới
    performed_by = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )  # Admin thực hiện
    performed_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)  # Ghi chú (nếu có)

    # Relationships
    target_user = db.relationship(
        "User", foreign_keys=[user_id], backref="admin_permission_history"
    )
    performer = db.relationship(
        "User", foreign_keys=[performed_by], backref="admin_actions_performed"
    )

    # Index
    __table_args__ = (
        db.Index("idx_admin_log_user", "user_id"),
        db.Index("idx_admin_log_performer", "performed_by"),
        db.Index("idx_admin_log_time", "performed_at"),
    )

    def __repr__(self):
        return (
            f"<AdminPermissionLog {self.action}: {self.old_level} -> {self.new_level}>"
        )

    @property
    def action_display(self) -> str:
        """Tên hiển thị hành động"""
        display_names = {
            "grant": "Cấp quyền",
            "revoke": "Thu hồi quyền",
            "change": "Thay đổi quyền",
        }
        return display_names.get(self.action, self.action)

    @classmethod
    def log_change(
        cls,
        user_id: int,
        old_level: str,
        new_level: str,
        performed_by: int,
        notes: str = None,
    ):
        """Ghi log thay đổi quyền admin"""
        if old_level == new_level:
            return None  # Không có thay đổi

        if old_level == "none" and new_level != "none":
            action = "grant"
        elif old_level != "none" and new_level == "none":
            action = "revoke"
        else:
            action = "change"

        log = cls(
            user_id=user_id,
            action=action,
            old_level=old_level,
            new_level=new_level,
            performed_by=performed_by,
            notes=notes,
        )
        db.session.add(log)
        return log


# =============================================================================
# APPROVAL HISTORY LOG - Lịch sử duyệt công trình (tùy chọn)
# =============================================================================


class ApprovalLog(db.Model):
    """
    Lịch sử duyệt công trình KHCN.
    Ghi lại từng bước trong quy trình duyệt 3 cấp.
    """

    __tablename__ = "approval_logs"

    id = db.Column(db.Integer, primary_key=True)
    item_type = db.Column(
        db.String(50), nullable=False
    )  # 'publication', 'project', 'activity'
    item_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(
        db.String(30), nullable=False
    )  # 'department_approve', 'faculty_approve', 'university_approve', 'return'
    old_status = db.Column(db.String(30))
    new_status = db.Column(db.String(30))
    performed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    performed_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)  # Ghi chú/Lý do trả lại

    # Relationship
    performer = db.relationship("User", backref="approval_actions")

    # Index
    __table_args__ = (
        db.Index("idx_approval_log_item", "item_type", "item_id"),
        db.Index("idx_approval_log_performer", "performed_by"),
    )

    def __repr__(self):
        return f"<ApprovalLog {self.item_type}:{self.item_id} {self.action}>"

    @property
    def action_display(self) -> str:
        """Tên hiển thị hành động"""
        display_names = {
            "department_approve": "Bộ môn xác nhận",
            "faculty_approve": "Khoa duyệt",
            "university_approve": "Trường phê duyệt",
            "return": "Trả lại",
        }
        return display_names.get(self.action, self.action)


def init_default_data(app):
    """Khởi tạo dữ liệu mặc định"""
    with app.app_context():
        # Kiểm tra xem cột admin_level đã tồn tại chưa
        inspector = inspect(db.engine)
        user_columns = [col["name"] for col in inspector.get_columns("users")]
        has_admin_level = "admin_level" in user_columns

        # Neu chua co cot admin_level, them cot vao database
        if not has_admin_level:
            print(">>> Column admin_level does not exist, adding...")
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN admin_level VARCHAR(20) DEFAULT 'none'"
                    )
                )
            print(">>> Added column admin_level")

        # Migrate old is_admin=True to admin_level='university' (if is_admin column exists)
        has_is_admin = "is_admin" in user_columns
        if has_is_admin:
            with db.engine.begin() as conn:
                # Migrate old admins to university level (PostgreSQL uses true/false)
                result = conn.execute(
                    text(
                        "UPDATE users SET admin_level = 'university' WHERE is_admin = true AND (admin_level IS NULL OR admin_level = 'none' OR admin_level = '')"
                    )
                )
                if result.rowcount > 0:
                    print(
                        f">>> Migrated {result.rowcount} old admin(s) to admin_level='university'"
                    )

        # Tạo bảng admin_roles nếu chưa có (cần trước khi tạo role)
        existing_tables = inspector.get_table_names()
        if "admin_roles" not in existing_tables:
            print(">>> Creating table admin_roles...")
            AdminRole.__table__.create(db.engine, checkfirst=True)

        # Tạo tài khoản admin mặc định nếu chưa có admin nào (ưu tiên AdminRole)
        admin_exists = AdminRole.query.filter_by(is_active=True).first()
        if not admin_exists:
            admin_exists = User.query.filter(User.admin_level == "university").first()
        if not admin_exists:
            # Kiểm tra xem có user admin@vnu.edu.vn không
            existing_admin = User.query.filter_by(email="admin@vnu.edu.vn").first()
            if existing_admin:
                # Cập nhật admin_level cho user đã tồn tại
                existing_admin.admin_level = "university"
                # Ensure AdminRole exists
                existing_role = AdminRole.query.filter_by(
                    user_id=existing_admin.id,
                    role_level="university",
                    is_active=True,
                ).first()
                if not existing_role:
                    db.session.add(
                        AdminRole(
                            user_id=existing_admin.id,
                            role_level="university",
                            is_active=True,
                            notes="Default admin role",
                        )
                    )
                print(">>> Updated admin@vnu.edu.vn to Admin Truong (university)")
            else:
                default_admin = User(
                    email="admin@vnu.edu.vn",
                    full_name="Administrator (PKHCN)",
                    admin_level="university",  # Admin cấp Trường
                    is_active=True,
                )
                default_admin.set_password(
                    "admin123"
                )  # Default password, should change after login
                db.session.add(default_admin)
                db.session.flush()
                db.session.add(
                    AdminRole(
                        user_id=default_admin.id,
                        role_level="university",
                        is_active=True,
                        notes="Default admin role",
                    )
                )
                print(">>> Created Admin Truong account: admin@vnu.edu.vn / admin123")

        # Create log tables if not exist
        existing_tables = inspector.get_table_names()
        if "admin_permission_logs" not in existing_tables:
            print(">>> Creating table admin_permission_logs...")
            AdminPermissionLog.__table__.create(db.engine, checkfirst=True)
        if "approval_logs" not in existing_tables:
            print(">>> Creating table approval_logs...")
            ApprovalLog.__table__.create(db.engine, checkfirst=True)

        # Backfill: đồng bộ admin_level -> admin_roles (kể cả khi bảng đã tồn tại)
        admin_users = User.query.filter(
            User.admin_level.in_(["department", "faculty", "university"])
        ).all()
        created_roles = 0
        skipped_roles = 0

        for user in admin_users:
            role_level = user.admin_level
            if role_level == "faculty" and not user.organization_unit_id:
                skipped_roles += 1
                continue
            if role_level == "department" and not user.division_id:
                skipped_roles += 1
                continue

            existing_role = AdminRole.query.filter_by(
                user_id=user.id,
                role_level=role_level,
                organization_unit_id=(
                    user.organization_unit_id
                    if role_level in ["faculty", "department"]
                    else None
                ),
                division_id=(user.division_id if role_level == "department" else None),
            ).first()
            if existing_role:
                continue

            role = AdminRole(
                user_id=user.id,
                role_level=role_level,
                organization_unit_id=(
                    user.organization_unit_id
                    if role_level in ["faculty", "department"]
                    else None
                ),
                division_id=user.division_id if role_level == "department" else None,
                is_active=True,
                notes="Backfilled from admin_level column",
            )
            db.session.add(role)
            created_roles += 1

        if created_roles:
            db.session.commit()
            print(f">>> Backfilled {created_roles} admin role(s) from admin_level")
        if skipped_roles:
            print(f">>> Skipped {skipped_roles} admin role(s) due to missing scope")

        # Sync admin_level cache from AdminRole
        role_user_ids = [
            row[0]
            for row in db.session.query(AdminRole.user_id).distinct().all()
        ]
        for uid in role_user_ids:
            u = User.query.get(uid)
            if not u:
                continue
            u.admin_level = AdminRole.get_highest_level(uid)
        if role_user_ids:
            db.session.commit()

        # Update admin_level = 'none' for users without value
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE users SET admin_level = 'none' WHERE admin_level IS NULL OR admin_level = ''"
                )
            )

        # =================================================================
        # ORGANIZATION UNITS / DIVISIONS (New structure)
        #
        # POLICY: Không hardcode dữ liệu Khoa/Phòng ban/Bộ môn trong code.
        # Admin quản lý toàn bộ thông qua giao diện web:
        # - Quản lý Khoa/Phòng ban: /admin/org-units
        # - Quản lý Bộ môn: /admin/divisions
        # =================================================================

        # VNU Special Journals
        vnu_journals = [
            ("VNU Journal of Science", None),
            ("Chuyên san Công nghệ thông tin và Truyền thông (VNU)", None),
        ]
        for name, issn in vnu_journals:
            if not VNUSpecialJournal.query.filter_by(name=name).first():
                db.session.add(VNUSpecialJournal(name=name, issn=issn))

        # REV Journal
        rev_journals = [
            (
                "Tạp chi Điện tử Truyền thông / Journal on Electronics and Communications",
                "1859-378X",
            ),
        ]
        for name, issn in rev_journals:
            if not REVJournal.query.filter_by(name=name).first():
                db.session.add(REVJournal(name=name, issn=issn))

        # Reputable Publishers
        publishers = [
            ("Elsevier", "Netherlands"),
            ("Springer", "Germany"),
            ("Wiley-Blackwell", "USA"),
            ("Taylor & Francis", "UK"),
            ("Sage", "USA"),
            ("Oxford University Press", "UK"),
            ("Cambridge University Press", "UK"),
            ("Emerald", "UK"),
            ("Macmillan Publishers", "UK"),
            ("Inderscience Publishers", "Switzerland"),
            ("Edward Elgar Publishing", "UK"),
        ]
        for name, country in publishers:
            if not ReputablePublisher.query.filter_by(name=name).first():
                db.session.add(ReputablePublisher(name=name, country=country))

        db.session.commit()
        print(
            ">>> init_default_data: ready (org structure not overwritten if DB has data)"
        )


def ensure_user_org_columns(app=None):
    """
    Ensure database schema has all required columns.
    Lightweight migration helper (ALTER TABLE ADD COLUMN).
    """
    if app is None:
        from flask import current_app

        app = current_app

    with app.app_context():
        inspector = inspect(db.engine)
        try:
            cols = [c["name"] for c in inspector.get_columns("users")]
        except Exception:
            cols = []

        with db.engine.begin() as conn:
            if "organization_unit_id" not in cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN organization_unit_id INTEGER")
                )
            if "division_id" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN division_id INTEGER"))
            if "failed_login_count" not in cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN failed_login_count INTEGER DEFAULT 0")
                )
            if "locked_until" not in cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN locked_until TIMESTAMP")
                )
            if "avatar_filename" not in cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN avatar_filename VARCHAR(255)")
                )

        # Ensure returned_by_level column exists on item tables
        for tbl in ("publications", "projects", "other_activities"):
            try:
                tbl_cols = [c["name"] for c in inspector.get_columns(tbl)]
                if "returned_by_level" not in tbl_cols:
                    with db.engine.begin() as conn:
                        conn.execute(
                            text(
                                f"ALTER TABLE {tbl} ADD COLUMN returned_by_level VARCHAR(20)"
                            )
                        )
            except Exception:
                pass

        # Create journal_catalog table if not present
        try:
            existing_tables = inspector.get_table_names()
            if "journal_catalog" not in existing_tables:
                JournalCatalog.__table__.create(db.engine, checkfirst=True)
        except Exception:
            pass

        # PostgreSQL: create enum type and unique constraint if missing.
        try:
            with db.engine.begin() as conn:
                # Create enum type unit_type_enum if it doesn't exist
                try:
                    exists = conn.execute(
                        text("SELECT 1 FROM pg_type WHERE typname = 'unit_type_enum'")
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            text(
                                "CREATE TYPE unit_type_enum AS ENUM ('faculty','office')"
                            )
                        )
                except Exception:
                    pass

                # Ensure unit_type column is VARCHAR (not native enum) for compatibility.
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE organization_units ALTER COLUMN unit_type TYPE VARCHAR(20) USING unit_type::text"
                        )
                    )
                except Exception:
                    pass

                # Add unique constraint for divisions(code, organization_unit_id) if missing
                try:
                    exists_c = conn.execute(
                        text(
                            "SELECT 1 FROM pg_constraint WHERE conname = 'uq_division_code_org'"
                        )
                    ).fetchone()
                    if not exists_c:
                        conn.execute(
                            text(
                                "ALTER TABLE divisions ADD CONSTRAINT uq_division_code_org UNIQUE (code, organization_unit_id)"
                            )
                        )
                except Exception:
                    pass

        except Exception:
            # If anything fails, skip but do not crash application startup
            pass


def ensure_admin_role_constraints(app=None):
    """
    Ensure admin_roles check constraints exist (best-effort).
    """
    if app is None:
        from flask import current_app

        app = current_app

    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            return

        inspector = inspect(db.engine)
        try:
            if "admin_roles" not in inspector.get_table_names():
                return
        except Exception:
            return
        try:
            existing = inspector.get_check_constraints("admin_roles")
        except Exception:
            existing = []
        existing_names = {c.get("name") for c in existing if c.get("name")}

        constraints = {
            "ck_admin_role_university_scope": "role_level <> 'university' OR (organization_unit_id IS NULL AND division_id IS NULL)",
            "ck_admin_role_faculty_scope": "role_level <> 'faculty' OR (organization_unit_id IS NOT NULL AND division_id IS NULL)",
            "ck_admin_role_department_scope": "role_level <> 'department' OR division_id IS NOT NULL",
        }

        with db.engine.begin() as conn:
            for name, expr in constraints.items():
                if name in existing_names:
                    continue
                try:
                    conn.execute(
                        text(
                            f"ALTER TABLE admin_roles ADD CONSTRAINT {name} CHECK ({expr})"
                        )
                    )
                except Exception:
                    # Best-effort: do not break startup if data violates constraints
                    pass
