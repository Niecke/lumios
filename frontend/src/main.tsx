// main.tsx — app entry point
//
// Sets up the two global providers:
//   - QueryClientProvider: TanStack Query for server state (API calls, caching)
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
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { routeTree } from "./routeTree.gen";
import { imagesApi } from "./api/images";
import { uploadVideo, pollVideoStatus } from "./api/videos";
import { createUploadStore } from "./uploads/uploadStore";
import { UploadProvider } from "./uploads/UploadContext";

const queryClient = new QueryClient();
// App-level upload queue: lives outside React so uploads survive page changes.
const uploadStore = createUploadStore({
  uploadImage: (id, file) => imagesApi.upload(id, file),
  uploadVideo,
  pollVideoStatus,
  onFileDone: (id) => {
    queryClient.resetQueries({ queryKey: ["images", id] });
  },
  onDrained: () => {
    queryClient.invalidateQueries({ queryKey: ["libraries"] });
  },
});
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
