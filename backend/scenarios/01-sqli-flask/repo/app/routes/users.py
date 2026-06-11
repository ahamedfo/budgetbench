from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.extensions import db


users_bp = Blueprint("users", __name__)


@users_bp.get("/me")
@login_required
def me():
    return jsonify(current_user.to_dict())


@users_bp.put("/me")
@login_required
def update_me():
    data = request.get_json(silent=True) or {}
    display_name = data.get("display_name")
    if display_name is not None:
        current_user.display_name = str(display_name)[:100]
    db.session.commit()
    return jsonify(current_user.to_dict())
