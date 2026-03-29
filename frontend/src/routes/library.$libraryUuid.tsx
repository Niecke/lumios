// library.$libraryUuid.tsx — library detail page
//
// Authenticated photographers see the full management view (upload, delete, share).
// Unauthenticated visitors see a read-only public gallery.

import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { authApi } from "../api/auth";
import { librariesApi } from "../api/libraries";
import { imagesApi, type Image } from "../api/images";
import { publicApi, type PublicImage } from "../api/public";
import { AppBar } from "../components/AppBar";

export const Route = createFileRoute("/library/$libraryUuid")({
  beforeLoad: async () => {
    try {
      const user = await authApi.me();
      return { user, isAuthenticated: true as const };
    } catch {
      return { user: null, isAuthenticated: false as const };
    }
  },
  component: LibraryPage,
});

// ── Helpers ────────────────────────────────────────────────────────────────────

const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/jpg", "image/x-png"]);
const ACCEPTED_EXTS = new Set(["jpg", "jpeg", "png"]);

function filterFiles(files: FileList | File[]): File[] {
  return Array.from(files).filter((f) => {
    if (ACCEPTED_TYPES.has(f.type)) return true;
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

// ── Image tile (authenticated) ────────────────────────────────────────────────

interface ImageTileProps {
  image: Image;
  libraryId: number;
  onDeleted: () => void;
  onView: () => void;
}

function ImageTile({ image, libraryId, onDeleted, onView }: ImageTileProps) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      await imagesApi.delete(libraryId, image.id);
      onDeleted();
    } finally {
      setDeleting(false);
    }
  }

  const isLiked = image.customer_state === "liked";

  return (
    <div className="photo-tile">
      {isLiked && (
        <div className="photo-tile__liked-badge" title="Liked by customer">
          <span className="material-icons">favorite</span>
        </div>
      )}
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
              onClick={handleDelete}
              disabled={deleting}
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

// ── Lightbox (authenticated — original + preview) ────────────────────────────

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

// ── Lightbox (public — preview only) ─────────────────────────────────────────

function PublicLightbox({ image, onClose }: { image: PublicImage; onClose: () => void }) {
  return (
    <div className="lightbox" onClick={onClose}>
      <button className="lightbox__close" onClick={onClose} title="Close">
        <span className="material-icons">close</span>
      </button>
      <div className="lightbox__content" onClick={(e) => e.stopPropagation()}>
        <img
          src={image.preview_url}
          alt={image.filename}
          className="lightbox__img"
        />
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

// ── Share dialog ──────────────────────────────────────────────────────────────

function ShareDialog({ onClose }: { onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const shareUrl = window.location.href;

  async function copyToClipboard() {
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2>Share Library</h2>
        <p style={{ marginBottom: "0.75rem", color: "var(--clr-on-surface-var)" }}>
          Anyone with this link can view the photos in this library.
        </p>
        <input
          type="text"
          readOnly
          value={shareUrl}
          className="share-dialog__url"
          onFocus={(e) => e.target.select()}
        />
        <div className="dialog__actions">
          <a className="btn btn-outlined" href={shareUrl} target="_blank" rel="noopener noreferrer">
            <span className="material-icons" style={{ fontSize: 18 }}>open_in_new</span>
            Open
          </a>
          <button className="btn btn-contained" onClick={copyToClipboard}>
            <span className="material-icons" style={{ fontSize: 18 }}>
              {copied ? "check" : "content_copy"}
            </span>
            {copied ? "Copied!" : "Copy"}
          </button>
          <button className="btn btn-text" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Watermark settings ────────────────────────────────────────────────────────

const WATERMARK_POSITIONS = [
  { value: "top_left",     icon: "north_west",  label: "Top left" },
  { value: "top_right",    icon: "north_east",  label: "Top right" },
  { value: "center",       icon: "filter_center_focus", label: "Center" },
  { value: "bottom_left",  icon: "south_west",  label: "Bottom left" },
  { value: "bottom_right", icon: "south_east",  label: "Bottom right" },
];

function WatermarkSettings({
  library,
  onUpdate,
}: {
  library: { id: number; watermark_gcs_key: string | null; watermark_scale: number | null; watermark_position: string | null };
  onUpdate: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const initialScale = Math.round((library.watermark_scale ?? 0.2) * 100);
  const initialPosition = library.watermark_position ?? "bottom_right";
  const [pendingScale, setPendingScale] = useState(initialScale);
  const [pendingPosition, setPendingPosition] = useState(initialPosition);
  const [saving, setSaving] = useState(false);

  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const prevObjectUrl = useRef<string | null>(null);

  // Sync local state when library prop changes (e.g. after upload/save)
  useEffect(() => {
    setPendingScale(Math.round((library.watermark_scale ?? 0.2) * 100));
    setPendingPosition(library.watermark_position ?? "bottom_right");
  }, [library.watermark_scale, library.watermark_position]);

  // Fetch watermark preview whenever logo is set and pending params change (debounced)
  useEffect(() => {
    if (!library.watermark_gcs_key) {
      if (prevObjectUrl.current) {
        URL.revokeObjectURL(prevObjectUrl.current);
        prevObjectUrl.current = null;
      }
      setPreviewUrl(null);
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    const timer = setTimeout(() => {
      librariesApi
        .fetchWatermarkPreview(library.id, pendingScale / 100, pendingPosition)
        .then((url) => {
          if (prevObjectUrl.current) URL.revokeObjectURL(prevObjectUrl.current);
          prevObjectUrl.current = url;
          setPreviewUrl(url);
          setPreviewLoading(false);
        })
        .catch((err) => {
          setPreviewError(err instanceof Error ? err.message : "Failed to load preview");
          setPreviewLoading(false);
        });
    }, 600);
    return () => clearTimeout(timer);
  }, [library.id, library.watermark_gcs_key, pendingScale, pendingPosition]);

  // Revoke object URL on unmount
  useEffect(() => {
    return () => {
      if (prevObjectUrl.current) URL.revokeObjectURL(prevObjectUrl.current);
    };
  }, []);

  async function handleLogoFile(file: File) {
    setUploadError(null);
    setUploading(true);
    try {
      await librariesApi.uploadWatermark(library.id, file);
      onUpdate();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleRemove() {
    setDeleting(true);
    try {
      await librariesApi.deleteWatermark(library.id);
      onUpdate();
    } finally {
      setDeleting(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    try {
      await librariesApi.update(library.id, {
        watermark_scale: pendingScale / 100,
        watermark_position: pendingPosition,
      });
      onUpdate();
    } finally {
      setSaving(false);
    }
  }

  const hasLogo = Boolean(library.watermark_gcs_key);
  const isDirty =
    pendingScale !== Math.round((library.watermark_scale ?? 0.2) * 100) ||
    pendingPosition !== (library.watermark_position ?? "bottom_right");

  return (
    <div style={{ marginBottom: "0.5rem", background: "var(--clr-surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--clr-outline)", padding: "0.75rem 1rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem" }}>
        <span className="material-icons" style={{ fontSize: 20, color: "var(--clr-on-surface-var)" }}>branding_watermark</span>
        <span style={{ fontWeight: 500, fontSize: "0.9rem" }}>Watermark / Logo</span>
      </div>

      {/* Logo upload row */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
        {hasLogo && (
          <span style={{ fontSize: "0.8rem", color: "var(--clr-on-surface-var)" }}>Logo set</span>
        )}
        <button
          className="btn btn-outlined"
          style={{ fontSize: "0.8rem" }}
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
        >
          <span className="material-icons" style={{ fontSize: 16 }}>upload</span>
          {uploading ? "Uploading…" : hasLogo ? "Replace PNG" : "Upload PNG"}
        </button>
        {hasLogo && (
          <button
            className="btn btn-text"
            style={{ fontSize: "0.8rem", color: "var(--clr-error)" }}
            onClick={handleRemove}
            disabled={deleting}
          >
            <span className="material-icons" style={{ fontSize: 16 }}>delete</span>
            {deleting ? "Removing…" : "Remove"}
          </button>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleLogoFile(file);
            e.target.value = "";
          }}
        />
      </div>
      {uploadError && (
        <div className="alert alert--error" style={{ marginBottom: "0.5rem", fontSize: "0.8rem" }}>{uploadError}</div>
      )}

      {/* Scale slider */}
      <div style={{ marginBottom: "0.75rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.25rem" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--clr-on-surface-var)" }}>Size</span>
          <span style={{ fontSize: "0.8rem", fontWeight: 500 }}>{pendingScale}%</span>
        </div>
        <input
          type="range"
          min={5}
          max={50}
          step={1}
          value={pendingScale}
          onChange={(e) => setPendingScale(Number(e.target.value))}
          style={{ width: "100%", accentColor: "var(--clr-primary)" }}
        />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.7rem", color: "var(--clr-on-surface-var)" }}>
          <span>5%</span>
          <span>50%</span>
        </div>
      </div>

      {/* Position picker */}
      <div style={{ marginBottom: "0.75rem" }}>
        <div style={{ fontSize: "0.8rem", color: "var(--clr-on-surface-var)", marginBottom: "0.4rem" }}>Position</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 2rem)", gap: "0.25rem" }}>
          {WATERMARK_POSITIONS.map(({ value, icon, label }) => (
            <button
              key={value}
              title={label}
              onClick={() => setPendingPosition(value)}
              className={`btn ${pendingPosition === value ? "btn-contained" : "btn-outlined"}`}
              style={{ padding: "0.25rem", minWidth: 0, width: "2rem", height: "2rem" }}
            >
              <span className="material-icons" style={{ fontSize: 16 }}>{icon}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Save button */}
      {(isDirty || hasLogo) && (
        <button
          className="btn btn-contained"
          style={{ fontSize: "0.8rem", marginBottom: hasLogo ? "0.75rem" : 0 }}
          onClick={handleSave}
          disabled={saving || !isDirty}
        >
          {saving ? "Saving…" : "Save position & size"}
        </button>
      )}

      {/* Preview */}
      {hasLogo && (
        <div>
          <div style={{ fontSize: "0.8rem", color: "var(--clr-on-surface-var)", marginBottom: "0.4rem" }}>Preview</div>
          <div style={{ position: "relative", background: "var(--clr-surface-var)", borderRadius: "var(--radius-sm)", minHeight: "6rem", display: "flex", alignItems: "center", justifyContent: "center" }}>
            {previewLoading && (
              <span className="material-icons" style={{ fontSize: 24, color: "var(--clr-on-surface-var)", animation: "spin 1s linear infinite" }}>hourglass_top</span>
            )}
            {!previewLoading && previewError && (
              <span style={{ fontSize: "0.8rem", color: "var(--clr-error)" }}>{previewError}</span>
            )}
            {!previewLoading && !previewError && previewUrl && (
              <img
                src={previewUrl}
                alt="Watermark preview"
                style={{ maxWidth: "100%", maxHeight: "20rem", borderRadius: "var(--radius-sm)", display: "block" }}
              />
            )}
            {!previewLoading && !previewError && !previewUrl && (
              <span style={{ fontSize: "0.8rem", color: "var(--clr-on-surface-var)" }}>Upload a photo to see preview</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Library settings overlay ──────────────────────────────────────────────────

function LibrarySettingsOverlay({
  library,
  onUpdate,
  onClose,
  updateLibrary,
}: {
  library: { id: number; use_original_as_preview: boolean; download_enabled: boolean; is_private: boolean; watermark_gcs_key: string | null; watermark_scale: number | null; watermark_position: string | null };
  onUpdate: () => void;
  onClose: () => void;
  updateLibrary: { mutate: (patch: { use_original_as_preview?: boolean; download_enabled?: boolean; is_private?: boolean }) => void; isPending: boolean };
}) {
  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog dialog--settings" onClick={(e) => e.stopPropagation()}>
        <div className="dialog__header">
          <h2>Library Settings</h2>
          <button className="icon-btn" onClick={onClose} title="Close">
            <span className="material-icons">close</span>
          </button>
        </div>

        <div className="settings-section-label">Sharing</div>
        <div style={{ background: "var(--clr-background)", borderRadius: "var(--radius-sm)", border: "1px solid var(--clr-outline)", overflow: "hidden" }}>
          {[
            {
              icon: "photo_filter",
              label: "Use originals as preview",
              description: library.use_original_as_preview
                ? "Customers see the original, uncompressed photos"
                : "Customers see watermarked preview images",
              checked: library.use_original_as_preview,
              onChange: (v: boolean) => updateLibrary.mutate({ use_original_as_preview: v }),
            },
            {
              icon: "download",
              label: "Allow download",
              description: library.download_enabled
                ? "Customers see a download button on each photo"
                : "No download button shown to customers",
              checked: library.download_enabled,
              onChange: (v: boolean) => updateLibrary.mutate({ download_enabled: v }),
            },
            {
              icon: "lock",
              label: "Private library",
              description: library.is_private
                ? "Only you can access this library — share link is disabled"
                : "Anyone with the link can view this library",
              checked: library.is_private,
              onChange: (v: boolean) => updateLibrary.mutate({ is_private: v }),
            },
          ].map(({ icon, label, description, checked, onChange }, i, arr) => (
            <div
              key={label}
              style={{
                display: "flex", alignItems: "center", gap: "0.75rem",
                padding: "0.75rem 1rem",
                borderBottom: i < arr.length - 1 ? "1px solid var(--clr-outline)" : undefined,
              }}
            >
              <span className="material-icons" style={{ fontSize: 20, color: "var(--clr-on-surface-var)" }}>{icon}</span>
              <div>
                <div style={{ fontWeight: 500, fontSize: "0.9rem" }}>{label}</div>
                <div style={{ fontSize: "0.8rem", color: "var(--clr-on-surface-var)" }}>{description}</div>
              </div>
              <label style={{ marginLeft: "auto", display: "flex", alignItems: "center", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => onChange(e.target.checked)}
                  disabled={updateLibrary.isPending}
                  style={{ width: 18, height: 18, accentColor: "var(--clr-primary)", cursor: "pointer" }}
                />
              </label>
            </div>
          ))}
        </div>

        <div className="settings-section-label">Watermark / Logo</div>
        <WatermarkSettings library={library} onUpdate={onUpdate} />
      </div>
    </div>
  );
}

// ── Router component — delegates to authenticated or public view ─────────────

function LibraryPage() {
  const { libraryUuid } = Route.useParams();
  const { user, isAuthenticated } = Route.useRouteContext() as {
    user: { email: string; name?: string; picture?: string } | null;
    isAuthenticated: boolean;
  };

  if (isAuthenticated && user) {
    return <AuthenticatedLibraryView libraryUuid={libraryUuid} user={user} />;
  }
  return <PublicLibraryView libraryUuid={libraryUuid} />;
}

// ── Authenticated view (full management) ─────────────────────────────────────

function AuthenticatedLibraryView({ libraryUuid, user }: { libraryUuid: string; user: { email: string; name?: string; picture?: string } }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [queue, setQueue] = useState<UploadItem[]>([]);
  const [viewImage, setViewImage] = useState<Image | null>(null);
  const [showShare, setShowShare] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showLikedOnly, setShowLikedOnly] = useState(false);
  const [renamingLib, setRenamingLib] = useState(false);
  const [editLibName, setEditLibName] = useState("");

  const { data: library, refetch: refetchLibrary } = useQuery({
    queryKey: ["library", libraryUuid],
    queryFn: () => librariesApi.getByUuid(libraryUuid),
  });

  const updateLibrary = useMutation({
    mutationFn: (patch: { name?: string; use_original_as_preview?: boolean; download_enabled?: boolean; is_private?: boolean; watermark_scale?: number; watermark_position?: string }) =>
      librariesApi.update(library!.id, patch),
    onSuccess: () => {
      refetchLibrary();
      queryClient.invalidateQueries({ queryKey: ["libraries"] });
    },
  });

  function startRenameLib() {
    setEditLibName(library?.name ?? "");
    setRenamingLib(true);
  }

  function submitRenameLib(e: { preventDefault(): void }) {
    e.preventDefault();
    const trimmed = editLibName.trim();
    if (!trimmed) return;
    updateLibrary.mutate({ name: trimmed }, { onSuccess: () => setRenamingLib(false) });
  }

  const libId = library?.id;

  const { data, isLoading, isError } = useQuery({
    queryKey: ["images", libId],
    queryFn: () => imagesApi.list(libId!),
    enabled: libId !== undefined,
  });

  function invalidate() {
    if (libId !== undefined) {
      queryClient.invalidateQueries({ queryKey: ["images", libId] });
    }
  }

  async function handleFiles(files: File[]) {
    if (libId === undefined) return;
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

  const allImages = data?.images ?? [];
  const hasImages = allImages.length > 0;
  const likedCount = useMemo(
    () => allImages.filter((img) => img.customer_state === "liked").length,
    [allImages]
  );
  const images = showLikedOnly
    ? allImages.filter((img) => img.customer_state === "liked")
    : allImages;

  return (
    <>
      <AppBar name={user.name} picture={user.picture} />

      <main className="page-content">
        <div className="page-header">
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
            <Link to="/" className="btn btn-text" style={{ padding: "0 0.5rem" }}>
              <span className="material-icons" style={{ fontSize: 20 }}>arrow_back</span>
            </Link>
            {renamingLib ? (
              <form onSubmit={submitRenameLib} style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                <input
                  type="text"
                  value={editLibName}
                  onChange={(e) => setEditLibName(e.target.value)}
                  maxLength={255}
                  autoFocus
                  disabled={updateLibrary.isPending}
                  style={{ fontSize: "1.25rem", fontWeight: 600, padding: "0.2rem 0.4rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--clr-outline)" }}
                />
                <button type="submit" className="icon-btn" disabled={!editLibName.trim() || updateLibrary.isPending} title="Save">
                  <span className="material-icons">check</span>
                </button>
                <button type="button" className="icon-btn" onClick={() => setRenamingLib(false)} title="Cancel">
                  <span className="material-icons">close</span>
                </button>
              </form>
            ) : (
              <>
                <h1>{library?.name ?? "Library"}</h1>
                {library && (
                  <button className="icon-btn" onClick={startRenameLib} title="Rename library">
                    <span className="material-icons" style={{ fontSize: 18 }}>edit</span>
                  </button>
                )}
              </>
            )}
            {library?.finished_at && (
              <span className="reviewed-chip">
                <span className="material-icons">check_circle</span>
                Reviewed
              </span>
            )}
          </div>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {(likedCount > 0 || showLikedOnly) && (
              <button
                className={`btn ${showLikedOnly ? "btn-tonal" : "btn-outlined"}`}
                onClick={() => setShowLikedOnly((v) => !v)}
              >
                <span className="material-icons" style={{ fontSize: 18, color: showLikedOnly ? "var(--clr-error)" : undefined }}>favorite</span>
                {likedCount}
              </button>
            )}
            <button className="btn btn-outlined" onClick={() => setShowShare(true)}>
              <span className="material-icons">share</span>
              Share
            </button>
            <button className="btn btn-outlined" onClick={() => setShowSettings(true)} title="Library settings">
              <span className="material-icons">settings</span>
            </button>
            {hasImages && (
              <button className="btn btn-contained" onClick={() => fileInputRef.current?.click()}>
                <span className="material-icons">add_photo_alternate</span>
                Add photos
              </button>
            )}
          </div>
        </div>


        {data && (
          <p className="library-count-hint">
            {data.count} of {data.max_images_per_library ?? "\u221e"} photos
          </p>
        )}

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

        {hasImages && libId !== undefined && images.length > 0 && (
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

        {hasImages && showLikedOnly && images.length === 0 && (
          <div className="empty-state">
            <span className="material-icons">favorite_border</span>
            <p>No liked photos yet.</p>
          </div>
        )}

        {viewImage && (
          <Lightbox image={viewImage} onClose={() => setViewImage(null)} />
        )}
      </main>

      {showShare && <ShareDialog onClose={() => setShowShare(false)} />}
      {showSettings && library && (
        <LibrarySettingsOverlay
          library={library}
          onUpdate={() => {
            refetchLibrary();
            queryClient.invalidateQueries({ queryKey: ["libraries"] });
          }}
          onClose={() => setShowSettings(false)}
          updateLibrary={updateLibrary}
        />
      )}
    </>
  );
}

// ── Public view (read-only gallery) ──────────────────────────────────────────

function PublicLibraryView({ libraryUuid }: { libraryUuid: string }) {
  const queryClient = useQueryClient();
  const [viewImage, setViewImage] = useState<PublicImage | null>(null);
  const [showLikedOnly, setShowLikedOnly] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["public-library", libraryUuid],
    queryFn: () => publicApi.getLibrary(libraryUuid),
  });

  const likedCount = useMemo(
    () => data?.images.filter((img) => img.customer_state === "liked").length ?? 0,
    [data]
  );

  const isFinished = data?.library.finished_at != null;

  async function toggleLike(img: PublicImage) {
    const newState = img.customer_state === "liked" ? "none" : "liked";
    await publicApi.setCustomerState(libraryUuid, img.uuid, newState);
    queryClient.invalidateQueries({ queryKey: ["public-library", libraryUuid] });
  }

  async function handleFinish() {
    setFinishError(null);
    setFinishing(true);
    try {
      await publicApi.finishLibrary(libraryUuid);
      queryClient.invalidateQueries({ queryKey: ["public-library", libraryUuid] });
    } catch (err) {
      setFinishError(err instanceof Error ? err.message : "Failed to mark as complete");
    } finally {
      setFinishing(false);
    }
  }

  return (
    <>
      <header className="app-bar">
        <span className="app-bar__brand">Lumios</span>
        <div className="app-bar__title">
          {data?.library.name ?? "Library"}
        </div>
        {isFinished && (
          <span className="reviewed-chip">
            <span className="material-icons">check_circle</span>
            Reviewed
          </span>
        )}
        {(likedCount > 0 || showLikedOnly) && (
          <button
            className={`btn ${showLikedOnly ? "btn-tonal" : "btn-outlined"}`}
            onClick={() => setShowLikedOnly((v) => !v)}
          >
            <span className="material-icons" style={{ fontSize: 18, color: showLikedOnly ? "var(--clr-error)" : undefined }}>favorite</span>
            {likedCount}
          </button>
        )}
        {!isFinished && likedCount > 0 && (
          <button
            className="btn btn-contained"
            onClick={handleFinish}
            disabled={finishing}
            title="Mark your selection as complete"
          >
            <span className="material-icons">done_all</span>
            {finishing ? "Submitting…" : "Done selecting"}
          </button>
        )}
        <a className="btn btn-text" href="/login" target="_blank" rel="noopener noreferrer">
          <span className="material-icons">login</span>
          Login
        </a>
      </header>
      {finishError && (
        <div className="alert alert--error" style={{ margin: "0.5rem 1.5rem" }}>
          {finishError}
        </div>
      )}

      <main className="page-content">
        {isLoading && (
          <div className="photo-grid">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="skeleton photo-tile photo-tile--skeleton" />
            ))}
          </div>
        )}

        {isError && (
          <div className="empty-state">
            <span style={{ fontSize: 72, opacity: 0.50 }}>😔</span>
            <p style={{ fontSize: "1.5rem", fontWeight: 600 }}>Sorry, we haven't found your photos.</p>
          </div>
        )}

        {!isLoading && !isError && data && data.images.length === 0 && (
          <div className="empty-state">
            <span className="material-icons">photo_library</span>
            <p>No photos in this library yet.</p>
          </div>
        )}

        {!isLoading && !isError && data && data.images.length > 0 && (() => {
          const visibleImages = showLikedOnly
            ? data.images.filter((img) => img.customer_state === "liked")
            : data.images;
          return visibleImages.length > 0 ? (
            <div className="photo-grid">
              {visibleImages.map((img) => (
                <div key={img.uuid} className="photo-tile">
                  <img
                    src={img.thumb_url}
                    alt={img.filename}
                    className="photo-tile__img"
                    loading="lazy"
                    onClick={() => setViewImage(img)}
                    style={{ cursor: "pointer" }}
                  />
                  <button
                    className={`photo-tile__like ${img.customer_state === "liked" ? "photo-tile__like--active" : ""}`}
                    onClick={() => toggleLike(img)}
                    title={img.customer_state === "liked" ? "Remove like" : "Like this photo"}
                  >
                    <span className="material-icons">
                      {img.customer_state === "liked" ? "favorite" : "favorite_border"}
                    </span>
                  </button>
                  {img.download_url && (
                    <a
                      className="photo-tile__download"
                      href={img.download_url}
                      title="Download photo"
                    >
                      <span className="material-icons">download</span>
                    </a>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <span className="material-icons">favorite_border</span>
              <p>No liked photos yet.</p>
            </div>
          );
        })()}

        {viewImage && (
          <PublicLightbox image={viewImage} onClose={() => setViewImage(null)} />
        )}
      </main>
    </>
  );
}
