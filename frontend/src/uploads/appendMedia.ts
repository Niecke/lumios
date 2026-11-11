// Pure helpers to add a finished upload to the cached infinite image list without
// refetching it. Framework-free so the node test runner can import it.
import type { Image, ImagePage } from "../api/images.ts";

interface MediaPages {
  pages: ImagePage[];
  pageParams: unknown[];
}

const key = (i: Pick<Image, "media_type" | "id">) => `${i.media_type}:${i.id}`;

/** Drops repeated items (same media_type + id), keeping the first. */
export function dedupeMedia(items: Image[]): Image[] {
  const seen = new Set<string>();
  return items.filter((i) => {
    const k = key(i);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

/**
 * Appends `item` to the last loaded page. When more pages remain unloaded the item is
 * not placed (it would leave a gap); only `total` is raised. Never mutates the input.
 */
export function appendUploaded<T extends MediaPages>(data: T | undefined, item: Image): T | undefined {
  if (!data || data.pages.length === 0) return data;
  if (data.pages.some((p) => p.images.some((i) => key(i) === key(item)))) return data;
  const last = data.pages.length - 1;
  const hasMore = data.pages[last].has_more;
  const pages = data.pages.map((p, idx) => ({
    ...p,
    total: p.total + 1,
    images: idx === last && !hasMore ? [...p.images, item] : p.images,
  }));
  return { ...data, pages };
}
