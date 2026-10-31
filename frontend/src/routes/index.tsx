// index.tsx — library dashboard (home page)
//
// Shows all of the photographer's libraries as cards in a responsive grid.
// A "New Library" button opens a dialog where the user enters a name.
// Inline rename and delete are available on each card.

import { createFileRoute, redirect, Link } from "@tanstack/react-router";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { getApiErrorMessage } from "../api/errors";
import { formatDate } from "../i18n";
import { authApi, type UserInfo } from "../api/auth";
import { librariesApi, type Library } from "../api/libraries";
import { AppBar } from "../components/AppBar";
import { InfiniteScrollSentinel } from "../components/InfiniteScrollSentinel";

export const Route = createFileRoute("/")({
  beforeLoad: async () => {
    try {
      const user = await authApi.me();
      return { user };
    } catch {
      throw redirect({ to: "/login" });
    }
  },
  component: LibrariesPage,
});

// ── Create dialog ─────────────────────────────────────────────────────────────

interface CreateDialogProps {
  onClose: () => void;
  onCreated: () => void;
}

function CreateDialog({ onClose, onCreated }: CreateDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: (n: string) => librariesApi.create(n),
    onSuccess: () => {
      onCreated();
      onClose();
    },
    onError: (err: Error) => setError(getApiErrorMessage(err, t)),
  });

  function handleSubmit(e: { preventDefault(): void }) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setError(null);
    create.mutate(trimmed);
  }

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2>{t("libraries.newTitle")}</h2>

        <form onSubmit={handleSubmit}>
          <div className="text-field">
            <label htmlFor="lib-name">{t("libraries.name")}</label>
            <input
              id="lib-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("libraries.namePlaceholder")}
              maxLength={255}
              autoFocus
              disabled={create.isPending}
            />
            {error && <span className="field-error">{error}</span>}
          </div>

          <div className="dialog__actions" style={{ marginTop: "0.5rem" }}>
            <button
              type="button"
              className="btn btn-text"
              onClick={onClose}
              disabled={create.isPending}
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              className="btn btn-contained"
              disabled={!name.trim() || create.isPending}
            >
              {create.isPending ? t("common.creating") : t("common.create")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Library card ──────────────────────────────────────────────────────────────

interface LibraryCardProps {
  lib: Library;
  onRenamed: () => void;
  onDeleted: () => void;
}

function LibraryCard({ lib, onRenamed, onDeleted }: LibraryCardProps) {
  const { t, i18n } = useTranslation();
  const [renaming, setRenaming] = useState(false);
  const [editName, setEditName] = useState(lib.name);

  const rename = useMutation({
    mutationFn: (name: string) => librariesApi.rename(lib.id, name),
    onSuccess: () => {
      setRenaming(false);
      onRenamed();
    },
  });

  const remove = useMutation({
    mutationFn: () => librariesApi.delete(lib.id),
    onSuccess: onDeleted,
  });

  function startRename() {
    setEditName(lib.name);
    setRenaming(true);
  }

  function submitRename(e: { preventDefault(): void }) {
    e.preventDefault();
    const trimmed = editName.trim();
    if (!trimmed) return;
    rename.mutate(trimmed);
  }

  return (
    <div className="library-card">
      <Link to="/library/$libraryUuid" params={{ libraryUuid: lib.uuid }} className="library-card__media">
        <span className="material-icons">photo_library</span>
      </Link>

      {renaming ? (
        <form className="library-card__rename" onSubmit={submitRename}>
          <input
            type="text"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            maxLength={255}
            autoFocus
            disabled={rename.isPending}
          />
          <button
            type="submit"
            className="icon-btn"
            disabled={!editName.trim() || rename.isPending}
            title={t("common.save")}
          >
            <span className="material-icons">check</span>
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={() => setRenaming(false)}
            title={t("common.cancel")}
          >
            <span className="material-icons">close</span>
          </button>
        </form>
      ) : (
        <Link to="/library/$libraryUuid" params={{ libraryUuid: lib.uuid }} className="library-card__body">
          <div className="library-card__name" title={lib.name}>
            {lib.name}
          </div>
          <div className="library-card__meta">
            {t("libraries.created", { date: formatDate(lib.created_at, i18n.language) })}
            {lib.finished_at && (
              <span className="reviewed-chip">
                <span className="material-icons">check_circle</span>
                {t("libraries.reviewed")}
              </span>
            )}
          </div>
        </Link>
      )}

      {!renaming && (
        <div className="library-card__actions">
          <button
            className="icon-btn"
            onClick={startRename}
            title={t("libraries.rename")}
          >
            <span className="material-icons">edit</span>
          </button>
          <button
            className="icon-btn icon-btn--danger"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            title={t("common.delete")}
          >
            <span className="material-icons">delete</span>
          </button>
        </div>
      )}
    </div>
  );
}

// ── Skeleton loader ───────────────────────────────────────────────────────────

function SkeletonGrid() {
  return (
    <div className="card-deck">
      {[0, 1, 2].map((i) => (
        <div key={i} className="skeleton skeleton-card" />
      ))}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function LibrariesPage() {
  const { t } = useTranslation();
  const { user } = Route.useRouteContext() as { user: UserInfo };
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const {
    data,
    isLoading,
    isError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["libraries"],
    queryFn: ({ pageParam = 1 }) => librariesApi.list(pageParam as number),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.page + 1 : undefined),
  });

  function invalidate() {
    queryClient.resetQueries({ queryKey: ["libraries"] });
  }

  const allLibraries = data?.pages.flatMap((p) => p.libraries) ?? [];
  const count = data?.pages[0]?.total ?? 0;
  const maxLibraries = data?.pages[0]?.max_libraries ?? user.max_libraries;
  const atLimit = maxLibraries !== null && count >= maxLibraries;

  return (
    <>
      <AppBar name={user.name} picture={user.picture} />

      <main className="page-content">
        <div className="page-header">
          <h1>{t("libraries.title")}</h1>
          <button
            className="btn btn-contained"
            onClick={() => setShowCreate(true)}
            disabled={atLimit}
            title={atLimit ? t("libraries.limitTitle", { max: maxLibraries }) : undefined}
          >
            <span className="material-icons">add</span>
            {t("libraries.new")}
          </button>
        </div>

        <p className="library-count-hint">
          {t("libraries.inUse", { used: count, max: maxLibraries ?? "∞" })}
          {atLimit && ` · ${t("libraries.limitReached")}`}
        </p>

        {isLoading && <SkeletonGrid />}

        {isError && (
          <div className="alert alert--error">
            {t("libraries.loadFailed")}
          </div>
        )}

        {!isLoading && !isError && (
          <div className="card-deck">
            {allLibraries.length === 0 ? (
              <div className="empty-state">
                <span className="material-icons">photo_library</span>
                <p>{t("libraries.empty")}</p>
              </div>
            ) : (
              allLibraries.map((lib) => (
                <LibraryCard
                  key={lib.id}
                  lib={lib}
                  onRenamed={invalidate}
                  onDeleted={invalidate}
                />
              ))
            )}
          </div>
        )}

        <InfiniteScrollSentinel
          hasNextPage={hasNextPage}
          isFetchingNextPage={isFetchingNextPage}
          fetchNextPage={fetchNextPage}
        />
      </main>

      {showCreate && (
        <CreateDialog
          onClose={() => setShowCreate(false)}
          onCreated={invalidate}
        />
      )}
    </>
  );
}
