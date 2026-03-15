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
        img.to_dict(presigned_url=storage.get_presigned_url(img.s3_key))
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
        with PilImage.open(io.BytesIO(file_data)) as pil_img:
            width, height = pil_img.size
    except Exception:
        return jsonify({"error": "File is not a valid image"}), 415

    ext = "jpg" if content_type == "image/jpeg" else "png"
    s3_key = f"{uuid_module.uuid4()}.{ext}"

    try:
        storage.ensure_bucket()
        storage.upload_fileobj(io.BytesIO(file_data), s3_key, content_type)
    except Exception:
        current_app.logger.exception(
            "S3 upload failed for key=%s bucket=%s endpoint=%s",
            s3_key,
            storage.S3_BUCKET,
            storage.S3_ENDPOINT_URL,
        )
        return jsonify({"error": "Storage error. Please try again."}), 502

    image = Image(
        library_id=library_id,
        s3_key=s3_key,
        original_filename=file.filename,
        content_type=content_type,
        size=len(file_data),
        width=width,
        height=height,
    )
    db.session.add(image)
    db.session.commit()

    url = storage.get_presigned_url(s3_key)
    return jsonify(image.to_dict(presigned_url=url)), 201


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
