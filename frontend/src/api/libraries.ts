// libraries.ts — all communication with the backend libraries API

import { tokenStore } from "./auth";

export interface Library {
  id: number;
  uuid: string;
  name: string;
  created_at: string;
  archived_at: string | null;
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

  delete: (id: number) =>
    apiFetch<void>(`/api/v1/libraries/${id}`, { method: "DELETE" }),
};
