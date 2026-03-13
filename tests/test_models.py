"""
Tests for database models (User, Role) and the password handler module.
"""
import pytest
from models import db, User, Role
from password_handler import hash_password, verify_password


class TestPasswordHandler:
    def test_hash_returns_string(self):
        hashed = hash_password("mypassword")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_is_not_plaintext(self):
        pw = "mypassword"
        assert hash_password(pw) != pw

    def test_verify_correct_password(self):
        hashed = hash_password("correct_password")
        assert verify_password("correct_password", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_two_hashes_of_same_password_differ(self):
        # Argon2 uses random salts – same plaintext should produce different hashes
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2


class TestRoleModel:
    def test_create_role(self):
        role = Role(name="editor", description="Can edit content")
        db.session.add(role)
        db.session.commit()

        saved = db.session.get(Role, role.id)
        assert saved is not None
        assert saved.name == "editor"
        assert saved.description == "Can edit content"

    def test_role_name_is_unique(self):
        db.session.add(Role(name="unique_role"))
        db.session.commit()

        db.session.add(Role(name="unique_role"))
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


class TestUserModel:
    def test_create_user(self):
        user = User(email="test@example.com", active=True)
        user.set_password("ValidPass1!")
        db.session.add(user)
        db.session.commit()

        saved = db.session.get(User, user.id)
        assert saved is not None
        assert saved.email == "test@example.com"
        assert saved.active is True

    def test_email_is_unique(self):
        u1 = User(email="dup@example.com", active=True)
        u1.set_password("ValidPass1!")
        db.session.add(u1)
        db.session.commit()

        u2 = User(email="dup@example.com", active=True)
        u2.set_password("ValidPass1!")
        db.session.add(u2)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()

    def test_set_password_stores_hash(self):
        user = User(email="hash@example.com", active=True)
        user.set_password("PlainPassword1!")
        assert user.password != "PlainPassword1!"
        assert len(user.password) > 20

    def test_set_password_too_short_raises(self):
        user = User(email="short@example.com", active=True)
        with pytest.raises(ValueError):
            user.set_password("short")

    def test_set_password_exactly_min_length(self):
        # Exactly 8 characters should succeed (MIN_PASSWORD_LENGTH=8 in test env)
        user = User(email="minlen@example.com", active=True)
        user.set_password("Exactly8")  # 8 chars
        assert user.password is not None

    def test_verify_password_correct(self):
        user = User(email="verify@example.com", active=True)
        user.set_password("CorrectPass1!")
        db.session.add(user)
        db.session.commit()

        assert user.verify_password("CorrectPass1!") is True

    def test_verify_password_wrong(self):
        user = User(email="wrong@example.com", active=True)
        user.set_password("CorrectPass1!")
        db.session.add(user)
        db.session.commit()

        assert user.verify_password("WrongPass1!") is False

    def test_is_authenticated_active_user(self):
        user = User(email="active@example.com", active=True)
        assert user.is_authenticated() is True

    def test_is_authenticated_inactive_user(self):
        user = User(email="inactive@example.com", active=False)
        assert user.is_authenticated() is False

    def test_user_role_assignment(self):
        role = Role(name="tester", description="Tester role")
        user = User(email="roled@example.com", active=True)
        user.set_password("RoledPass1!")
        user.roles.append(role)
        db.session.add(user)
        db.session.commit()

        saved = db.session.get(User, user.id)
        assert len(saved.roles) == 1
        assert saved.roles[0].name == "tester"

    def test_user_multiple_roles(self):
        r1 = Role(name="viewer")
        r2 = Role(name="writer")
        user = User(email="multi@example.com", active=True)
        user.set_password("MultiPass1!")
        user.roles.extend([r1, r2])
        db.session.add(user)
        db.session.commit()

        saved = db.session.get(User, user.id)
        role_names = {r.name for r in saved.roles}
        assert role_names == {"viewer", "writer"}

    def test_user_no_roles_by_default(self):
        user = User(email="noroles@example.com", active=True)
        user.set_password("NoRoles1!!")
        db.session.add(user)
        db.session.commit()

        saved = db.session.get(User, user.id)
        assert saved.roles == []
