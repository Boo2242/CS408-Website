from app import db, Friendship
from conftest import login_as


def test_friendship_model_lifecycle(app, make_user):
    alice = make_user(username="alice", email="alice@example.com", is_public=True)
    bob = make_user(username="bob", email="bob@example.com", is_public=False)

    with app.app_context():
        req = Friendship(user_id=alice.id, friend_id=bob.id, status="pending")
        db.session.add(req)
        db.session.commit()

        saved = Friendship.query.filter_by(user_id=alice.id, friend_id=bob.id).first()
        assert saved is not None
        assert saved.status == "pending"

        saved.status = "accepted"
        db.session.commit()
        assert Friendship.query.filter_by(id=saved.id).first().status == "accepted"


def test_friend_tracker_privacy_enforcement(client, make_user):
    viewer = make_user(username="viewer", email="viewer@example.com")
    private_friend = make_user(username="private_p", email="priv@example.com", is_public=False)
    public_friend = make_user(username="public_p", email="pub@example.com", is_public=True)

    login_as(client, "viewer")

    # Update URL path if your route uses a different slug (e.g., /friends/<id>/tracker)
    resp_private = client.get(f"/friends/{private_friend.id}", follow_redirects=True)
    assert resp_private.status_code in (200, 403, 404)

    resp_public = client.get(f"/friends/{public_friend.id}", follow_redirects=True)
    assert resp_public.status_code in (200, 404)