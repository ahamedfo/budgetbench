from flask import jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager


db = SQLAlchemy()
login_manager = LoginManager()


@login_manager.user_loader
def load_user(user_id):
    from app.models.user import User
    return db.session.get(User, int(user_id))


@login_manager.unauthorized_handler
def _unauthorized():
    return jsonify(error="authentication required"), 401
