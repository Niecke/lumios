// videos.ts — API client for authenticated video upload (Architecture B)

import { tokenStore } from "./auth";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = tokenStore.get();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(path, { ...init, headers });

  const contentType = res.headers.get("content-type") ?? "";
  const data = contentType.includes("application/json") ? await res.json() : null;

  if (!res.ok) {
    throw new Error(
      (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`
    );
  }
  return data as T;
}

export interface VideoInitResponse {
  uuid: string;
  upload_url: string;
}

export interface VideoStatusResponse {
  uuid: string;
  processing_status: "uploading" | "processing" | "ready" | "failed";
  hevc_warning?: boolean;
}

/** Upload a video using the two-step presigned PUT flow with XHR progress events. */
export async function uploadVideo(
  libraryId: number,
  file: File,
  onProgress?: (pct: number) => void
): Promise<VideoStatusResponse> {
  // Step 1: init — create DB row, get presigned PUT URL
  const { uuid, upload_url } = await apiFetch<VideoInitResponse>(
    `/api/v1/libraries/${libraryId}/videos/init`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type,
        size: file.size,
      }),
    }
  );

  // Step 2: PUT directly to storage with progress events
  await xhrPut(upload_url, file, file.type, onProgress);

  // Step 3: finalize — verify upload + enqueue processing
  const finalized = await apiFetch<VideoStatusResponse>(
    `/api/v1/libraries/${libraryId}/videos/${uuid}/finalize`,
    { method: "POST" }
  );

  return finalized;
}

/** Poll until processing_status is "ready" or "failed" (max ~2 min). */
export async function pollVideoStatus(
  libraryId: number,
  uuid: string
): Promise<VideoStatusResponse> {
  const maxAttempts = 60;
  for (let i = 0; i < maxAttempts; i++) {
    await delay(2000);
    const status = await apiFetch<VideoStatusResponse>(
      `/api/v1/libraries/${libraryId}/videos/${uuid}`
    );
    if (status.processing_status === "ready" || status.processing_status === "failed") {
      return status;
    }
  }
  throw new Error("Video processing timed out");
}

export const videosApi = {
  delete: (libraryId: number, videoId: number) =>
    apiFetch<void>(`/api/v1/libraries/${libraryId}/videos/${videoId}`, {
      method: "DELETE",
    }),
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function xhrPut(
  url: string,
  file: File,
  contentType: string,
  onProgress?: (pct: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType);

    if (onProgress) {
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      });
    }

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed (${xhr.status})`));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Upload network error")));
    xhr.addEventListener("abort", () => reject(new Error("Upload aborted")));

    xhr.send(file);
  });
}
