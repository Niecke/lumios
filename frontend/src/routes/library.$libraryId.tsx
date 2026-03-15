// library.$libraryId.tsx — library detail page
//
// Shows all photos in a library as a grid.
// Empty state: full-page drag-and-drop upload zone.
// Non-empty state: photo grid + drag-and-drop overlay + "Add photos" button.

import { createFileRoute, redirect, Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { authApi } from "../api/auth";
import { imagesApi, type Image } from "../api/images";
import { AppBar } from "../components/AppBar";

export const Route = createFileRoute("/library/$libraryId")({
  beforeLoad: async () => {
    try {
      const user = await authApi.me();
      return { user };
    } catch {
      throw redirect({ to: "/login" });
    }
  },
  component: LibraryDetailPage,
});

// ── Helpers ────────────────────────────────────────────────────────────────────

const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/jpg", "image/x-png"]);
const ACCEPTED_EXTS = new Set(["jpg", "jpeg", "png"]);

function filterFiles(files: FileList | File[]): File[] {
  return Array.from(files).filter((f) => {
    if (ACCEPTED_TYPES.has(f.type)) return true;
    // Fallback: some OSes/file managers don't set type on drag-and-drop
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    return ACCEPTED_EXTS.has(ext);
  });
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Upload queue item ─────────────────────────────────────────────────────────

interface UploadItem {
  id: string;
  file: File;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
}

// ── Image tile ────────────────────────────────────────────────────────────────

interface ImageTileProps {
  image: Image;
  libraryId: number;
  onDeleted: () => void;
  onView: () => void;
}

function ImageTile({ image, libraryId, onDeleted, onView }: ImageTileProps) {
  const [confirming, setConfirming] = useState(false);

  const remove = useMutation({
    mutationFn: () => imagesApi.delete(libraryId, image.id),
    onSuccess: onDeleted,
  });

  return (
    <div className="photo-tile">
      <img
        src={image.thumb_url ?? image.original_url ?? undefined}
        alt={image.filename}
        className="photo-tile__img"
        loading="lazy"
        onClick={onView}
        style={{ cursor: "pointer" }}
      />
      <div className="photo-tile__overlay">
        {confirming ? (
          <div className="photo-tile__confirm">
            <span>Delete?</span>
            <button
              className="icon-btn icon-btn--danger"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              title="Confirm delete"
            >
              <span className="material-icons">check</span>
            </button>
            <button
              className="icon-btn"
              onClick={() => setConfirming(false)}
              title="Cancel"
            >
              <span className="material-icons">close</span>
            </button>
          </div>
        ) : (
          <button
            className="icon-btn icon-btn--danger photo-tile__delete"
            onClick={() => setConfirming(true)}
            title="Delete image"
          >
            <span className="material-icons">delete</span>
          </button>
        )}
      </div>
      <div className="photo-tile__meta">
        {image.width && image.height
          ? `${image.width}×${image.height}`
          : image.filename}{" "}
        · {formatBytes(image.size)}
      </div>
    </div>
  );
}

// ── Lightbox ─────────────────────────────────────────────────────────────────

function Lightbox({ image, onClose }: { image: Image; onClose: () => void }) {
  return (
    <div className="lightbox" onClick={onClose}>
      <button className="lightbox__close" onClick={onClose} title="Close">
        <span className="material-icons">close</span>
      </button>
      <div className="lightbox__pair" onClick={(e) => e.stopPropagation()}>
        <div className="lightbox__side">
          <p className="lightbox__label">Original</p>
          <img
            src={image.original_url ?? undefined}
            alt={`${image.filename} — original`}
            className="lightbox__img"
          />
        </div>
        <div className="lightbox__side">
          <p className="lightbox__label">Preview</p>
          <img
            src={image.preview_url ?? undefined}
            alt={`${image.filename} — preview`}
            className="lightbox__img"
          />
        </div>
      </div>
    </div>
  );
}

// ── Drop zone ─────────────────────────────────────────────────────────────────

interface DropZoneProps {
  onFiles: (files: File[]) => void;
  compact?: boolean;
}

function DropZone({ onFiles, compact = false }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = filterFiles(e.dataTransfer.files);
      if (files.length) onFiles(files);
    },
    [onFiles]
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = filterFiles(e.target.files ?? []);
    if (files.length) onFiles(files);
    e.target.value = "";
  };

  return (
    <div
      className={`drop-zone ${dragging ? "drop-zone--active" : ""} ${compact ? "drop-zone--compact" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png"
        multiple
        style={{ display: "none" }}
        onChange={handleChange}
      />
      <span className="material-icons drop-zone__icon">cloud_upload</span>
      {!compact && (
        <>
          <p className="drop-zone__title">Drop photos here</p>
          <p className="drop-zone__hint">or click to browse — JPEG & PNG, up to 20 MB each</p>
        </>
      )}
      {compact && <p className="drop-zone__hint">Drop to add photos</p>}
    </div>
  );
}

// ── Upload progress list ──────────────────────────────────────────────────────

function UploadQueue({ items }: { items: UploadItem[] }) {
  const active = items.filter((i) => i.status !== "done");
  if (!active.length) return null;

  return (
    <div className="upload-queue">
      {active.map((item) => (
        <div key={item.id} className={`upload-item upload-item--${item.status}`}>
          <span className="material-icons upload-item__icon">
            {item.status === "uploading"
              ? "hourglass_top"
              : item.status === "error"
                ? "error_outline"
                : "schedule"}
          </span>
          <span className="upload-item__name">{item.file.name}</span>
          {item.status === "error" && (
            <span className="upload-item__error">{item.error}</span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function LibraryDetailPage() {
  const { libraryId } = Route.useParams();
  const { user } = Route.useRouteContext() as { user: { email: string } };
  const libId = Number(libraryId);
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [queue, setQueue] = useState<UploadItem[]>([]);
  const [viewImage, setViewImage] = useState<Image | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["images", libId],
    queryFn: () => imagesApi.list(libId),
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["images", libId] });
  }

  async function handleFiles(files: File[]) {
    const newItems: UploadItem[] = files.map((f) => ({
      id: crypto.randomUUID(),
      file: f,
      status: "pending",
    }));
    setQueue((q) => [...q, ...newItems]);

    for (const item of newItems) {
      setQueue((q) =>
        q.map((i) => (i.id === item.id ? { ...i, status: "uploading" } : i))
      );
      try {
        await imagesApi.upload(libId, item.file);
        setQueue((q) =>
          q.map((i) => (i.id === item.id ? { ...i, status: "done" } : i))
        );
        invalidate();
      } catch (err) {
        const message = err instanceof Error ? err.message : "Upload failed";
        setQueue((q) =>
          q.map((i) =>
            i.id === item.id ? { ...i, status: "error", error: message } : i
          )
        );
      }
    }
  }

  const images = data?.images ?? [];
  const hasImages = images.length > 0;

  return (
    <>
      <AppBar email={user.email} />

      <main className="page-content">
        <div className="page-header">
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <Link to="/" className="btn btn-text" style={{ padding: "0 0.5rem" }}>
              <span className="material-icons" style={{ fontSize: 20 }}>arrow_back</span>
            </Link>
            <h1>Photos</h1>
          </div>

          {hasImages && (
            <button className="btn btn-contained" onClick={() => fileInputRef.current?.click()}>
              <span className="material-icons">add_photo_alternate</span>
              Add photos
            </button>
          )}
        </div>

        {data && (
          <p className="library-count-hint">
            {data.count} of {data.max_images_per_library ?? "∞"} photos
          </p>
        )}

        {/* Hidden file input for the "Add photos" button */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png"
          multiple
          style={{ display: "none" }}
          onChange={(e) => {
            const files = filterFiles(e.target.files ?? []);
            if (files.length) handleFiles(files);
            e.target.value = "";
          }}
        />

        <UploadQueue items={queue} />

        {isLoading && (
          <div className="photo-grid">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="skeleton photo-tile photo-tile--skeleton" />
            ))}
          </div>
        )}

        {isError && (
          <div className="alert alert--error">Failed to load photos. Please refresh.</div>
        )}

        {!isLoading && !isError && !hasImages && (
          <DropZone onFiles={handleFiles} />
        )}

        {!isLoading && !isError && hasImages && (
          <DropZone onFiles={handleFiles} compact />
        )}

        {hasImages && (
          <div className="photo-grid">
            {images.map((img) => (
              <ImageTile
                key={img.id}
                image={img}
                libraryId={libId}
                onDeleted={invalidate}
                onView={() => setViewImage(img)}
              />
            ))}
          </div>
        )}

        {viewImage && (
          <Lightbox image={viewImage} onClose={() => setViewImage(null)} />
        )}
      </main>
    </>
  );
}
