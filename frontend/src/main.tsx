// main.tsx — app entry point
//
// Sets up the two global providers:
//   - QueryClientProvider: TanStack Query for server state (API calls, caching)
//   - RouterProvider:      TanStack Router for file-based routing (src/routes/)
//
// Routes are auto-generated into routeTree.gen.ts by the Vite plugin.
// Add new pages by creating files under src/routes/.

import "./index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { routeTree } from "./routeTree.gen";

const queryClient = new QueryClient();
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
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>
);
