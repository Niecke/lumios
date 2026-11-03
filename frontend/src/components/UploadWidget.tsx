import { useState } from "react";
import { useTranslation } from "react-i18next";
import { tokenStore } from "../api/auth";
import { displayErrorMessage } from "../api/errors";
import { summarize, uploadStatusIcon } from "../uploads/uploadStore";
import { useUploads, useUploadStore } from "../uploads/UploadContext";

export function UploadWidget() {
  const { t } = useTranslation();
  const store = useUploadStore();
  const items = useUploads();
  const [open, setOpen] = useState(false);

  const { active, failed, done, state, current } = summarize(items);
  const visible = tokenStore.get() !== null && state !== "idle";
  // Always mounted, so screen readers announce changes from the first one on.
  const announcement = !visible
    ? ""
    : [
        state === "running" ? t("uploads.pending", { count: active }) : "",
        state === "done" ? t("uploads.allDone") : "",
        failed > 0 ? t("uploads.failed", { count: failed }) : "",
      ]
        .filter(Boolean)
        .join(", ");
  const liveRegion = (
    <span className="upload-widget__live" role="status" aria-live="polite">
      {announcement}
    </span>
  );
  if (!visible) return liveRegion;

  const icon =
    state === "running"
      ? "cloud_upload"
      : state === "failed"
        ? "error_outline"
        : "check_circle";

  return (
    <>
      {liveRegion}
      <section className="upload-widget" aria-label={t("uploads.widgetLabel")}>
        <button
          type="button"
          className="upload-widget__toggle"
          aria-expanded={open}
          aria-controls="upload-widget-list"
          title={t("uploads.toggle")}
          onClick={() => setOpen((o) => !o)}
        >
          <span className="material-icons" aria-hidden="true">
            {icon}
          </span>
          <span className="upload-widget__summary">
            {state === "running" && t("uploads.pending", { count: active })}
            {state === "done" && t("uploads.allDone")}
            {failed > 0 && (
              <span className="upload-widget__failed">
                {state === "running" ? " · " : ""}
                {t("uploads.failed", { count: failed })}
              </span>
            )}
          </span>
          <span className="material-icons" aria-hidden="true">
            {open ? "expand_more" : "expand_less"}
          </span>
        </button>
        {state === "running" && current?.status === "uploading" && (
          <div
            className="upload-widget__progress"
            role="progressbar"
            aria-valuenow={current.progress ?? 0}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t("uploads.currentProgress", {
              name: current.file.name,
            })}
          >
            <div
              className="upload-widget__progress-bar"
              style={{ width: `${current.progress ?? 0}%` }}
            />
          </div>
        )}
        {open && (
          <ul id="upload-widget-list" className="upload-widget__list">
            {items.map((item) => (
              <li
                key={item.id}
                className={`upload-item upload-item--${item.status}`}
              >
                <span
                  className="material-icons upload-item__icon"
                  aria-hidden="true"
                >
                  {uploadStatusIcon(item.status)}
                </span>
                <span className="upload-item__name">
                  {item.file.name}{" "}
                  <span className="text-muted">{item.libraryName}</span>
                </span>
                {item.status === "uploading" && item.progress !== undefined && (
                  <span className="upload-item__progress">
                    {item.progress}%
                  </span>
                )}
                {item.status === "processing" && (
                  <span className="upload-item__progress">
                    {t("library.processing")}
                  </span>
                )}
                {item.status === "error" && item.error && (
                  <span className="upload-item__error">
                    {displayErrorMessage(item.error, t)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {done + failed > 0 && (
          <div className="upload-widget__footer">
            <button
              type="button"
              className="btn btn-text"
              onClick={() => store.clearFinished()}
            >
              {t("uploads.clearFinished")}
            </button>
          </div>
        )}
      </section>
    </>
  );
}
