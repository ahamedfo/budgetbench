# Acme Store API

A small SaaS-style storefront backend: users, products with categories,
and orders. Built with Flask + SQLAlchemy + Flask-Login.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Visit `http://localhost:5000/health` to confirm it's up.

## Layout

```
app/
├── __init__.py        # create_app() factory
├── config.py          # Config classes
├── extensions.py      # db, login_manager singletons
├── models/            # SQLAlchemy models
├── routes/            # Blueprints — auth, users, products, orders
├── services/          # Business logic
└── utils/             # seed.py for test data
tests/                 # pytest suite
```

## API surface

| Method | Route                       | Notes |
|--------|-----------------------------|-------|
| POST   | `/auth/signup`              | Create user |
| POST   | `/auth/login`               | Session login |
| POST   | `/auth/logout`              |  |
| POST   | `/auth/password-reset`      | Issue reset token |
| GET    | `/users/me`                 | Current user (auth) |
| PUT    | `/users/me`                 | Update profile (auth) |
| GET    | `/products`                 | List all products |
| GET    | `/products/<id>`            | Product detail |
| GET    | `/products/search?q=…`      | Search by name |
| POST   | `/products`                 | Create (auth) |
| GET    | `/categories`               | List categories |
| POST   | `/orders/cart`              | Add to cart (auth) |
| POST   | `/orders/checkout`          | Checkout (auth) |
| GET    | `/orders/history`           | Past orders (auth) |

## Test

```bash
pytest -q
```

## TODO

- Add rate limiting on auth endpoints
- Optimize search for large catalogs
- Pagination on `/products`
