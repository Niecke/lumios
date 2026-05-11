// public.ts — API client for unauthenticated public endpoints

export interface PublicImage {
  uuid: string;
  filename: string;
  width: number | null;
  height: number | null;
  duration_ms?: number;
  media_type: "photo" | "video";
  processing_status?: "uploading" | "processing" | "ready" | "failed";
  hevc_warning?: boolean;
  customer_state: string;
  preview_url: string | null;
  thumb_url: string | null;
  download_url: string | null;
}

export interface PublicLibraryPage {
  library: {
    uuid: string;
    name: string;
    finished_at: string | null;
    download_enabled: boolean;
    public_upload_enabled: boolean;
    video_uploads_enabled: boolean;
  };
  images: PublicImage[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const contentType = res.headers.get("content-type") ?? "";
  const data = contentType.includes("application/json") ? await res.json() : null;
  if (!res.ok) {
    throw new Error(
      (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`
    );
  }
  return data as T;
}

export const publicApi = {
  getLibrary: (uuid: string, page = 1, pageSize = 20): Promise<PublicLibraryPage> =>
    apiFetch<PublicLibraryPage>(
      `/api/v1/public/libraries/${uuid}?page=${page}&page_size=${pageSize}`
    ),

  setCustomerState: (
    libraryUuid: string,
    imageUuid: string,
    customerState: string
  ): Promise<{ uuid: string; customer_state: string }> =>
    apiFetch<{ uuid: string; customer_state: string }>(
      `/api/v1/public/libraries/${libraryUuid}/images/${imageUuid}/state`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_state: customerState }),
      }
    ),

  setVideoCustomerState: (
    libraryUuid: string,
    videoUuid: string,
    customerState: string
  ): Promise<{ uuid: string; customer_state: string }> =>
    apiFetch<{ uuid: string; customer_state: string }>(
      `/api/v1/public/libraries/${libraryUuid}/videos/${videoUuid}/state`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_state: customerState }),
      }
    ),

  finishLibrary: (libraryUuid: string): Promise<{ uuid: string; finished_at: string }> =>
    apiFetch<{ uuid: string; finished_at: string }>(
      `/api/v1/public/libraries/${libraryUuid}/finish`,
      { method: "POST", headers: { "Content-Type": "application/json" } }
    ),

  uploadImage: async (libraryUuid: string, file: File): Promise<{ uuid: string }> => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<{ uuid: string }>(
      `/api/v1/public/libraries/${libraryUuid}/images`,
      { method: "POST", body: form }
    );
  },

  initVideoUpload: (
    libraryUuid: string,
    filename: string,
    contentType: string,
    size: number
  ): Promise<{ uuid: string; upload_url: string }> =>
    apiFetch<{ uuid: string; upload_url: string }>(
      `/api/v1/public/libraries/${libraryUuid}/videos/init`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename, content_type: contentType, size }),
      }
    ),

  finalizeVideoUpload: (
    libraryUuid: string,
    videoUuid: string
  ): Promise<{ uuid: string; processing_status: string }> =>
    apiFetch<{ uuid: string; processing_status: string }>(
      `/api/v1/public/libraries/${libraryUuid}/videos/${videoUuid}/finalize`,
      { method: "POST" }
    ),

  getVideoStatus: (
    libraryUuid: string,
    videoUuid: string
  ): Promise<{ uuid: string; processing_status: string; hevc_warning?: boolean }> =>
    apiFetch<{ uuid: string; processing_status: string; hevc_warning?: boolean }>(
      `/api/v1/public/libraries/${libraryUuid}/videos/${videoUuid}`
    ),
};
