FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements_web.txt ./
RUN pip install --no-cache-dir -r requirements_web.txt

# Tạo non-root user để chạy app
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy source (in dev we will mount the code over this)
COPY . .

# Đổi ownership cho app user
RUN chown -R appuser:appgroup /app

# Chuyển sang non-root user
USER appuser

EXPOSE 5000

# Default command for production use Gunicorn; for dev we'll use flask run via compose
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "run_web:app"]
