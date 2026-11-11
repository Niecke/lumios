import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  AUTO_HIDE_MS,
  bindBeforeUnload,
  createUploadStore,
  summarize,
  uploadStatusIcon,
  type QueuedUpload,
  type UploadDeps,
} from "../src/uploads/uploadStore.ts";

// api/auth.ts reads the storages at call time; stub them like tests/auth.test.ts.
const localData = new Map<string, string>();
(globalThis as any).localStorage = {
  getItem: (k: string) => localData.get(k) ?? null,
  setItem: (k: string, v: string) => void localData.set(k, v),
  removeItem: (k: string) => void localData.delete(k),
};
const sessionData = new Map<string, string>();
(globalThis as any).sessionStorage = {
  getItem: (k: string) => sessionData.get(k) ?? null,
  setItem: (k: string, v: string) => void sessionData.set(k, v),
  removeItem: (k: string) => void sessionData.delete(k),
};
const { authApi, onLogout, tokenStore } = await import("../src/api/auth.ts");

function deferred<T = void>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
const tick = () => new Promise((r) => setImmediate(r));
const img = (n: string) => new File(["x"], n, { type: "image/jpeg" });
const vid = (n: string) => new File(["x"], n, { type: "video/mp4" });

function setup(over: Partial<UploadDeps> = {}) {
  const calls: string[] = [];
  const done: number[] = [];
  let drained = 0;
  const deps: UploadDeps = {
    uploadImage: async (_id, f) => {
      calls.push(f.name);
    },
    uploadVideo: async () => ({ uuid: "u1", processing_status: "processing" }),
    pollVideoStatus: async () => {},
    onFileDone: (id) => done.push(id),
    onDrained: () => {
      drained++;
    },
    ...over,
  };
  return { store: createUploadStore(deps), calls, done, drained: () => drained };
}

const statuses = (items: QueuedUpload[]) => items.map((i) => i.status);

test("summarize counts and states", () => {
  const mk = (status: QueuedUpload["status"]) => ({ id: status, file: img("a"), status, libraryId: 1, libraryName: "L" });
  assert.equal(summarize([]).state, "idle");
  const mixed = summarize([mk("pending"), mk("uploading"), mk("processing"), mk("done"), mk("error")]);
  assert.deepEqual([mixed.active, mixed.failed, mixed.done, mixed.total], [3, 1, 1, 5]);
  assert.equal(mixed.state, "running");
  assert.equal(mixed.current?.status, "uploading");
  assert.equal(summarize([mk("done"), mk("error")]).state, "failed");
  assert.equal(summarize([mk("done")]).state, "done");
});

test("uploadStatusIcon", () => {
  assert.equal(uploadStatusIcon("pending"), "schedule");
  assert.equal(uploadStatusIcon("uploading"), "hourglass_top");
  assert.equal(uploadStatusIcon("processing"), "sync");
  assert.equal(uploadStatusIcon("error"), "error_outline");
  assert.equal(uploadStatusIcon("done"), "check_circle");
});

test("addFiles queues items and runs strictly in sequence across libraries", async () => {
  const gates = [deferred(), deferred()];
  const started: string[] = [];
  let n = 0;
  const { store } = setup({
    uploadImage: async (_id, f) => {
      started.push(f.name);
      await gates[n++].promise;
    },
  });
  store.addFiles(1, "One", [img("a.jpg")]);
  store.addFiles(2, "Two", [img("b.jpg")]);
  await tick();
  assert.deepEqual(started, ["a.jpg"]);
  const snap = store.getSnapshot();
  assert.deepEqual(statuses(snap), ["uploading", "pending"]);
  assert.deepEqual([snap[1].libraryId, snap[1].libraryName], [2, "Two"]);
  gates[0].resolve();
  await tick();
  assert.deepEqual(started, ["a.jpg", "b.jpg"]);
  gates[1].resolve();
  await tick();
  assert.deepEqual(statuses(store.getSnapshot()), ["done", "done"]);
});

test("video goes uploading -> processing -> done with progress", async () => {
  const up = deferred<{ uuid: string; processing_status: string }>();
  const poll = deferred();
  let progress!: (p: number) => void;
  const { store } = setup({
    uploadVideo: (_id, _f, onProgress) => {
      progress = onProgress;
      return up.promise;
    },
    pollVideoStatus: () => poll.promise,
  });
  store.addFiles(1, "L", [vid("v.mp4")]);
  await tick();
  progress(42);
  assert.equal(store.getSnapshot()[0].progress, 42);
  up.resolve({ uuid: "u", processing_status: "processing" });
  await tick();
  assert.deepEqual([store.getSnapshot()[0].status, store.getSnapshot()[0].progress], ["processing", 100]);
  poll.resolve();
  await tick();
  assert.equal(store.getSnapshot()[0].status, "done");
});

test("poll is skipped when the video is already ready", async () => {
  let polled = 0;
  const { store } = setup({
    uploadVideo: async () => ({ uuid: "u", processing_status: "ready" }),
    pollVideoStatus: async () => {
      polled++;
    },
  });
  store.addFiles(1, "L", [vid("v.mp4")]);
  await tick();
  assert.equal(polled, 0);
  assert.equal(store.getSnapshot()[0].status, "done");
});

test("errors are recorded, next file still runs, callbacks fire correctly", async () => {
  const boom = new Error("boom");
  const { store, done, drained } = setup({
    uploadImage: async (id, f) => {
      if (f.name === "bad.jpg") throw boom;
      if (f.name === "weird.jpg") throw "string";
    },
  });
  store.addFiles(7, "L", [img("bad.jpg"), img("weird.jpg"), img("ok.jpg")]);
  await tick();
  const [a, b, c] = store.getSnapshot();
  assert.deepEqual(a.error, { error: boom });
  assert.deepEqual(b.error, { key: "watermark.uploadFailed" });
  assert.equal(c.status, "done");
  assert.deepEqual(done, [7]);
  assert.equal(drained(), 1);
});

test("auto-hide after a clean drain, not with failures, cancelled by addFiles", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const ok = setup();
    ok.store.addFiles(1, "L", [img("a.jpg")]);
    await tick();
    assert.equal(summarize(ok.store.getSnapshot()).state, "done");
    mock.timers.tick(AUTO_HIDE_MS);
    assert.equal(ok.store.getSnapshot().length, 0);

    const bad = setup({ uploadImage: async () => { throw new Error("x"); } });
    bad.store.addFiles(1, "L", [img("a.jpg")]);
    await tick();
    mock.timers.tick(AUTO_HIDE_MS * 2);
    assert.equal(bad.store.getSnapshot().length, 1);

    const again = setup();
    again.store.addFiles(1, "L", [img("a.jpg")]);
    await tick();
    mock.timers.tick(AUTO_HIDE_MS - 1);
    const gate = deferred();
    const s2 = setup({ uploadImage: () => gate.promise });
    s2.store.addFiles(1, "L", [img("1.jpg")]);
    await tick();
    gate.resolve();
    await tick();
    mock.timers.tick(AUTO_HIDE_MS - 1);
    s2.store.addFiles(1, "L", [img("2.jpg")]);
    mock.timers.tick(10);
    await tick();
    assert.equal(s2.store.getSnapshot().length, 2);
  } finally {
    mock.timers.reset();
  }
});

test("clearFinished keeps active items and does not stop the running upload", async () => {
  const gate = deferred();
  let n = 0;
  const { store } = setup({
    uploadImage: async () => {
      if (n++ === 1) await gate.promise;
    },
  });
  store.addFiles(1, "L", [img("a.jpg"), img("b.jpg"), img("c.jpg")]);
  await tick();
  assert.deepEqual(statuses(store.getSnapshot()), ["done", "uploading", "pending"]);
  store.clearFinished();
  assert.deepEqual(statuses(store.getSnapshot()), ["uploading", "pending"]);
  gate.resolve();
  await tick();
  assert.deepEqual(statuses(store.getSnapshot()), ["done", "done"]);
});

test("getSnapshot is stable until something changes", async () => {
  const { store } = setup();
  const s0 = store.getSnapshot();
  assert.equal(store.getSnapshot(), s0);
  store.clearFinished();
  assert.equal(store.getSnapshot(), s0);
  let calls = 0;
  const unsub = store.subscribe(() => calls++);
  store.addFiles(1, "L", [img("a.jpg")]);
  await tick();
  assert.ok(calls > 0);
  assert.notEqual(store.getSnapshot(), s0);
  unsub();
});

test("bindBeforeUnload is registered only while uploads are active", async () => {
  const gate = deferred();
  const { store } = setup({ uploadImage: () => gate.promise });
  const target = new EventTarget();
  const added = mock.method(target, "addEventListener");
  const removed = mock.method(target, "removeEventListener");
  const cleanup = bindBeforeUnload(store, target);
  assert.equal(added.mock.callCount(), 0);
  store.addFiles(1, "L", [img("a.jpg")]);
  await tick();
  assert.equal(added.mock.callCount(), 1);
  const ev = new Event("beforeunload", { cancelable: true });
  target.dispatchEvent(ev);
  assert.equal(ev.defaultPrevented, true);
  gate.resolve();
  await tick();
  assert.equal(removed.mock.callCount(), 1);
  const ev2 = new Event("beforeunload", { cancelable: true });
  target.dispatchEvent(ev2);
  assert.equal(ev2.defaultPrevented, false);
  cleanup();
});

test("bindBeforeUnload cleanup removes the listener", async () => {
  const gate = deferred();
  const { store } = setup({ uploadImage: () => gate.promise });
  const target = new EventTarget();
  const cleanup = bindBeforeUnload(store, target);
  store.addFiles(1, "L", [img("a.jpg")]);
  await tick();
  cleanup();
  const ev = new Event("beforeunload", { cancelable: true });
  target.dispatchEvent(ev);
  assert.equal(ev.defaultPrevented, false);
  gate.resolve();
  await tick();
});

test("reset clears items and abandons running uploads", async () => {
  const gate = deferred();
  let started = 0;
  const { store, done } = setup({
    uploadImage: () => {
      started++;
      return gate.promise;
    },
  });
  store.addFiles(1, "L", [img("a.jpg"), img("b.jpg")]);
  await tick();
  store.reset();
  assert.equal(store.getSnapshot().length, 0);
  gate.resolve();
  await tick();
  assert.equal(store.getSnapshot().length, 0);
  assert.equal(started, 1);
  assert.equal(done.length, 0);
  gate.promise.then(() => {});
  store.addFiles(2, "M", [img("c.jpg")]);
  await tick();
  assert.equal(started, 2);
  assert.equal(store.getSnapshot()[0].status, "done");
});

test("a throwing onFileDone leaves the item done and the queue running", async () => {
  const { store, drained } = setup({
    onFileDone: () => {
      throw new Error("boom");
    },
  });
  const log = mock.method(console, "error", () => {});
  try {
    store.addFiles(1, "L", [img("a.jpg"), img("b.jpg")]);
    await tick();
  } finally {
    log.mock.restore();
  }
  assert.deepEqual(statuses(store.getSnapshot()), ["done", "done"]);
  assert.ok(store.getSnapshot().every((i) => i.error === undefined));
  assert.equal(drained(), 1);
});

test("a rejected token keeps the queue; logout clears it", async () => {
  const { store } = setup({
    uploadImage: async () => {
      throw new Error("Token expired");
    },
  });
  const off = onLogout(() => store.reset());
  try {
    store.addFiles(1, "L", [img("a.jpg")]);
    await tick();
    tokenStore.set("stale");
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ error: "Token expired" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      })) as typeof fetch;
    await assert.rejects(authApi.me());
    assert.equal(tokenStore.get(), null);
    const items = store.getSnapshot();
    assert.equal(items.length, 1);
    assert.equal(items[0].status, "error");
    assert.equal(items[0].error?.error?.message, "Token expired");
    await authApi.logout();
    assert.equal(store.getSnapshot().length, 0);
  } finally {
    off();
  }
});

test("images have no progress value, videos start at 0", async () => {
  const gate = deferred();
  const vgate = deferred<{ uuid: string; processing_status: string }>();
  const { store } = setup({
    uploadImage: () => gate.promise,
    uploadVideo: () => vgate.promise,
  });
  store.addFiles(1, "L", [img("a.jpg")]);
  await tick();
  assert.equal(store.getSnapshot()[0].status, "uploading");
  assert.equal(store.getSnapshot()[0].progress, undefined);
  gate.resolve();
  await tick();
  store.addFiles(1, "L", [vid("v.mp4")]);
  await tick();
  assert.equal(store.getSnapshot()[1].status, "uploading");
  assert.equal(store.getSnapshot()[1].progress, 0);
  vgate.resolve({ uuid: "u", processing_status: "ready" });
  await tick();
});

test("widget markup and root wiring", () => {
  const widget = readFileSync(new URL("../src/components/UploadWidget.tsx", import.meta.url), "utf8");
  assert.ok(widget.includes("aria-expanded"));
  assert.ok(widget.includes('aria-live="polite"'));
  const root = readFileSync(new URL("../src/routes/__root.tsx", import.meta.url), "utf8");
  assert.ok(root.includes("<UploadWidget"));
  assert.ok(widget.includes("upload-widget__progress--indeterminate"));
  const main = readFileSync(new URL("../src/main.tsx", import.meta.url), "utf8");
  assert.ok(main.includes("onLogout(() => uploadStore.reset())"));
  assert.ok(!main.includes("onSessionCleared"));
});
