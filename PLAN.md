# Plan: Public Photo Uploads for Libraries

## Context
Photographers want to allow gallery visitors to contribute photos to a library (e.g., crowd-sourced event photos). A per-library opt-in setting controls this. Uploaded photos are tagged as "external" so photographers can distinguish them from their own uploads. Public uploads go through the identical processing pipeline (EXIF strip, watermark, thumbnail, S3 upload) as authenticated uploads.

---

## 1. Database Model Changes (`backend/app/models.py`)

**Library model** — add immediately after the `is_private` column:
```python
public_upload_enabled = db.Column(
    db.Boolean, nullable=False, default=False, server_default=db.false()
)
```

**Image model** — add immediately after `deleted_at`:
```python
is_external = db.Column(
    db.Boolean, nullable=False, default=False, server_default=db.false()
)
```

**`server_default=db.false()`** ensures existing rows are set to `False` by the migration.

After saving `models.py`, **auto-generate the migration** (do not write it manually):
```bash
podman exec -e FLASK_APP="main:create_app()" lumios-backend python3 -m flask db migrate -m "add public_upload_enabled and is_external"
podman exec -e FLASK_APP="main:create_app()" lumios-backend python3 -m flask db upgrade
```

---

## 2. Service Extraction (`backend/app/services/images.py`) — new file

The upload pipeline (~200 lines) currently lives inside the route handler in `blueprints/api/images.py`. The public endpoint needs to call the same logic without duplicating it. Create `services/images.py` following the existing `services/audit.py`, `services/storage.py` pattern.

**Move into this file:**
- All private helpers: `_strip_private_exif`, `_build_watermark_tile`, `_WATERMARK_TILE`, `_apply_logo_watermark`, `_create_watermarked_preview`, `_load_library_logo`, `_build_placeholder_image`
- All module-level constants: `ALLOWED_CONTENT_TYPES`, `MAX_FILE_SIZE`, `MAGIC_BYTES`, `PREVIEW_MAX_BYTES`, `THUMB_SIZE`, `WATERMARK_LOGO_MAX_BYTES`, `WATERMARK_LOGO_MAGIC`, `_PRIVATE_EXIF_TAGS`, etc.

**Add a validation helper:**
```python
def validate_upload(file_data: bytes, content_type: str, filename: str) -> None:
    """Raises ValueError with a user-facing message on any rejection."""
    # content type allowlist, file size, magic bytes, PIL open
```

**Add the central processing function:**
```python
def process_and_store_image(
    library: Library,
    owner: User,           # always the photographer (quota + S3 path owner)
    file_data: bytes,
    filename: str,
    content_type: str,
    is_external: bool = False,
) -> Image:
    # PIL open + EXIF rotate + dimensions
    # Thumbnail (600px JPEG q85)
    # Watermarked preview (_create_watermarked_preview)
    # EXIF strip (_strip_private_exif for JPEG)
    # UUID + s3_key generation
    # storage.upload_fileobj x3 (originals, previews, thumbs)
    # Image(is_external=is_external) DB insert
    # create_audit_log(AuditLogType.picture_uploaded, creator_id=owner.id if not is_external else None, ...)
    # db.session.commit()
    # cache_delete_pattern(f"public:library:{library.uuid}:*")
    # cache_delete(f"user:storage:{owner.id}")
    # return image
```

Key notes:
- S3 path always uses `owner.id` (photographer ID), regardless of who uploaded
- `creator_id=None` for public uploads (no authenticated user); `AuditLog.creator_id` is nullable
- Raises `ValueError` for validation failures, propagates storage exceptions

---

## 3. Backend API Changes

### 3a. `blueprints/api/images.py`
- Remove all moved helpers and constants; import them from `services.images`
- Refactor `upload_image` route handler to call `validate_upload()` then `process_and_store_image(..., is_external=False)`, keeping auth + quota checks in the route layer
- Update the mock target in `tests/test_api_images.py`: change `blueprints.api.images.storage` → `services.images.storage`

### 3b. `blueprints/api/libraries.py`
- Update import: `from services.images import ...` (currently imports from `blueprints.api.images` — fix to avoid circular imports)
- Add `public_upload_enabled` to the PATCH handler, after the `is_private` block:
  ```python
  if "public_upload_enabled" in data:
      value = data["public_upload_enabled"]
      if not isinstance(value, bool):
          return jsonify({"error": "public_upload_enabled must be a boolean"}), 400
      library.public_upload_enabled = value
  ```

### 3c. `blueprints/api/public.py`
- **Update `get_public_library` response** — add `"public_upload_enabled": library.public_upload_enabled` to the library dict in both the cache-miss path and the cached response structure.
- **Add new endpoint:**
  ```
  POST /api/v1/public/libraries/<library_uuid>/images
  Rate: 10/minute
  Auth: none
  ```
  Steps:
  1. Fetch library by UUID; 404 if deleted or `is_private`
  2. 403 if `not library.public_upload_enabled`
  3. Load `owner = db.session.get(User, library.user_id)`
  4. Quota check (per-library image count, total storage) against `owner.effective_limits` — 422 on breach
  5. Read file from `request.files["file"]`
  6. `validate_upload(...)` — 415/413/400 on `ValueError`
  7. `process_and_store_image(library, owner, ..., is_external=True)`
  8. Return `{"uuid": image.uuid}`, 201

---

## 4. Frontend Changes

### 4a. `frontend/src/api/libraries.ts`
- Add `public_upload_enabled: boolean` to the `Library` interface
- Add `public_upload_enabled?: boolean` to the `update()` patch parameter type

### 4b. `frontend/src/api/public.ts`
- Add `public_upload_enabled: boolean` to the `library` field in the `getLibrary` response type
- Add `uploadImage(libraryUuid: string, file: File): Promise<{ uuid: string }>`:
  ```typescript
  const form = new FormData();
  form.append("file", file);
  // POST /api/v1/public/libraries/{uuid}/images — no Auth header, no Content-Type header
  ```

### 4c. `frontend/src/routes/library.$libraryUuid.tsx`
- **`LibrarySettingsOverlay`** — add fourth settings entry after `is_private`:
  ```typescript
  {
    icon: "cloud_upload",
    label: "Allow visitor uploads",
    description: library.public_upload_enabled
      ? "Visitors can upload photos to this library"
      : "Only you can upload photos",
    checked: library.public_upload_enabled,
    onChange: (v: boolean) => updateLibrary.mutate({ public_upload_enabled: v }),
  }
  ```
- **`PublicLibraryView`** — add upload state + handler:
  ```typescript
  const [publicQueue, setPublicQueue] = useState<UploadItem[]>([]);
  async function handlePublicFiles(files: File[]) { /* mirrors handleFiles, calls publicApi.uploadImage, invalidates ["public-library", libraryUuid] */ }
  ```
- **Render conditionally** in the public view (above the photo grid, hidden when library is finished):
  ```tsx
  {library?.public_upload_enabled && !isFinished && (
    <>
      <DropZone onFiles={handlePublicFiles} compact={allImages.length > 0} />
      <UploadQueue items={publicQueue} />
    </>
  )}
  ```
  `DropZone` and `UploadQueue` are already defined in the same file and need no changes.

---

## 5. Tests

### `tests/test_api_public.py` — new `TestPublicUpload` class
- `test_upload_disabled_returns_403` — default `public_upload_enabled=False` → 403
- `test_upload_enabled_accepts_jpeg` — 201, returns `{"uuid": ...}`
- `test_upload_marks_image_as_external` — `image.is_external is True` in DB
- `test_private_library_returns_404` — `is_private=True` → 404 even if upload enabled
- `test_upload_rejects_wrong_content_type` — `text/plain` → 415
- `test_public_upload_enforces_quota` — library at image limit → 422
- `test_response_contains_public_upload_enabled` — existing GET response includes field, defaults False

### `tests/test_api_libraries.py`
- `test_patch_public_upload_enabled` — PATCH with `true` → 200, field reflected
- `test_patch_public_upload_enabled_invalid_type` — PATCH with `"yes"` → 400

---

## 6. Critical Files

| File | Change |
|------|--------|
| `backend/app/models.py` | Add `Library.public_upload_enabled`, `Image.is_external` |
| `backend/app/services/images.py` | **New file** — helpers + `process_and_store_image` + `validate_upload` |
| `backend/app/blueprints/api/images.py` | Remove moved code, call service, fix mock target |
| `backend/app/blueprints/api/libraries.py` | Fix import, add `public_upload_enabled` to PATCH |
| `backend/app/blueprints/api/public.py` | Add `public_upload_enabled` to GET response, add POST upload endpoint |
| `frontend/src/api/libraries.ts` | Add field to interface + patch type |
| `frontend/src/api/public.ts` | Add field to response type + `uploadImage()` |
| `frontend/src/routes/library.$libraryUuid.tsx` | Settings checkbox + public upload UI |
| `backend/app/tests/test_api_public.py` | New test class |
| `backend/app/tests/test_api_libraries.py` | Two new tests |
| `backend/app/tests/test_api_images.py` | Update mock target to `services.images.storage` |

---

## 7. Verification

```bash
# Backend tests (from lumios/)
source ./.venv/bin/activate
python -m pytest ./backend/app/tests/ -v

# End-to-end (requires running services)
podman-compose up -d --build --force-recreate
# 1. Log in as photographer, open a library settings → verify "Allow visitor uploads" checkbox
# 2. Enable it → open the share link in incognito → verify DropZone appears
# 3. Upload a JPEG via public view → verify it appears in the gallery
# 4. Check DB: SELECT is_external FROM images ORDER BY created_at DESC LIMIT 1; → should be TRUE
# 5. Disable setting → reload share link → verify DropZone is gone
# 6. Try uploading while quota is full → verify 422 error in upload queue
```
