import os
import sys
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app import app as flask_app, db as _db, User, Friendship


@pytest.fixture
def app(tmp_path):
    db_file = tmp_path / "test_pikmin.db"
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_file}",
        WTF_CSRF_ENABLED=False,
    )

    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    def _make_user(username="trainer1", email="t1@example.com", password="password123", is_public=True, profile_picture=None):
        with app.app_context():
            user = User(
                username=username,
                email=email,
                is_public=is_public,
                profile_picture=profile_picture,
            )
            if hasattr(user, "set_password"):
                user.set_password(password)
            else:
                from werkzeug.security import generate_password_hash
                user.password = generate_password_hash(password)
            _db.session.add(user)
            _db.session.commit()
            _db.session.refresh(user)
            return user
    return _make_user


def login_as(client, username, password="password123"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )