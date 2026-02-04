"""VNU-UET Research Hours application package.

This module exposes the Flask application factory `create_app()`.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from flask import Flask

from app.db_models import db, init_default_data
from app.extensions import csrf, limiter, login_manager, migrate


def create_app(config_class=None):
    """Application factory."""
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Configuration
    flask_env = (os.environ.get("FLASK_ENV", "") or os.environ.get("ENV", "")).lower()
    is_production = flask_env == "production"

    secret = os.environ.get("SECRET_KEY")
    if is_production and not secret:
        raise RuntimeError("SECRET_KEY must be set in production")
    app.config["SECRET_KEY"] = secret or "dev-only-unsafe-key"

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL must be set. Example: postgresql://user:pass@localhost:5432/dbname"
        )
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Avatar upload config
    avatar_dir = os.path.join(app.root_path, "static", "avatars")
    app.config["AVATAR_UPLOAD_FOLDER"] = avatar_dir
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB
    os.makedirs(avatar_dir, exist_ok=True)

    # Session cookie hardening
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_production,
        SESSION_COOKIE_NAME="vnu_research_session",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        REMEMBER_COOKIE_DURATION=timedelta(days=14),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=is_production,
        REMEMBER_COOKIE_SAMESITE="Lax",
    )

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Register blueprints
    from app.blueprints.main import main_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.publications import pub_bp
    from app.blueprints.projects import project_bp
    from app.blueprints.activities import activity_bp
    from app.blueprints.reports import report_bp
    from app.blueprints.api import api_bp
    from app.blueprints.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(pub_bp, url_prefix="/publications")
    app.register_blueprint(project_bp, url_prefix="/projects")
    app.register_blueprint(activity_bp, url_prefix="/activities")
    app.register_blueprint(report_bp, url_prefix="/reports")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # Create tables and init default data
    with app.app_context():
        auto_create = os.environ.get("AUTO_CREATE_DB")
        if auto_create is None:
            auto_create = "0" if is_production else "1"

        if auto_create == "1":
            db.create_all()

        # Ensure schema is up-to-date for new organization fields (best-effort)
        try:
            from app.db_models import ensure_user_org_columns

            ensure_user_org_columns(app)
        except Exception as e:
            app.logger.warning("ensure_user_org_columns failed: %s", e)

        try:
            init_default_data(app)
        except Exception as e:
            app.logger.warning("init_default_data failed: %s", e)

        try:
            from app.db_models import ensure_admin_role_constraints

            ensure_admin_role_constraints(app)
        except Exception as e:
            app.logger.warning("ensure_admin_role_constraints failed: %s", e)

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    # Context processor for templates
    @app.context_processor
    def inject_globals():
        return {
            "current_year": datetime.now().year,
            "app_name": "VNU-UET Research Hours",
        }

    @app.context_processor
    def inject_act_as():
        """Inject act-as role context for admin role switching dropdown."""
        try:
            from app.blueprints.admin.helpers import inject_act_as_context

            return inject_act_as_context()
        except Exception:
            return {}

    return app
