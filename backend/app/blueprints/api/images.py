from flask import Blueprint, request, jsonify, g, current_app
from security import require_api_auth, require_api_role
from models import db, User, Library, Image
from sqlalchemy import select
from datetime import datetime, timezone
import uuid as uuid_module
from PIL import Image as PilImage
import io
from services import storage

images_api = Blueprint("images_api", __name__, url_prefix="/libraries")

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
THUMB_SIZE = 300  # longest side in pixels

# Magic byte signatures for allowed image formats
MAGIC_BYTES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


def _get_library(library_id: int, user_id: int) -> Library | None:
    return db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


@images_api.route("/<int:library_id>/images", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def list_images(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    user = db.session.get(User, user_id)
    images = (
        db.session.execute(
            select(Image)
            .where(Image.library_id == library_id, Image.deleted_at.is_(None))
            .order_by(Image.created_at.desc())
        )
        .scalars()
        .all()
    )

    image_dicts = [
        img.to_dict(
            original_url=storage.get_presigned_url(img.storage_path("originals")),
            thumb_url=storage.get_presigned_url(img.storage_path("thumbs")),
        )
        for img in images
    ]

    return jsonify(
        {
            "images": image_dicts,
            "count": len(image_dicts),
            "max_images_per_library": user.max_images_per_library if user else None,
        }
    )


@images_api.route("/<int:library_id>/images", methods=["POST"])
@require_api_auth
@require_api_role("photographer")
def upload_image(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "User not found"}), 404

    current_count = db.session.execute(
        select(db.func.count())
        .select_from(Image)
        .where(Image.library_id == library_id, Image.deleted_at.is_(None))
    ).scalar()

    if current_count >= user.max_images_per_library:
        return (
            jsonify(
                {
                    "error": f"Image limit reached ({user.max_images_per_library}) for this library."
                }
            ),
            422,
        )

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        return jsonify({"error": "Only JPEG and PNG images are allowed"}), 415

    file_data = file.read()
    if len(file_data) > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 20 MB)"}), 413

    # Verify magic bytes match the claimed content type
    expected_magic = MAGIC_BYTES[content_type]
    if not file_data.startswith(expected_magic):
        return jsonify({"error": "File content does not match its declared type"}), 415

    # Pillow must be able to open the file — reject corrupt or disguised uploads
    try:
        pil_img = PilImage.open(io.BytesIO(file_data))
        width, height = pil_img.size
    except Exception:
        return jsonify({"error": "File is not a valid image"}), 415

    # Generate 300px thumbnail
    thumb_img = pil_img.copy()
    thumb_img.thumbnail((THUMB_SIZE, THUMB_SIZE))
    thumb_buf = io.BytesIO()
    thumb_img.save(thumb_buf, format="JPEG", quality=85)
    thumb_buf.seek(0)
    pil_img.close()
    thumb_img.close()

    ext = "jpg" if content_type == "image/jpeg" else "png"
    photo_uuid = str(uuid_module.uuid4())
    s3_key = f"{photo_uuid}.{ext}"

    image = Image(
        uuid=photo_uuid,
        library_id=library_id,
        s3_key=s3_key,
        original_filename=file.filename,
        content_type=content_type,
        size=len(file_data),
        width=width,
        height=height,
    )

    base_path = f"photos/{user_id}/{library_id}"
    original_path = f"{base_path}/originals/{s3_key}"
    thumb_path = f"{base_path}/thumbs/{s3_key}"
    try:
        storage.ensure_bucket()
        storage.upload_fileobj(io.BytesIO(file_data), original_path, content_type)
        storage.upload_fileobj(thumb_buf, thumb_path, "image/jpeg")
    except Exception:
        current_app.logger.exception(
            "GCS upload failed for key=%s bucket=%s endpoint=%s",
            original_path,
            storage.S3_BUCKET,
            storage.S3_ENDPOINT_URL,
        )
        return jsonify({"error": "Storage error. Please try again."}), 502

    db.session.add(image)
    db.session.commit()

    original_url = storage.get_presigned_url(original_path)
    thumb_url = storage.get_presigned_url(thumb_path)
    return jsonify(image.to_dict(original_url=original_url, thumb_url=thumb_url)), 201


@images_api.route("/<int:library_id>/images/<int:image_id>", methods=["DELETE"])
@require_api_auth
@require_api_role("photographer")
def delete_image(library_id: int, image_id: int):
    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    image = db.session.execute(
        select(Image).where(
            Image.id == image_id,
            Image.library_id == library_id,
            Image.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if image is None:
        return jsonify({"error": "Image not found"}), 404

    image.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return "", 204
