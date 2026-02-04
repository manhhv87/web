"""
API routes for VNU-UET Research Hours Web Application.
Provides journal search from PostgreSQL journal_catalog table.
Also provides organization units and divisions for dynamic dropdowns.
"""

import logging

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required
from sqlalchemy import func

from app.db_models import OrganizationUnit, Division, JournalCatalog

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


@api_bp.route("/journals/search")
@login_required
def search_journals():
    """
    Search journals by name.

    Query params:
        q: Search query (min 2 characters)
        limit: Max results (default 10)

    Returns:
        JSON array of matching journals with name and quartile
    """
    query = request.args.get("q", "").strip()
    limit = request.args.get("limit", 10, type=int)

    if len(query) < 2:
        return jsonify([])

    try:
        search_pattern = f"%{query}%"
        prefix_pattern = f"{query}%"

        rows = (
            JournalCatalog.query
            .filter(
                (func.lower(JournalCatalog.name).like(func.lower(search_pattern)))
                | (JournalCatalog.issn.like(search_pattern))
                | (JournalCatalog.e_issn.like(search_pattern))
            )
            .order_by(
                # Prefer prefix matches
                (func.lower(JournalCatalog.name).like(func.lower(prefix_pattern))).desc(),
                JournalCatalog.name,
            )
            .limit(limit)
            .all()
        )

        results = []
        seen = set()
        for row in rows:
            if row.name in seen:
                continue
            seen.add(row.name)
            results.append(
                {
                    "name": row.name,
                    "quartile": row.sjr_best_quartile,
                    "issn": row.issn,
                    "publisher": row.sjr_publisher,
                }
            )

        return jsonify(results)

    except Exception as e:
        logger.exception("API error: %s", e)
        return jsonify({"error": "Lỗi hệ thống. Vui lòng thử lại sau."}), 500


@api_bp.route("/journals/<path:name>")
@login_required
def get_journal(name):
    """
    Get journal details by exact name.

    Returns:
        JSON object with journal details
    """
    try:
        row = (
            JournalCatalog.query
            .filter(func.lower(JournalCatalog.name) == func.lower(name))
            .first()
        )

        if not row:
            return jsonify({"error": "Journal not found"}), 404

        return jsonify(
            {
                "name": row.name,
                "quartile": row.sjr_best_quartile,
                "issn": row.issn,
                "e_issn": row.e_issn,
                "publisher": row.sjr_publisher,
                "sjr_score": row.sjr_score,
                "h_index": row.sjr_h_index,
            }
        )

    except Exception as e:
        logger.exception("API error: %s", e)
        return jsonify({"error": "Lỗi hệ thống. Vui lòng thử lại sau."}), 500


# =============================================================================
# ORGANIZATION UNITS & DIVISIONS API
# =============================================================================


@api_bp.route("/organization-units")
@login_required
def get_organization_units():
    """
    Lấy danh sách Khoa/Phòng ban.

    Query params:
        type: Filter by unit type ('faculty' | 'office')
        active_only: Only return active units (default: true)

    Returns:
        JSON array of organization units
    """
    unit_type = request.args.get("type", "").strip()
    active_only = request.args.get("active_only", "true").lower() == "true"

    query = OrganizationUnit.query

    if active_only:
        query = query.filter_by(is_active=True)

    if unit_type in ("faculty", "office"):
        query = query.filter_by(unit_type=unit_type)

    units = query.order_by(OrganizationUnit.unit_type, OrganizationUnit.name).all()

    results = []
    for unit in units:
        results.append(
            {
                "id": unit.id,
                "name": unit.name,
                "code": unit.code,
                "unit_type": unit.unit_type,
                "unit_type_display": unit.unit_type_display,
                "requires_division": unit.requires_division,
                "division_count": unit.division_count,
                "member_count": unit.member_count,
            }
        )

    return jsonify(results)


@api_bp.route("/organization-units/<int:unit_id>")
@login_required
def get_organization_unit(unit_id):
    """
    Lấy thông tin chi tiết của một Khoa/Phòng ban.

    Returns:
        JSON object with organization unit details
    """
    unit = OrganizationUnit.query.get(unit_id)

    if not unit:
        return jsonify({"error": "Organization unit not found"}), 404

    return jsonify(
        {
            "id": unit.id,
            "name": unit.name,
            "code": unit.code,
            "unit_type": unit.unit_type,
            "unit_type_display": unit.unit_type_display,
            "description": unit.description,
            "requires_division": unit.requires_division,
            "is_active": unit.is_active,
            "division_count": unit.division_count,
            "member_count": unit.member_count,
        }
    )


@api_bp.route("/organization-units/<int:unit_id>/divisions")
@login_required
def get_divisions_by_unit(unit_id):
    """
    Lấy danh sách Bộ môn theo Khoa/Phòng ban.

    Query params:
        active_only: Only return active divisions (default: true)

    Returns:
        JSON array of divisions
    """
    active_only = request.args.get("active_only", "true").lower() == "true"

    unit = OrganizationUnit.query.get(unit_id)
    if not unit:
        return jsonify({"error": "Organization unit not found"}), 404

    query = Division.query.filter_by(organization_unit_id=unit_id)

    if active_only:
        query = query.filter_by(is_active=True)

    divisions = query.order_by(Division.name).all()

    results = []
    for div in divisions:
        results.append(
            {
                "id": div.id,
                "name": div.name,
                "code": div.code,
                "organization_unit_id": div.organization_unit_id,
                "member_count": div.member_count,
            }
        )

    return jsonify(results)


@api_bp.route("/divisions")
@login_required
def get_all_divisions():
    """
    Lấy tất cả Bộ môn.

    Query params:
        active_only: Only return active divisions (default: true)
        org_unit_id: Filter by organization unit

    Returns:
        JSON array of divisions
    """
    active_only = request.args.get("active_only", "true").lower() == "true"
    org_unit_id = request.args.get("org_unit_id", type=int)

    query = Division.query

    if active_only:
        query = query.filter_by(is_active=True)

    if org_unit_id:
        query = query.filter_by(organization_unit_id=org_unit_id)

    divisions = (
        query.join(OrganizationUnit)
        .order_by(OrganizationUnit.name, Division.name)
        .all()
    )

    results = []
    for div in divisions:
        results.append(
            {
                "id": div.id,
                "name": div.name,
                "code": div.code,
                "full_name": div.full_name,
                "organization_unit_id": div.organization_unit_id,
                "organization_unit_name": div.organization_unit.name,
                "member_count": div.member_count,
            }
        )

    return jsonify(results)
