// feedback.ts — API client for the feedback widget

import { tokenStore } from "./auth";

export interface FeedbackResponse {
  id: number;
  rating: number;
  body: string | null;
  created_at: string;
  updated_at: string;
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

export const feedbackApi = {
  submit: (rating: number, body: string | null) =>
    apiFetch<FeedbackResponse>("/api/v1/feedback", {
      method: "POST",
      body: JSON.stringify({ rating, body: body || null }),
    }),
};
