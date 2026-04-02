// public.ts — API client for unauthenticated public endpoints

export interface PublicImage {
  uuid: string;
  filename: string;
  width: number | null;
  height: number | null;
  customer_state: string;
  preview_url: string;
  thumb_url: string;
  download_url: string | null;
}

export interface PublicLibraryPage {
  library: {
    uuid: string;
    name: string;
    finished_at: string | null;
    download_enabled: boolean;
  };
  images: PublicImage[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export const publicApi = {
  getLibrary: async (uuid: string, page = 1, pageSize = 20): Promise<PublicLibraryPage> => {
    const res = await fetch(
      `/api/v1/public/libraries/${uuid}?page=${page}&page_size=${pageSize}`
    );
    const contentType = res.headers.get("content-type") ?? "";
    const data = contentType.includes("application/json") ? await res.json() : null;
    if (!res.ok) {
      throw new Error(
        (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`
      );
    }
    return data as PublicLibraryPage;
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
