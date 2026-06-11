from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required, login_user, logout_user

from app.extensions import db
from app.models.user import User
from app.services.auth_service import (
    hash_password,
    make_reset_token,
    verify_password,
    verify_reset_token,
)


auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = data.get("display_name") or ""

    if not email or not password:
        return jsonify(error="email and password required"), 400
    if len(password) < 8:
        return jsonify(error="password must be at least 8 chars"), 400
    if User.query.filter_by(email=email).first():
        return jsonify(error="email already registered"), 409

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if user is None or not verify_password(user, password):
        return jsonify(error="invalid credentials"), 401

    login_user(user)
    return jsonify(user.to_dict())


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return jsonify(status="logged out")


@auth_bp.post("/password-reset")
def password_reset_request():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    user = User.query.filter_by(email=email).first()
    if user is None:
        # don't leak which emails exist
        return jsonify(status="if the email exists, a reset link has been sent")
    token = make_reset_token(current_app.config["SECRET_KEY"], email)
    return jsonify(status="reset token issued", token=token)


@auth_bp.post("/password-reset/confirm")
def password_reset_confirm():
    data = request.get_json(silent=True) or {}
    token = data.get("token") or ""
    new_password = data.get("password") or ""
    if len(new_password) < 8:
        return jsonify(error="password must be at least 8 chars"), 400
    email = verify_reset_token(current_app.config["SECRET_KEY"], token)
    if email is None:
        return jsonify(error="invalid or expired token"), 400
    user = User.query.filter_by(email=email).first()
    if user is None:
        return jsonify(error="user not found"), 404
    user.password_hash = hash_password(new_password)
    db.session.commit()
    return jsonify(status="password updated")
