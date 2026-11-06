// Global TanStack Query defaults. Data is fresh for 30 s: no refetch on window
// focus / remount / reconnect within that window. Mutations still invalidate
// or reset their queries, which refetches regardless of staleTime.
export const QUERY_STALE_TIME_MS = 30_000;
export const QUERY_DEFAULT_OPTIONS = {
  queries: { staleTime: QUERY_STALE_TIME_MS },
} as const;
