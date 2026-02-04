"""Flask extensions.

Keeping extensions in a dedicated module avoids circular imports and makes the
application factory cleaner.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from app.db_models import db, User


login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

login_manager.login_view = "auth.login"
login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."


@login_manager.user_loader
def load_user(user_id: str):
    # Flask-Login passes user_id as a string
    return User.query.get(int(user_id))


@login_manager.unauthorized_handler
def unauthorized_api():
    """Trả về JSON 401 cho API requests, redirect cho browser requests."""
    from flask import request, jsonify, redirect, url_for

    if (
        request.path.startswith("/api/")
        or request.accept_mimetypes.best == "application/json"
    ):
        return jsonify({"error": "Vui lòng đăng nhập để tiếp tục."}), 401
    return redirect(url_for("auth.login", next=request.path))
