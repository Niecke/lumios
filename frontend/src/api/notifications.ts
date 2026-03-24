// notifications.ts — API client for photographer notifications

import { tokenStore } from "./auth";

export interface Notification {
  id: number;
  type: string;
  created_at: string;
  seen_at: string | null;
  related_object: string | null;
  library_name?: string;
  ticket_subject?: string;
}

export interface NotificationList {
  notifications: Notification[];
  unseen_count: number;
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

export const notificationsApi = {
  list: () => apiFetch<NotificationList>("/api/v1/notifications"),

  markSeen: (id: number) =>
    apiFetch<Notification>(`/api/v1/notifications/${id}/seen`, {
      method: "PATCH",
    }),
};
