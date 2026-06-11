from flask import Flask, jsonify

from app.config import Config
from app.extensions import db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    from app.routes.auth import auth_bp
    from app.routes.users import users_bp
    from app.routes.products import products_bp
    from app.routes.orders import orders_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(products_bp, url_prefix="/products")
    app.register_blueprint(orders_bp, url_prefix="/orders")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/categories")
    def categories():
        from app.models.category import Category
        return jsonify([{"id": c.id, "name": c.name} for c in Category.query.all()])

    return app
