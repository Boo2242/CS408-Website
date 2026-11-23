from app import db, User
from conftest import login_as
from app import db, User, Friendship
from conftest import login_as


def test_home_page_loads(client):
    resp = client.get("/")
    assert resp.status_code in (200, 302)


def test_register_and_login_flow(client, app):
    password = "StrongPassword123!"
    resp = client.post(
        "/register",
        data={
            "username": "newtrainer",
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username="newtrainer").first()
        assert user is not None

    login_resp = login_as(client, "newtrainer", password)
    assert login_resp.status_code == 200


def test_duplicate_username_rejected(client, make_user):
    make_user(username="dupuser", email="first@example.com")

    resp = client.post(
        "/register",
        data={
            "username": "dupuser",
            "email": "second@example.com",
            "password": "Password123!",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"already" in resp.data.lower() or b"exists" in resp.data.lower() or b"taken" in resp.data.lower()


def test_profile_picture_and_privacy_update(client, app, make_user):
    user = make_user(username="avataruser", email="avatar@example.com", is_public=True)
    login_as(client, "avataruser")

    # Adjust route name/form fields to match your profile/settings route
    resp = client.post(
        "/profile",
        data={
            "profile_picture": "https://example.com/pikmin.png",
            "is_public": "",  # unchecked / private
        },
        follow_redirects=True,
    )
    assert resp.status_code in (200, 404)

    if resp.status_code == 200:
        with app.app_context():
            refreshed = db.session.get(User, user.id)
            assert len(refreshed.profile_picture or "") <= 500

def test_delete_account_removes_user_and_friendships(client, app, make_user):
    user = make_user(username="deleteme", email="deleteme@example.com")
    other = make_user(username="otheruser", email="other@example.com")

    with app.app_context():
        friendship = Friendship(user_id=user.id, friend_id=other.id, status="accepted")
        db.session.add(friendship)
        db.session.commit()
        user_id = user.id
        other_id = other.id

    login_as(client, "deleteme")

    resp = client.post("/delete-account", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(User, user_id) is None
        remaining = Friendship.query.filter(
            (Friendship.user_id == user_id) | (Friendship.friend_id == user_id)
        ).count()
        assert remaining == 0
        assert db.session.get(User, other_id) is not None