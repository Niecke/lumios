"""Upload quota check shared by every image and video upload endpoint."""

from flask import jsonify
from sqlalchemy import select, func
from models import db, User, Library, Image, Video


def check_upload_allowed(
    owner: User, library: Library, incoming_size: int, is_external: bool = False
):
    """Return an error response tuple if the upload does not fit, else None.

    Images and videos both count toward the library media limit and the owner's
    storage cap. The upload is rejected if it would push storage over the cap.
    """
    limits = owner.effective_limits

    # TODO: rename max_images_per_library to max_media in a later release
    current_count = (
        db.session.scalar(
            select(func.count(Image.id)).where(
                Image.library_id == library.id, Image.deleted_at.is_(None)
            )
        )
        or 0
    ) + (
        db.session.scalar(
            select(func.count(Video.id)).where(
                Video.library_id == library.id, Video.deleted_at.is_(None)
            )
        )
        or 0
    )

    if current_count >= limits["max_images_per_library"]:
        return (
            jsonify(
                {
                    "error": f"Media limit reached ({limits['max_images_per_library']}) for this library."
                }
            ),
            422,
        )

    image_storage = (
        db.session.scalar(
            select(func.coalesce(func.sum(Image.size), 0))
            .join(Image.library)
            .where(
                Library.user_id == owner.id,
                Image.deleted_at.is_(None),
                Library.deleted_at.is_(None),
            )
        )
        or 0
    )
    video_storage = (
        db.session.scalar(
            select(func.coalesce(func.sum(Video.size), 0))
            .join(Video.library)
            .where(
                Library.user_id == owner.id,
                Video.deleted_at.is_(None),
                Library.deleted_at.is_(None),
            )
        )
        or 0
    )

    if image_storage + video_storage + incoming_size > limits["max_storage_bytes"]:
        limit_mb = limits["max_storage_bytes"] // (1024 * 1024)
        target = "this library" if is_external else "your subscription"
        return (
            jsonify({"error": f"Storage limit reached ({limit_mb} MB) for {target}."}),
            422,
        )

    return None
