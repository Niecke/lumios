import io

from flask import (
    Blueprint, render_template, request, flash, redirect,
    url_for, current_app, abort, send_file, jsonify,
)
from sqlalchemy import select, func

from models import db, Document
from security import login_required
from current_user import current_user

documents = Blueprint('documents', __name__)

MAX_FILE_SIZE = 64 * 1024 * 1024   # 64 MB
MAX_DOCS_PER_USER = 100
_THUMBNAIL_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf'}


def _generate_thumbnail(data: bytes, content_type: str):
    """Return (thumbnail_bytes, 'image/jpeg') or (None, None) on failure."""
    thumb_size = (200, 200)
    try:
        if content_type in ('image/jpeg', 'image/png', 'image/gif', 'image/webp'):
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            img.thumbnail(thumb_size, Image.LANCZOS)
            if img.mode in ('RGBA', 'P', 'LA'):
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85)
            return buf.getvalue(), 'image/jpeg'

        if content_type == 'application/pdf':
            import fitz  # PyMuPDF
            from PIL import Image
            pdf = fitz.open(stream=data, filetype='pdf')
            page = pdf.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
            img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
            img.thumbnail(thumb_size, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85)
            return buf.getvalue(), 'image/jpeg'

    except Exception as exc:
        current_app.logger.warning('Thumbnail generation failed: %s', exc)

    return None, None


@documents.route('/documents/')
@login_required
def library():
    user_docs = db.session.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    ).scalars().all()
    return render_template(
        'documents/library.html',
        documents=user_docs,
        doc_count=len(user_docs),
        max_docs=MAX_DOCS_PER_USER,
    )


@documents.route('/documents/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided.'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'success': False, 'message': 'No file selected.'}), 400

    # Enforce per-user document cap
    doc_count = db.session.scalar(
        select(func.count(Document.id)).where(Document.user_id == current_user.id)
    )
    if doc_count >= MAX_DOCS_PER_USER:
        return jsonify({
            'success': False,
            'message': f'Document limit reached ({MAX_DOCS_PER_USER} max).',
        }), 400

    # Read and enforce size limit
    data = f.read(MAX_FILE_SIZE + 1)
    if len(data) > MAX_FILE_SIZE:
        return jsonify({
            'success': False,
            'message': 'File exceeds the 64 MB limit.',
        }), 400

    content_type = f.content_type or 'application/octet-stream'
    original_filename = f.filename
    thumbnail, thumbnail_content_type = _generate_thumbnail(data, content_type)

    doc = Document(
        user_id=current_user.id,
        title=original_filename,
        original_filename=original_filename,
        content_type=content_type,
        file_size=len(data),
        data=data,
        thumbnail=thumbnail,
        thumbnail_content_type=thumbnail_content_type,
    )
    db.session.add(doc)
    db.session.commit()

    current_app.logger.info(
        'Document uploaded: id=%s filename=%s size=%d user=%s',
        doc.id, original_filename, len(data), current_user.email,
        extra={'log_type': 'audit'},
    )
    return jsonify({'success': True, 'message': f'"{original_filename}" uploaded successfully.'})


@documents.route('/documents/<int:doc_id>/download')
@login_required
def download(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc or doc.user_id != current_user.id:
        abort(404)
    return send_file(
        io.BytesIO(doc.data),
        mimetype=doc.content_type,
        as_attachment=True,
        download_name=doc.original_filename,
    )


@documents.route('/documents/<int:doc_id>/thumbnail')
@login_required
def thumbnail(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc or doc.user_id != current_user.id:
        abort(404)
    if not doc.thumbnail:
        abort(404)
    return send_file(
        io.BytesIO(doc.thumbnail),
        mimetype=doc.thumbnail_content_type or 'image/jpeg',
    )


@documents.route('/documents/<int:doc_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc or doc.user_id != current_user.id:
        abort(404)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title cannot be empty.', 'error')
            return render_template('documents/edit.html', doc=doc)

        old_title = doc.title
        doc.title = title
        db.session.commit()

        current_app.logger.info(
            'Document edited: id=%s old_title=%r new_title=%r user=%s',
            doc.id, old_title, title, current_user.email,
            extra={'log_type': 'audit'},
        )
        flash('Document updated successfully.', 'success')
        return redirect(url_for('documents.library'))

    return render_template('documents/edit.html', doc=doc)


@documents.route('/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc or doc.user_id != current_user.id:
        abort(404)

    filename = doc.original_filename
    db.session.delete(doc)
    db.session.commit()

    current_app.logger.info(
        'Document deleted: id=%s filename=%s user=%s',
        doc_id, filename, current_user.email,
        extra={'log_type': 'audit'},
    )
    flash(f'"{filename}" deleted.', 'success')
    return redirect(url_for('documents.library'))
