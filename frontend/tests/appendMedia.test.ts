import { test } from "node:test";
import assert from "node:assert/strict";
import { appendUploaded, dedupeMedia } from "../src/uploads/appendMedia.ts";
import type { Image, ImagePage } from "../src/api/images.ts";

const mk = (id: number, media_type: Image["media_type"] = "photo"): Image => ({
  id,
  uuid: `${media_type}-${id}`,
  filename: `${id}`,
  content_type: "image/jpeg",
  size: 1,
  width: null,
  height: null,
  media_type,
  customer_state: "none",
  is_external: false,
  created_at: "2026-01-01T00:00:00",
  original_url: null,
  preview_url: null,
  thumb_url: null,
});
const page = (ids: number[], has_more: boolean, total = ids.length): ImagePage => ({
  images: ids.map((i) => mk(i)),
  total,
  page: 1,
  page_size: 20,
  has_more,
  max_images_per_library: null,
});
const data = (pages: ImagePage[]) => ({ pages, pageParams: pages.map((_, i) => i + 1) });
const ids = (d: ReturnType<typeof data> | undefined) => d!.pages.flatMap((p) => p.images.map((i) => `${i.media_type}${i.id}`));

test("appends to the last page when no page is left", () => {
  const out = appendUploaded(data([page([3, 2], false)]), mk(9));
  assert.deepEqual(ids(out), ["photo3", "photo2", "photo9"]);
  assert.equal(out!.pages[0].total, 3);
});

test("only raises total when more pages remain", () => {
  const out = appendUploaded(data([page([3, 2], true, 5)]), mk(9));
  assert.deepEqual(ids(out), ["photo3", "photo2"]);
  assert.equal(out!.pages[0].total, 6);
});

test("an existing item is not added twice", () => {
  const d = data([page([3, 2], false)]);
  assert.equal(appendUploaded(d, mk(2)), d);
});

test("undefined data and empty list", () => {
  assert.equal(appendUploaded(undefined, mk(1)), undefined);
  assert.deepEqual(ids(appendUploaded(data([page([], false)]), mk(1))), ["photo1"]);
});

test("photo and video with the same id are distinct", () => {
  const out = appendUploaded(data([page([1], false)]), mk(1, "video"));
  assert.deepEqual(ids(out), ["photo1", "video1"]);
});

test("input is not mutated", () => {
  const d = data([page([1], false)]);
  const snapshot = structuredClone(d);
  appendUploaded(d, mk(2));
  assert.deepEqual(d, snapshot);
});

test("25 appends keep existing items in place", () => {
  let d: ReturnType<typeof data> | undefined = data([page([100, 99, 98], false)]);
  for (let n = 1; n <= 25; n++) {
    d = appendUploaded(d, mk(n));
    assert.deepEqual(ids(d).slice(0, 3), ["photo100", "photo99", "photo98"]);
  }
  assert.equal(ids(d).length, 28);
  assert.equal(ids(d)[27], "photo25");
});

test("dedupeMedia keeps the first of repeated items", () => {
  assert.deepEqual(dedupeMedia([mk(1), mk(2), mk(1), mk(1, "video")]).map((i) => `${i.media_type}${i.id}`), ["photo1", "photo2", "video1"]);
});
