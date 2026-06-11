from app import create_app
from app.extensions import db
from app.utils.seed import seed_if_empty


app = create_app()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_if_empty()
    app.run(host="127.0.0.1", port=5000, debug=True)
