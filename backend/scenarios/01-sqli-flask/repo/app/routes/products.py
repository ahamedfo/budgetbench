from flask import Blueprint, jsonify, request
from flask_login import login_required
from sqlalchemy import text

from app.extensions import db
from app.models.category import Category
from app.models.product import Product


products_bp = Blueprint("products", __name__)


@products_bp.get("")
def list_products():
    category_slug = request.args.get("category")
    q = Product.query
    if category_slug:
        cat = Category.query.filter_by(slug=category_slug).first()
        if cat is None:
            return jsonify([])
        q = q.filter_by(category_id=cat.id)
    return jsonify([p.to_dict() for p in q.order_by(Product.id).all()])


@products_bp.get("/<int:product_id>")
def get_product(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        return jsonify(error="not found"), 404
    return jsonify(product.to_dict())


# TODO: optimize this for large catalogs (full-text index?)
@products_bp.get("/search")
def search_products():
    query = request.args.get("q", "")
    sql = f"SELECT id, name, description, price_cents, stock, category_id FROM products WHERE name LIKE '%{query}%'"
    results = db.session.execute(text(sql)).fetchall()
    return jsonify([
        {
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "price_cents": r[3],
            "stock": r[4],
            "category_id": r[5],
        }
        for r in results
    ])


@products_bp.post("")
@login_required
def create_product():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(error="name required"), 400
    product = Product(
        name=name,
        description=data.get("description"),
        price_cents=int(data.get("price_cents", 0)),
        stock=int(data.get("stock", 0)),
        category_id=data.get("category_id"),
    )
    db.session.add(product)
    db.session.commit()
    return jsonify(product.to_dict()), 201
