// Pure helper to set one item's customer_state in the cached public gallery without
// refetching it. Framework-free so the node test runner can import it.
import type { PublicImage, PublicLibraryPage } from "../api/public.ts";

interface PublicPages {
  pages: PublicLibraryPage[];
  pageParams: unknown[];
}

/**
 * Sets `customer_state` of the item matching `mediaType` + `uuid`. Only the page holding
 * it and the item itself are new objects; the rest keep their references. Returns `data`
 * unchanged when it is undefined or the item is not loaded. Never mutates the input.
 */
export function setItemState<T extends PublicPages>(
  data: T | undefined,
  mediaType: PublicImage["media_type"],
  uuid: string,
  state: string
): T | undefined {
  if (!data) return data;
  const match = (i: PublicImage) => i.media_type === mediaType && i.uuid === uuid;
  const pageIdx = data.pages.findIndex((p) => p.images.some(match));
  if (pageIdx === -1) return data;
  const pages = data.pages.map((p, idx) =>
    idx === pageIdx
      ? { ...p, images: p.images.map((i) => (match(i) ? { ...i, customer_state: state } : i)) }
      : p
  );
  return { ...data, pages };
}
