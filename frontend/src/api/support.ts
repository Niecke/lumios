// support.ts — API client for support tickets

import { tokenStore } from "./auth";

export interface SupportComment {
  id: number;
  body: string;
  created_at: string;
}

export interface SupportTicket {
  id: number;
  subject: string;
  body: string;
  status: "open" | "closed";
  created_at: string;
  updated_at: string;
  comments: SupportComment[];
}

export interface SupportTicketList {
  tickets: SupportTicket[];
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

export const supportApi = {
  list: () => apiFetch<SupportTicketList>("/api/v1/support/tickets"),

  get: (id: number) => apiFetch<SupportTicket>(`/api/v1/support/tickets/${id}`),

  create: (subject: string, body: string) =>
    apiFetch<SupportTicket>("/api/v1/support/tickets", {
      method: "POST",
      body: JSON.stringify({ subject, body }),
    }),
};
