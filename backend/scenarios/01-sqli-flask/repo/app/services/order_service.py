from app.extensions import db
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product


def get_or_create_cart(user_id: int) -> Order:
    cart = Order.query.filter_by(user_id=user_id, status="cart").first()
    if cart is None:
        cart = Order(user_id=user_id, status="cart", total_cents=0)
        db.session.add(cart)
        db.session.commit()
    return cart


def add_to_cart(user_id: int, product_id: int, quantity: int) -> Order:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    product = db.session.get(Product, product_id)
    if product is None:
        raise LookupError(f"product {product_id} not found")
    cart = get_or_create_cart(user_id)
    existing = OrderItem.query.filter_by(order_id=cart.id, product_id=product_id).first()
    if existing:
        existing.quantity += quantity
    else:
        db.session.add(
            OrderItem(
                order_id=cart.id,
                product_id=product_id,
                quantity=quantity,
                price_cents=product.price_cents,
            )
        )
    cart.total_cents = sum(i.quantity * i.price_cents for i in cart.items) + (
        quantity * product.price_cents if not existing else 0
    )
    db.session.commit()
    return cart


def checkout(user_id: int) -> Order:
    cart = Order.query.filter_by(user_id=user_id, status="cart").first()
    if cart is None or not cart.items:
        raise LookupError("cart is empty")
    cart.status = "placed"
    cart.total_cents = sum(i.quantity * i.price_cents for i in cart.items)
    db.session.commit()
    return cart
