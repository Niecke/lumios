"""
Tests for the documents blueprint.

Covers: library, upload, download, thumbnail, edit, delete.
All tests use the shared fixtures from conftest.py (SQLite in-memory DB,
CSRF disabled, rate limiting disabled).
"""
import io
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from conftest import do_login
from models import db, Document, User
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_jpeg_bytes():
    """Return a minimal valid 10×10 JPEG."""
    from PIL import Image
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_png_bytes():
    """Return a minimal valid 10×10 PNG (RGBA)."""
    from PIL import Image
    img = Image.new("RGBA", (10, 10), color=(0, 255, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload_file(client, filename, data, content_type="text/plain"):
    """POST a file to /documents/upload and return the response."""
    return client.post(
        "/documents/upload",
        data={"file": (io.BytesIO(data), filename, content_type)},
        content_type="multipart/form-data",
    )


def get_user_doc(user_email):
    """Return the first Document row for a given user email."""
    u = db.session.execute(
        select(User).where(User.email == user_email)
    ).scalar_one()
    return db.session.execute(
        select(Document).where(Document.user_id == u.id)
    ).scalar_one()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user1():
    user = User(email="doc_user1@test.com", active=True)
    user.set_password("DocUser1Pass!")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def user2():
    user = User(email="doc_user2@test.com", active=True)
    user.set_password("DocUser2Pass!")
    db.session.add(user)
    db.session.commit()
    return user


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

class TestLibrary:
    def test_requires_login(self, client):
        rv = client.get("/documents/")
        assert rv.status_code == 302
        assert "/login" in rv.headers["Location"]

    def test_empty_library(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = client.get("/documents/")
        assert rv.status_code == 200
        assert b"My Documents" in rv.data
        assert b"0 / 100" in rv.data

    def test_library_shows_uploaded_doc(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "hello.txt", b"hello world")
        rv = client.get("/documents/")
        assert b"hello.txt" in rv.data

    def test_library_isolates_users(self, client, user1, user2):
        # User1 uploads a document
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "user1secret.txt", b"secret")
        client.post("/logout", follow_redirects=True)

        # User2 should not see it
        do_login(client, user2.email, "DocUser2Pass!")
        rv = client.get("/documents/")
        assert b"user1secret.txt" not in rv.data
        assert b"0 / 100" in rv.data


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class TestUpload:
    def test_requires_login(self, client):
        rv = upload_file(client, "test.txt", b"data")
        assert rv.status_code == 302
        assert "/login" in rv.headers["Location"]

    def test_upload_text_file(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = upload_file(client, "report.txt", b"some content")
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

    def test_upload_jpeg(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = upload_file(client, "photo.jpg", make_jpeg_bytes(), "image/jpeg")
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

    def test_upload_png(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = upload_file(client, "image.png", make_png_bytes(), "image/png")
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

    def test_upload_stores_correct_metadata(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        content = b"file content here"
        upload_file(client, "doc.txt", content)

        doc = get_user_doc(user1.email)
        assert doc.original_filename == "doc.txt"
        assert doc.title == "doc.txt"
        assert doc.file_size == len(content)
        assert doc.data == content

    def test_upload_no_file_part(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = client.post("/documents/upload",
                         data={},
                         content_type="multipart/form-data")
        assert rv.status_code == 400
        assert rv.get_json()["success"] is False

    def test_upload_empty_filename(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = client.post(
            "/documents/upload",
            data={"file": (io.BytesIO(b"data"), "", "text/plain")},
            content_type="multipart/form-data",
        )
        assert rv.status_code == 400
        assert rv.get_json()["success"] is False

    def test_upload_file_too_large(self, client, user1, monkeypatch):
        do_login(client, user1.email, "DocUser1Pass!")
        import blueprints.documents as doc_bp
        monkeypatch.setattr(doc_bp, "MAX_FILE_SIZE", 5)
        rv = upload_file(client, "big.txt", b"more than five bytes")
        assert rv.status_code == 400
        assert "limit" in rv.get_json()["message"].lower()

    def test_upload_doc_count_limit(self, client, user1, monkeypatch):
        do_login(client, user1.email, "DocUser1Pass!")
        import blueprints.documents as doc_bp
        monkeypatch.setattr(doc_bp, "MAX_DOCS_PER_USER", 0)
        rv = upload_file(client, "one.txt", b"content")
        assert rv.status_code == 400
        assert "limit" in rv.get_json()["message"].lower()

    def test_upload_increments_library_count(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "a.txt", b"a")
        upload_file(client, "b.txt", b"b")
        rv = client.get("/documents/")
        assert b"2 / 100" in rv.data

    def test_jpeg_upload_creates_thumbnail(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "photo.jpg", make_jpeg_bytes(), "image/jpeg")
        doc = get_user_doc(user1.email)
        assert doc.thumbnail is not None
        assert doc.thumbnail_content_type == "image/jpeg"

    def test_text_upload_has_no_thumbnail(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "note.txt", b"plain text", "text/plain")
        doc = get_user_doc(user1.email)
        assert doc.thumbnail is None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class TestDownload:
    def test_requires_login(self, client, user1):
        # Create doc directly so there is a valid ID
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "f.txt", b"data")
        doc = get_user_doc(user1.email)
        client.post("/logout", follow_redirects=True)

        rv = client.get(f"/documents/{doc.id}/download")
        assert rv.status_code == 302

    def test_download_own_doc(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        payload = b"hello download"
        upload_file(client, "dl.txt", payload)
        doc = get_user_doc(user1.email)

        rv = client.get(f"/documents/{doc.id}/download")
        assert rv.status_code == 200
        assert rv.data == payload

    def test_download_other_user_doc_returns_404(self, client, user1, user2):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "secret.txt", b"secret")
        doc = get_user_doc(user1.email)
        client.post("/logout", follow_redirects=True)

        do_login(client, user2.email, "DocUser2Pass!")
        rv = client.get(f"/documents/{doc.id}/download")
        assert rv.status_code == 404

    def test_download_nonexistent_returns_404(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = client.get("/documents/99999/download")
        assert rv.status_code == 404


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------

class TestThumbnail:
    def test_jpeg_has_thumbnail(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "img.jpg", make_jpeg_bytes(), "image/jpeg")
        doc = get_user_doc(user1.email)

        rv = client.get(f"/documents/{doc.id}/thumbnail")
        assert rv.status_code == 200
        assert rv.content_type.startswith("image/")

    def test_png_has_thumbnail(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "img.png", make_png_bytes(), "image/png")
        doc = get_user_doc(user1.email)

        rv = client.get(f"/documents/{doc.id}/thumbnail")
        assert rv.status_code == 200

    def test_text_has_no_thumbnail(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "note.txt", b"text", "text/plain")
        doc = get_user_doc(user1.email)

        rv = client.get(f"/documents/{doc.id}/thumbnail")
        assert rv.status_code == 404

    def test_thumbnail_other_user_returns_404(self, client, user1, user2):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "img.jpg", make_jpeg_bytes(), "image/jpeg")
        doc = get_user_doc(user1.email)
        client.post("/logout", follow_redirects=True)

        do_login(client, user2.email, "DocUser2Pass!")
        rv = client.get(f"/documents/{doc.id}/thumbnail")
        assert rv.status_code == 404

    def test_thumbnail_requires_login(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        upload_file(client, "img.jpg", make_jpeg_bytes(), "image/jpeg")
        doc = get_user_doc(user1.email)
        client.post("/logout", follow_redirects=True)

        rv = client.get(f"/documents/{doc.id}/thumbnail")
        assert rv.status_code == 302


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

class TestEdit:
    def _setup(self, client, email, password):
        do_login(client, email, password)
        upload_file(client, "original.txt", b"content")
        return get_user_doc(email)

    def test_edit_form_renders(self, client, user1):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        rv = client.get(f"/documents/{doc.id}/edit")
        assert rv.status_code == 200
        assert b"Edit Document" in rv.data
        assert doc.title.encode() in rv.data

    def test_edit_title(self, client, user1):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        rv = client.post(
            f"/documents/{doc.id}/edit",
            data={"title": "My New Title"},
            follow_redirects=True,
        )
        assert rv.status_code == 200
        assert b"My New Title" in rv.data

        db.session.expire(doc)
        assert doc.title == "My New Title"

    def test_edit_empty_title_rejected(self, client, user1):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        rv = client.post(f"/documents/{doc.id}/edit", data={"title": ""})
        assert rv.status_code == 200
        assert b"empty" in rv.data.lower()

    def test_edit_whitespace_title_rejected(self, client, user1):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        rv = client.post(f"/documents/{doc.id}/edit", data={"title": "   "})
        assert rv.status_code == 200
        assert b"empty" in rv.data.lower()

    def test_edit_requires_login(self, client, user1):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        client.post("/logout", follow_redirects=True)
        rv = client.get(f"/documents/{doc.id}/edit")
        assert rv.status_code == 302

    def test_edit_other_user_doc_returns_404(self, client, user1, user2):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        client.post("/logout", follow_redirects=True)

        do_login(client, user2.email, "DocUser2Pass!")
        rv = client.post(f"/documents/{doc.id}/edit", data={"title": "Stolen"})
        assert rv.status_code == 404

    def test_edit_nonexistent_returns_404(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = client.get("/documents/99999/edit")
        assert rv.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDelete:
    def _setup(self, client, email, password):
        do_login(client, email, password)
        upload_file(client, "todelete.txt", b"content")
        return get_user_doc(email)

    def test_delete_own_doc(self, client, user1):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        doc_id = doc.id

        rv = client.post(f"/documents/{doc_id}/delete", follow_redirects=True)
        assert rv.status_code == 200
        assert b"deleted" in rv.data.lower()
        assert db.session.get(Document, doc_id) is None

    def test_delete_other_user_doc_returns_404(self, client, user1, user2):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        client.post("/logout", follow_redirects=True)

        do_login(client, user2.email, "DocUser2Pass!")
        rv = client.post(f"/documents/{doc.id}/delete")
        assert rv.status_code == 404

    def test_delete_nonexistent_returns_404(self, client, user1):
        do_login(client, user1.email, "DocUser1Pass!")
        rv = client.post("/documents/99999/delete")
        assert rv.status_code == 404

    def test_delete_requires_login(self, client, user1):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        client.post("/logout", follow_redirects=True)
        rv = client.post(f"/documents/{doc.id}/delete")
        assert rv.status_code == 302

    def test_delete_updates_library_count(self, client, user1):
        doc = self._setup(client, user1.email, "DocUser1Pass!")
        # Library should show 1 doc before deletion
        rv = client.get("/documents/")
        assert b"1 / 100" in rv.data

        client.post(f"/documents/{doc.id}/delete", follow_redirects=True)
        rv = client.get("/documents/")
        assert b"0 / 100" in rv.data
