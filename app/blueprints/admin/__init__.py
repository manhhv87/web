"""Admin blueprint package."""

from flask import Blueprint

admin_bp = Blueprint("admin", __name__)

# Import route modules so decorators attach to `admin_bp`.
from . import dashboard  # noqa: F401
from . import users  # noqa: F401
from . import approval  # noqa: F401
from . import org  # noqa: F401
from . import reports  # noqa: F401
from . import admin_roles  # noqa: F401
