// main.tsx — app entry point
//
// Sets up the two global providers:
//   - QueryClientProvider: TanStack Query for server state (API calls, caching;
//                          global defaults live in queryDefaults.ts)
//   - RouterProvider:      TanStack Router for file-based routing (src/routes/)
//
// Routes are auto-generated into routeTree.gen.ts by the Vite plugin.
// Add new pages by creating files under src/routes/.

import "./index.css";
import "./i18n";
import { initErrorReporting } from "./errorReporting";
initErrorReporting();
import { initSentry } from "./sentry";
initSentry();
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";
import { routeTree } from "./routeTree.gen";
import { imagesApi, type ImagePage } from "./api/images";
import { uploadVideo, pollVideoStatus, videosApi } from "./api/videos";
import { appendUploaded } from "./uploads/appendMedia";
import { createUploadStore } from "./uploads/uploadStore";
import { onLogout } from "./api/auth";
import { UploadProvider } from "./uploads/UploadContext";
import { QUERY_DEFAULT_OPTIONS } from "./queryDefaults";

const queryClient = new QueryClient({ defaultOptions: QUERY_DEFAULT_OPTIONS });
// App-level upload queue: lives outside React so uploads survive page changes.
const uploadStore = createUploadStore({
  uploadImage: (id, file) => imagesApi.upload(id, file),
  uploadVideo,
  pollVideoStatus,
  fetchVideo: (id, uuid) => videosApi.get(id, uuid),
  // Append the finished file locally; no refetch, so the visible grid stays put.
  onFileDone: (id, item) => {
    if (item) {
      queryClient.setQueryData<InfiniteData<ImagePage, number>>(["images", id], (d) =>
        appendUploaded(d, item)
      );
    } else {
      queryClient.invalidateQueries({ queryKey: ["images", id], refetchType: "none" });
    }
  },
  onDrained: () => {
    queryClient.invalidateQueries({ queryKey: ["libraries"] });
  },
});
// Explicit logout: drop the previous user's uploads and stop their queue. A rejected
// token keeps the queue, so failed items stay visible after the user logs in again.
onLogout(() => uploadStore.reset());
const router = createRouter({ routeTree });

// Required for TanStack Router's TypeScript type inference
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <UploadProvider store={uploadStore}>
        <RouterProvider router={router} />
      </UploadProvider>
    </QueryClientProvider>
  </StrictMode>
);
