from app.extensions import db
from app.models.category import Category
from app.models.product import Product
from app.models.user import User
from app.services.auth_service import hash_password


SAMPLE_CATEGORIES = [
    {"name": "Widgets", "slug": "widgets"},
    {"name": "Gadgets", "slug": "gadgets"},
    {"name": "Tools", "slug": "tools"},
]

SAMPLE_PRODUCTS = [
    {"name": "Standard Widget", "description": "A solid, dependable widget.",
     "price_cents": 1999, "stock": 100, "category_slug": "widgets"},
    {"name": "Premium Widget", "description": "Same as standard, but in chrome.",
     "price_cents": 4999, "stock": 50, "category_slug": "widgets"},
    {"name": "Pocket Gadget", "description": "Fits in your pocket.",
     "price_cents": 2499, "stock": 200, "category_slug": "gadgets"},
    {"name": "Heavy Duty Tool", "description": "For serious tinkering.",
     "price_cents": 8999, "stock": 25, "category_slug": "tools"},
    {"name": "Multi-Tool", "description": "Several tools in one.",
     "price_cents": 3499, "stock": 75, "category_slug": "tools"},
]


def seed_if_empty():
    if Category.query.count() == 0:
        for c in SAMPLE_CATEGORIES:
            db.session.add(Category(name=c["name"], slug=c["slug"]))
        db.session.commit()

    if Product.query.count() == 0:
        cats = {c.slug: c.id for c in Category.query.all()}
        for p in SAMPLE_PRODUCTS:
            db.session.add(
                Product(
                    name=p["name"],
                    description=p["description"],
                    price_cents=p["price_cents"],
                    stock=p["stock"],
                    category_id=cats.get(p["category_slug"]),
                )
            )
        db.session.commit()

    if User.query.count() == 0:
        db.session.add(
            User(
                email="demo@example.com",
                password_hash=hash_password("demo1234"),
                display_name="Demo User",
            )
        )
        db.session.commit()
