// public.ts — API client for unauthenticated public endpoints

export interface PublicImage {
  uuid: string;
  filename: string;
  width: number | null;
  height: number | null;
  preview_url: string;
  thumb_url: string;
}

export interface PublicLibrary {
  library: {
    uuid: string;
    name: string;
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
};
