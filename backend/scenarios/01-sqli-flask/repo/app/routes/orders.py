from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.models.order import Order
from app.services.order_service import add_to_cart, checkout


orders_bp = Blueprint("orders", __name__)


@orders_bp.post("/cart")
@login_required
def add_item():
    data = request.get_json(silent=True) or {}
    try:
        product_id = int(data["product_id"])
        quantity = int(data.get("quantity", 1))
    except (KeyError, TypeError, ValueError):
        return jsonify(error="product_id (int) required"), 400
    try:
        cart = add_to_cart(current_user.id, product_id, quantity)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except LookupError as e:
        return jsonify(error=str(e)), 404
    return jsonify(cart.to_dict())


@orders_bp.post("/checkout")
@login_required
def do_checkout():
    try:
        order = checkout(current_user.id)
    except LookupError as e:
        return jsonify(error=str(e)), 400
    return jsonify(order.to_dict())


@orders_bp.get("/history")
@login_required
def history():
    orders = (
        Order.query.filter_by(user_id=current_user.id)
        .filter(Order.status != "cart")
        .order_by(Order.created_at.desc())
        .all()
    )
    return jsonify([o.to_dict() for o in orders])
