from flask import Blueprint, jsonify
from models import db, Library, Image
from sqlalchemy import select
from services import storage

public_api = Blueprint("public_api", __name__, url_prefix="/public")


@public_api.route("/libraries/<library_uuid>", methods=["GET"])
def get_public_library(library_uuid: str):
    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    images = (
        db.session.execute(
            select(Image)
            .where(Image.library_id == library.id, Image.deleted_at.is_(None))
            .order_by(Image.created_at.desc())
        )
        .scalars()
        .all()
    )

    image_dicts = [
        {
            "uuid": img.uuid,
            "filename": img.original_filename,
            "width": img.width,
            "height": img.height,
            "preview_url": storage.get_presigned_url(img.storage_path("previews")),
            "thumb_url": storage.get_presigned_url(img.storage_path("thumbs")),
        }
        for img in images
    ]

    return jsonify(
        {
            "library": {
                "uuid": library.uuid,
                "name": library.name,
            },
            "images": image_dicts,
            "count": len(image_dicts),
        }
    )
