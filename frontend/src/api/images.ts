// images.ts — all communication with the backend images API

import { tokenStore } from "./auth";

export interface Image {
  id: number;
  uuid: string;
  filename: string;
  content_type: string;
  size: number;
  width: number | null;
  height: number | null;
  customer_state: string;
  is_external: boolean;
  created_at: string;
  original_url: string | null;
  preview_url: string | null;
  thumb_url: string | null;
}

export interface ImagePage {
  images: Image[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  max_images_per_library: number | null;
}

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

export const imagesApi = {
  list: (libraryId: number, page = 1, pageSize = 20) =>
    apiFetch<ImagePage>(
      `/api/v1/libraries/${libraryId}/images?page=${page}&page_size=${pageSize}`
    ),

  upload: (libraryId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<Image>(`/api/v1/libraries/${libraryId}/images`, {
      method: "POST",
      body: form,
    });
  },

  delete: (libraryId: number, imageId: number) =>
    apiFetch<void>(`/api/v1/libraries/${libraryId}/images/${imageId}`, {
      method: "DELETE",
    }),
};
