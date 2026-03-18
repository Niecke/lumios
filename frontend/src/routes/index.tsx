// index.tsx — library dashboard (home page)
//
// Shows all of the photographer's libraries as cards in a responsive grid.
// A "New Library" button opens a dialog where the user enters a name.
// Inline rename and delete are available on each card.

import { createFileRoute, redirect, Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { authApi, type UserInfo } from "../api/auth";
import { librariesApi, type Library } from "../api/libraries";
import { AppBar } from "../components/AppBar";

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

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// ── Create dialog ─────────────────────────────────────────────────────────────

interface CreateDialogProps {
  onClose: () => void;
  onCreated: () => void;
}

function CreateDialog({ onClose, onCreated }: CreateDialogProps) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: (n: string) => librariesApi.create(n),
    onSuccess: () => {
      onCreated();
      onClose();
    },
    onError: (err: Error) => setError(err.message),
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
        <h2>New Library</h2>

        <form onSubmit={handleSubmit}>
          <div className="text-field">
            <label htmlFor="lib-name">Library name</label>
            <input
              id="lib-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Wedding – Smith & Jones"
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
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-contained"
              disabled={!name.trim() || create.isPending}
            >
              {create.isPending ? "Creating…" : "Create"}
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
            title="Save"
          >
            <span className="material-icons">check</span>
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={() => setRenaming(false)}
            title="Cancel"
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
            Created {formatDate(lib.created_at)}
            {lib.finished_at && (
              <span className="reviewed-chip">
                <span className="material-icons">check_circle</span>
                Reviewed
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
            title="Rename"
          >
            <span className="material-icons">edit</span>
          </button>
          <button
            className="icon-btn icon-btn--danger"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            title="Delete"
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
  const { user } = Route.useRouteContext() as { user: UserInfo };
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["libraries"],
    queryFn: librariesApi.list,
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["libraries"] });
  }

  const count = data?.count ?? 0;
  const maxLibraries = data?.max_libraries ?? user.max_libraries;
  const atLimit = maxLibraries !== null && count >= maxLibraries;

  return (
    <>
      <AppBar name={user.name} picture={user.picture} />

      <main className="page-content">
        <div className="page-header">
          <h1>Libraries</h1>
          <button
            className="btn btn-contained"
            onClick={() => setShowCreate(true)}
            disabled={atLimit}
            title={atLimit ? `Limit of ${maxLibraries} libraries reached` : undefined}
          >
            <span className="material-icons">add</span>
            New Library
          </button>
        </div>

        <p className="library-count-hint">
          {count} of {maxLibraries ?? "∞"} libraries in use
          {atLimit && " · limit reached"}
        </p>

        {isLoading && <SkeletonGrid />}

        {isError && (
          <div className="alert alert--error">
            Failed to load libraries. Please refresh the page.
          </div>
        )}

        {!isLoading && !isError && (
          <div className="card-deck">
            {data!.libraries.length === 0 ? (
              <div className="empty-state">
                <span className="material-icons">photo_library</span>
                <p>No libraries yet — create your first one above.</p>
              </div>
            ) : (
              data!.libraries.map((lib) => (
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
