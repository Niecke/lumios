// App-level upload queue. Framework-free so it survives page changes and can be
// tested with the plain node test runner; React reads it via useSyncExternalStore.
import type { DisplayError } from "../api/errors.ts";

export type UploadStatus = "pending" | "uploading" | "processing" | "done" | "error";

export interface UploadItem {
  id: string;
  file: File;
  status: UploadStatus;
  progress?: number;
  error?: DisplayError;
}

export interface QueuedUpload extends UploadItem {
  libraryId: number;
  libraryName: string;
}

const VIDEO_TYPES = new Set(["video/mp4", "video/quicktime", "video/webm", "video/x-m4v"]);
const VIDEO_EXTS = new Set(["mp4", "mov", "webm", "m4v"]);

export function isVideoFile(f: File): boolean {
  if (VIDEO_TYPES.has(f.type)) return true;
  const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
  return VIDEO_EXTS.has(ext);
}

export function uploadStatusIcon(status: UploadStatus): string {
  switch (status) {
    case "uploading":
      return "hourglass_top";
    case "processing":
      return "sync";
    case "error":
      return "error_outline";
    case "done":
      return "check_circle";
    default:
      return "schedule";
  }
}

export const AUTO_HIDE_MS = 4000;

interface UploadSummary {
  active: number;
  failed: number;
  done: number;
  total: number;
  current?: QueuedUpload;
  state: "idle" | "running" | "done" | "failed";
}

export function summarize(items: readonly QueuedUpload[]): UploadSummary {
  let active = 0;
  let failed = 0;
  let done = 0;
  for (const i of items) {
    if (i.status === "error") failed++;
    else if (i.status === "done") done++;
    else active++;
  }
  const current = items.find((i) => i.status === "uploading");
  const state = active > 0 ? "running" : failed > 0 ? "failed" : items.length > 0 ? "done" : "idle";
  return { active, failed, done, total: items.length, current, state };
}

export interface UploadDeps {
  uploadImage(libraryId: number, file: File): Promise<unknown>;
  uploadVideo(
    libraryId: number,
    file: File,
    onProgress: (pct: number) => void
  ): Promise<{ uuid: string; processing_status: string }>;
  pollVideoStatus(libraryId: number, uuid: string): Promise<unknown>;
  onFileDone(libraryId: number): void;
  onDrained?(): void;
}

export interface UploadStore {
  subscribe(listener: () => void): () => void;
  getSnapshot(): QueuedUpload[];
  addFiles(libraryId: number, libraryName: string, files: File[]): void;
  clearFinished(): void;
  /** Drops every item and abandons running work (logout). */
  reset(): void;
}

export function createUploadStore(deps: UploadDeps): UploadStore {
  let items: QueuedUpload[] = [];
  const listeners = new Set<() => void>();
  let draining = false;
  let generation = 0;
  let hideTimer: ReturnType<typeof setTimeout> | undefined;

  function set(next: QueuedUpload[]) {
    items = next;
    listeners.forEach((l) => l());
  }

  function patch(id: string, change: Partial<QueuedUpload>, gen = generation) {
    if (gen !== generation) return;
    set(items.map((i) => (i.id === id ? { ...i, ...change } : i)));
  }

  function cancelHide() {
    if (hideTimer !== undefined) {
      clearTimeout(hideTimer);
      hideTimer = undefined;
    }
  }

  async function runItem(item: QueuedUpload) {
    const gen = generation;
    patch(item.id, { status: "uploading", progress: 0 }, gen);
    try {
      if (isVideoFile(item.file)) {
        const status = await deps.uploadVideo(item.libraryId, item.file, (pct) =>
          patch(item.id, { progress: pct }, gen)
        );
        patch(item.id, { status: "processing", progress: 100 }, gen);
        if (status.processing_status !== "ready" && status.processing_status !== "failed") {
          await deps.pollVideoStatus(item.libraryId, status.uuid);
        }
      } else {
        await deps.uploadImage(item.libraryId, item.file);
      }
      if (gen !== generation) return;
      patch(item.id, { status: "done" }, gen);
      deps.onFileDone(item.libraryId);
    } catch (err) {
      const error: DisplayError =
        err instanceof Error ? { error: err } : { key: "watermark.uploadFailed" };
      patch(item.id, { status: "error", error }, gen);
    }
  }

  async function drain() {
    if (draining) return;
    draining = true;
    const gen = generation;
    try {
      for (;;) {
        if (gen !== generation) return;
        const next = items.find((i) => i.status === "pending");
        if (!next) break;
        await runItem(next);
      }
    } finally {
      if (gen === generation) draining = false;
    }
    deps.onDrained?.();
    if (summarize(items).state === "done") {
      cancelHide();
      hideTimer = setTimeout(() => {
        hideTimer = undefined;
        clearFinished();
      }, AUTO_HIDE_MS);
    }
  }

  function clearFinished() {
    const kept = items.filter((i) => i.status !== "done" && i.status !== "error");
    if (kept.length !== items.length) set(kept);
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: () => items,
    addFiles(libraryId, libraryName, files) {
      if (!files.length) return;
      cancelHide();
      const added: QueuedUpload[] = files.map((file) => ({
        id: crypto.randomUUID(),
        file,
        status: "pending",
        libraryId,
        libraryName,
      }));
      set([...items, ...added]);
      void drain();
    },
    clearFinished,
    reset() {
      generation++;
      draining = false;
      cancelHide();
      if (items.length) set([]);
    },
  };
}

type ListenerTarget = Pick<EventTarget, "addEventListener" | "removeEventListener">;

function warnBeforeUnload(e: Event) {
  e.preventDefault();
  (e as BeforeUnloadEvent).returnValue = "";
}

/** Registers a beforeunload warning while uploads are active. Returns the cleanup. */
export function bindBeforeUnload(store: UploadStore, target: ListenerTarget): () => void {
  let bound = false;
  function sync() {
    const active = summarize(store.getSnapshot()).active > 0;
    if (active && !bound) {
      target.addEventListener("beforeunload", warnBeforeUnload);
      bound = true;
    } else if (!active && bound) {
      target.removeEventListener("beforeunload", warnBeforeUnload);
      bound = false;
    }
  }
  sync();
  const unsubscribe = store.subscribe(sync);
  return () => {
    unsubscribe();
    if (bound) {
      target.removeEventListener("beforeunload", warnBeforeUnload);
      bound = false;
    }
  };
}
