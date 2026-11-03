import { createContext, useContext, useEffect, useSyncExternalStore, type ReactNode } from "react";
import { bindBeforeUnload, type QueuedUpload, type UploadStore } from "./uploadStore.ts";

const UploadContext = createContext<UploadStore | null>(null);

export function UploadProvider({ store, children }: { store: UploadStore; children: ReactNode }) {
  useEffect(() => bindBeforeUnload(store, window), [store]);
  return <UploadContext.Provider value={store}>{children}</UploadContext.Provider>;
}

export function useUploadStore(): UploadStore {
  const store = useContext(UploadContext);
  if (!store) throw new Error("useUploadStore must be used inside UploadProvider");
  return store;
}

export function useUploads(): QueuedUpload[] {
  const store = useUploadStore();
  return useSyncExternalStore(store.subscribe, store.getSnapshot);
}
