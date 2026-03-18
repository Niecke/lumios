// public.ts — API client for unauthenticated public endpoints

export interface PublicImage {
  uuid: string;
  filename: string;
  width: number | null;
  height: number | null;
  customer_state: string;
  preview_url: string;
  thumb_url: string;
}

export interface PublicLibrary {
  library: {
    uuid: string;
    name: string;
    finished_at: string | null;
  };
  images: PublicImage[];
  count: number;
}

export const publicApi = {
  getLibrary: async (uuid: string): Promise<PublicLibrary> => {
    const res = await fetch(`/api/v1/public/libraries/${uuid}`);
    const contentType = res.headers.get("content-type") ?? "";
    const data = contentType.includes("application/json") ? await res.json() : null;
    if (!res.ok) {
      throw new Error(
        (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`
      );
    }
    return data as PublicLibrary;
  },

  setCustomerState: async (
    libraryUuid: string,
    imageUuid: string,
    customerState: string
  ): Promise<{ uuid: string; customer_state: string }> => {
    const res = await fetch(
      `/api/v1/public/libraries/${libraryUuid}/images/${imageUuid}/state`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_state: customerState }),
      }
    );
    const contentType = res.headers.get("content-type") ?? "";
    const data = contentType.includes("application/json") ? await res.json() : null;
    if (!res.ok) {
      throw new Error(
        (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`
      );
    }
    return data as { uuid: string; customer_state: string };
  },

  finishLibrary: async (
    libraryUuid: string
  ): Promise<{ uuid: string; finished_at: string }> => {
    const res = await fetch(
      `/api/v1/public/libraries/${libraryUuid}/finish`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }
    );
    const contentType = res.headers.get("content-type") ?? "";
    const data = contentType.includes("application/json") ? await res.json() : null;
    if (!res.ok) {
      throw new Error(
        (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`
      );
    }
    return data as { uuid: string; finished_at: string };
  },
};
