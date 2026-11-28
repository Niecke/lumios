import { test } from "node:test";
import assert from "node:assert/strict";
import { setItemState } from "../src/public/customerState.ts";
import type { PublicImage, PublicLibraryPage } from "../src/api/public.ts";

const mk = (uuid: string, media_type: PublicImage["media_type"] = "photo"): PublicImage => ({
  uuid,
  filename: uuid,
  width: null,
  height: null,
  media_type,
  customer_state: "none",
  preview_url: null,
  thumb_url: null,
  download_url: null,
});
const page = (n: number, images: PublicImage[], has_more: boolean): PublicLibraryPage => ({
  library: {
    uuid: "lib",
    name: "Gallery",
    finished_at: null,
    download_enabled: false,
    public_upload_enabled: false,
    video_uploads_enabled: false,
  },
  images,
  total: 60,
  page: n,
  page_size: 20,
  has_more,
});
// 3 pages x 20 photos: p<page>-<index>
const threePages = () => {
  const pages = [1, 2, 3].map((n) =>
    page(n, Array.from({ length: 20 }, (_, i) => mk(`p${n}-${i}`)), n < 3)
  );
  return { pages, pageParams: [1, 2, 3] };
};
const state = (d: ReturnType<typeof threePages> | undefined, uuid: string, type = "photo") =>
  d!.pages.flatMap((p) => p.images).find((i) => i.uuid === uuid && i.media_type === type)!.customer_state;

test("likes an item on page 3 and leaves the other pages untouched", () => {
  const d = threePages();
  const out = setItemState(d, "photo", "p3-7", "liked")!;
  assert.equal(state(out, "p3-7"), "liked");
  assert.equal(out.pages[0], d.pages[0]);
  assert.equal(out.pages[1], d.pages[1]);
  assert.notEqual(out.pages[2], d.pages[2]);
  assert.equal(out.pageParams, d.pageParams);
  out.pages[2].images.forEach((img, i) => {
    if (i !== 7) assert.equal(img, d.pages[2].images[i]);
  });
  assert.equal(out.pages.flatMap((p) => p.images).filter((i) => i.customer_state === "liked").length, 1);
});

test("input is not mutated", () => {
  const d = threePages();
  const before = structuredClone(d);
  setItemState(d, "photo", "p3-7", "liked");
  assert.deepEqual(d, before);
});

test("photo and video with the same uuid are distinct", () => {
  const d = threePages();
  d.pages[2].images.push(mk("p3-7", "video"));
  const out = setItemState(d, "video", "p3-7", "liked");
  assert.equal(state(out, "p3-7", "video"), "liked");
  assert.equal(state(out, "p3-7", "photo"), "none");
});

test("unknown item and undefined data are returned unchanged", () => {
  const d = threePages();
  assert.equal(setItemState(d, "photo", "missing", "liked"), d);
  assert.equal(setItemState(d, "video", "p1-0", "liked"), d);
  assert.equal(setItemState(undefined, "photo", "p1-0", "liked"), undefined);
});

test("rollback restores only the failed item", () => {
  let d = threePages();
  d = setItemState(d, "photo", "p3-7", "liked")!; // optimistic like that will fail
  d = setItemState(d, "photo", "p1-2", "liked")!; // another like in the meantime
  d = setItemState(d, "photo", "p3-7", "none")!; // rollback of the failed one
  assert.equal(state(d, "p3-7"), "none");
  assert.equal(state(d, "p1-2"), "liked");
});
