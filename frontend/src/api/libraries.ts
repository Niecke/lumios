// libraries.ts — all communication with the backend libraries API

import { tokenStore } from "./auth";

export interface Library {
  id: number;
  uuid: string;
  name: string;
  created_at: string;
  archived_at: string | null;
  finished_at: string | null;
  use_original_as_preview: boolean;
  download_enabled: boolean;
  watermark_gcs_key: string | null;
  watermark_scale: number | null;
  watermark_position: string | null;
}

export interface LibraryList {
  libraries: Library[];
  count: number;
  max_libraries: number | null;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = tokenStore.get();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
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

export const librariesApi = {
  list: () => apiFetch<LibraryList>("/api/v1/libraries"),

  getByUuid: (uuid: string) =>
    apiFetch<Library>(`/api/v1/libraries/uuid/${uuid}`),

  create: (name: string) =>
    apiFetch<Library>("/api/v1/libraries", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  rename: (id: number, name: string) =>
    apiFetch<Library>(`/api/v1/libraries/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  update: (id: number, patch: {
    name?: string;
    use_original_as_preview?: boolean;
    download_enabled?: boolean;
    watermark_scale?: number;
    watermark_position?: string;
  }) =>
    apiFetch<Library>(`/api/v1/libraries/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  delete: (id: number) =>
    apiFetch<void>(`/api/v1/libraries/${id}`, { method: "DELETE" }),

  uploadWatermark: (id: number, file: File): Promise<Library> => {
    const token = tokenStore.get();
    const formData = new FormData();
    formData.append("file", file);
    return fetch(`/api/v1/libraries/${id}/watermark`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    }).then(async (res) => {
      const data = res.headers.get("content-type")?.includes("application/json")
        ? await res.json()
        : null;
      if (!res.ok) {
        throw new Error((data as { error?: string } | null)?.error ?? `Request failed (${res.status})`);
      }
      return data as Library;
    });
  },

  deleteWatermark: (id: number) =>
    apiFetch<Library>(`/api/v1/libraries/${id}/watermark`, { method: "DELETE" }),

  fetchWatermarkPreview: (id: number, scale: number, position: string): Promise<string> => {
    const token = tokenStore.get();
    const params = new URLSearchParams({ scale: String(scale), position });
    return fetch(`/api/v1/libraries/${id}/watermark/preview?${params}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then(async (res) => {
      if (!res.ok) {
        const data = res.headers.get("content-type")?.includes("application/json")
          ? await res.json()
          : null;
        throw new Error((data as { error?: string } | null)?.error ?? `Request failed (${res.status})`);
      }
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    });
  },
};
