# VNU-UET Research Hours Management System

Hệ thống quản lý giờ nghiên cứu khoa học cho Trường Đại học Công nghệ (VNU-UET) theo Quy chế QĐ 2706/QĐ-ĐHCN ngày 21/11/2024.

## Tính năng chính

- **Quản lý ấn phẩm khoa học**: Bài báo WoS/Scopus, tạp chí trong nước, hội nghị, sách, sáng chế...
- **Quản lý đề tài/dự án**: Đề tài cấp Nhà nước, ĐHQGHN, Trường, hợp tác quốc tế
- **Quản lý hoạt động KHCN khác**: Hướng dẫn SV NCKH, huấn luyện đội tuyển...
- **Tính giờ tự động**: Theo công thức quy định trong Quy chế
- **Hệ thống phân quyền 3 cấp**: Admin Trường (PKHCN) → Admin Khoa → Admin Bộ môn
- **Quy trình duyệt tuần tự**: Bộ môn → Khoa → Trường
- **Báo cáo thống kê**: Theo năm, theo đơn vị

## Yêu cầu

- Python 3.11+
- PostgreSQL 15+ (chạy qua Docker hoặc cài trực tiếp)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (khuyến nghị)

---

## Cách 1: Chạy hoàn toàn bằng Docker (đơn giản nhất)

```bash
# Clone
git clone <repo-url>
cd rowfollow

# Khởi động (tự tạo DB + web server)
docker-compose -f docker-compose.dev.yml up -d --build
```

Truy cập: **http://localhost:5000**

---

## Cách 2: Chạy Flask trên máy local (khuyến nghị khi phát triển)

Database vẫn chạy trong Docker, Flask chạy trực tiếp trên máy.

### Bước 1: Khởi động PostgreSQL trong Docker

```bash
docker-compose -f docker-compose.dev.yml up -d db
```

### Bước 2: Cài đặt Python dependencies (lần đầu)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

pip install -r requirements_web.txt
```

### Bước 3: Đặt biến môi trường và chạy

**Windows (Command Prompt):**
```cmd
set DATABASE_URL=postgresql://devuser:devpass@localhost:5433/rowfollow_db
python run_web.py
```

**Windows (PowerShell):**
```powershell
$env:DATABASE_URL="postgresql://devuser:devpass@localhost:5433/rowfollow_db"
python run_web.py
```

**Linux/Mac:**
```bash
export DATABASE_URL=postgresql://devuser:devpass@localhost:5433/rowfollow_db
python run_web.py
```

Truy cập: **http://localhost:5050**

---

## Đăng nhập lần đầu

Hệ thống tự tạo tài khoản admin mặc định:
- **Email**: `admin@vnu.edu.vn`
- **Mật khẩu**: `admin123`

> Đổi mật khẩu ngay sau khi đăng nhập lần đầu!

---

## Thiết lập ban đầu

Sau khi đăng nhập admin, thực hiện theo thứ tự:

### 1. Tạo Khoa/Phòng ban

Vào **Quản lý → Khoa/Phòng ban**:
- Thêm các **Khoa** (loại: Khoa — bắt buộc có Bộ môn)
- Thêm các **Phòng ban** (loại: Phòng ban — không cần Bộ môn)

### 2. Tạo Bộ môn

Vào **Quản lý → Bộ môn**:
- Thêm Bộ môn cho từng Khoa đã tạo ở bước 1

### 3. Phân quyền Admin (nếu cần)

Vào **Quản lý → Quản lý Admin**:
- Gán quyền **Admin Khoa** cho trưởng khoa
- Gán quyền **Admin Bộ môn** cho trưởng bộ môn

### 4. Thêm người dùng

- Người dùng tự đăng ký tại trang đăng ký
- Hoặc Admin tạo tại **Quản lý → Người dùng**

---

## Các lệnh thường dùng

```bash
# Khởi động (Docker)
docker-compose -f docker-compose.dev.yml up -d

# Dừng
docker-compose -f docker-compose.dev.yml down

# Xem logs
docker-compose -f docker-compose.dev.yml logs -f web

# Rebuild sau khi sửa code
docker-compose -f docker-compose.dev.yml up -d --build

# Reset database hoàn toàn (xóa tất cả dữ liệu)
docker-compose -f docker-compose.dev.yml down -v
docker-compose -f docker-compose.dev.yml up -d --build
```

---

## Quy trình duyệt công trình

**Cán bộ thuộc Khoa** (có Bộ môn):
```
Nộp → Bộ môn xác nhận → Khoa duyệt → Trường phê duyệt
```

**Cán bộ thuộc Phòng ban**:
```
Nộp → Trường phê duyệt
```

## Hệ thống phân quyền

| Cấp | Phạm vi | Quyền hạn |
|-----|---------|-----------|
| Admin Trường (PKHCN) | Toàn trường | Duyệt cuối cùng, quản lý tất cả |
| Admin Khoa | Trong Khoa | Duyệt sau Bộ môn, quản lý trong Khoa |
| Admin Bộ môn | Trong Bộ môn | Xác nhận ban đầu |
| Người dùng | Cá nhân | Nộp công trình, xem báo cáo cá nhân |

### Nâng cấp từ phiên bản cũ (admin_level → AdminRole)

Phân quyền mới sử dụng bảng `admin_roles` làm nguồn chuẩn. Nếu dữ liệu cũ còn lưu ở cột `users.admin_level`,
hãy chạy backfill một lần:

```bash
python scripts/backfill_admin_roles.py
```

---

## Cấu trúc dự án

```
rowfollow/
├── app/
│   ├── __init__.py              # Flask app factory
│   ├── db_models.py             # Database models (SQLAlchemy)
│   ├── extensions.py            # Flask extensions (LoginManager, Migrate, CSRF)
│   ├── hours_calculator.py      # Tính giờ NCKH theo Quy chế
│   ├── blueprints/
│   │   ├── main/                # Trang chủ, dashboard, bảng quy đổi
│   │   ├── auth/                # Đăng nhập, đăng ký, profile
│   │   ├── publications/        # CRUD ấn phẩm khoa học
│   │   ├── projects/            # CRUD đề tài/dự án
│   │   ├── activities/          # CRUD hoạt động KHCN khác
│   │   ├── reports/             # Báo cáo, xuất CSV
│   │   ├── api/                 # API tra cứu tạp chí, đơn vị
│   │   └── admin/               # Quản trị: dashboard, users, approval, org, roles
│   ├── services/
│   │   └── approval.py          # Logic duyệt công trình + phân quyền
│   └── templates/               # Jinja2 templates (Bootstrap 5)
├── docker-compose.dev.yml       # Development config (DB + web)
├── docker-compose.yml           # Production config
├── Dockerfile
├── requirements_web.txt
├── run_web.py                   # Entry point
└── .env.example                 # Mẫu biến môi trường
```

---

## Thông tin kết nối Database (Development)

| Thông số | Giá trị |
|----------|---------|
| Host | `localhost` |
| Port | `5433` |
| Database | `rowfollow_db` |
| User | `devuser` |
| Password | `devpass` |

Dùng để kết nối từ DBeaver, pgAdmin hoặc công cụ quản lý DB khác.

---

## Liên hệ

- **Đơn vị**: Khoa Cơ học kỹ thuật và Tự động hóa — Trường Đại học Công nghệ (ĐHQGHN)
- **Quy chế tham chiếu**: QĐ 2706/QĐ-ĐHCN ngày 21/11/2024
