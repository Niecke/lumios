// support.tsx — support ticket page at /support
//
// Logged-in users can create support tickets and view their existing ones,
// including any admin comments/replies.

import { createFileRoute, redirect, Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { authApi, type UserInfo } from "../api/auth";
import { supportApi, type SupportTicket } from "../api/support";
import { AppBar } from "../components/AppBar";

export const Route = createFileRoute("/support")({
  beforeLoad: async () => {
    try {
      const user = await authApi.me();
      return { user };
    } catch {
      throw redirect({ to: "/login" });
    }
  },
  component: SupportPage,
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ── New ticket form ───────────────────────────────────────────────────────────

function NewTicketForm({ onCreated }: { onCreated: () => void }) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [open, setOpen] = useState(false);

  const create = useMutation({
    mutationFn: () => supportApi.create(subject.trim(), body.trim()),
    onSuccess: () => {
      setSubject("");
      setBody("");
      setOpen(false);
      onCreated();
    },
  });

  if (!open) {
    return (
      <button className="btn btn-contained" onClick={() => setOpen(true)}>
        <span className="material-icons">add</span>
        New ticket
      </button>
    );
  }

  return (
    <div className="account-card" style={{ marginBottom: "1.5rem" }}>
      <div style={{ padding: "1.25rem 1.5rem" }}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 500, marginBottom: "1rem" }}>
          New support ticket
        </h2>
        {create.isError && (
          <div className="alert alert--error" style={{ marginBottom: "1rem" }}>
            {(create.error as Error).message}
          </div>
        )}
        <div className="text-field" style={{ marginBottom: "1rem" }}>
          <label htmlFor="support-subject">Subject</label>
          <input
            id="support-subject"
            type="text"
            maxLength={255}
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Brief description of your issue"
          />
        </div>
        <div className="text-field" style={{ marginBottom: "1.25rem" }}>
          <label htmlFor="support-body">Message</label>
          <textarea
            id="support-body"
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Describe your issue in detail…"
          />
        </div>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <button
            className="btn btn-contained"
            disabled={create.isPending || !subject.trim() || !body.trim()}
            onClick={() => create.mutate()}
          >
            {create.isPending ? "Submitting…" : "Submit ticket"}
          </button>
          <button
            className="btn btn-outlined"
            onClick={() => setOpen(false)}
            disabled={create.isPending}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Ticket card ───────────────────────────────────────────────────────────────

function TicketCard({ ticket }: { ticket: SupportTicket }) {
  const [expanded, setExpanded] = useState(false);
  const hasReplies = ticket.comments.length > 0;

  return (
    <div className="account-card" style={{ marginBottom: "1rem" }}>
      <div
        style={{
          padding: "1rem 1.5rem",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "1rem",
          cursor: "pointer",
        }}
        onClick={() => setExpanded((v) => !v)}
      >
        <div>
          <span
            className={`chip ${ticket.status === "closed" ? "chip--muted" : ""}`}
            style={{ marginRight: "0.5rem" }}
          >
            {ticket.status}
          </span>
          <strong>{ticket.subject}</strong>
        </div>
        <div
          style={{
            whiteSpace: "nowrap",
            fontSize: "0.85rem",
            color: "var(--clr-on-surface-var)",
            display: "flex",
            alignItems: "center",
            gap: "0.25rem",
            flexShrink: 0,
          }}
        >
          {formatDate(ticket.created_at)}
          {hasReplies && (
            <span>
              · {ticket.comments.length}{" "}
              {ticket.comments.length === 1 ? "reply" : "replies"}
            </span>
          )}
          <span className="material-icons" style={{ fontSize: "1.1rem" }}>
            {expanded ? "expand_less" : "expand_more"}
          </span>
        </div>
      </div>

      {expanded && (
        <div
          style={{
            padding: "0 1.5rem 1.25rem",
            borderTop: "1px solid var(--clr-outline)",
          }}
        >
          <p style={{ whiteSpace: "pre-wrap", margin: "1rem 0" }}>
            {ticket.body}
          </p>

          {ticket.comments.length > 0 && (
            <>
              <p
                style={{
                  fontSize: "0.8rem",
                  fontWeight: 500,
                  color: "var(--clr-on-surface-var)",
                  marginBottom: "0.5rem",
                }}
              >
                Replies
              </p>
              {ticket.comments.map((c) => (
                <div
                  key={c.id}
                  style={{
                    background: "var(--clr-background)",
                    borderRadius: "var(--radius-sm)",
                    padding: "0.75rem 1rem",
                    marginBottom: "0.5rem",
                  }}
                >
                  <div
                    style={{
                      fontSize: "0.8rem",
                      color: "var(--clr-on-surface-var)",
                      marginBottom: "0.25rem",
                    }}
                  >
                    {formatDate(c.created_at)}
                  </div>
                  <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{c.body}</p>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Support page ──────────────────────────────────────────────────────────────

function SupportPage() {
  const { user } = Route.useRouteContext() as { user: UserInfo };
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["support-tickets"],
    queryFn: supportApi.list,
  });

  const tickets = data?.tickets ?? [];
  const openCount = tickets.filter((t) => t.status === "open").length;

  return (
    <>
      <AppBar name={user.name} picture={user.picture} />

      <main className="page-content">
        <div className="page-header">
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <Link to="/" className="btn btn-text" style={{ padding: "0 0.5rem" }}>
              <span className="material-icons" style={{ fontSize: 20 }}>arrow_back</span>
            </Link>
            <h1>Support</h1>
          </div>
        </div>

        <div className="account-layout">
          <div style={{ width: "100%" }}>
            <NewTicketForm
              onCreated={() =>
                queryClient.invalidateQueries({ queryKey: ["support-tickets"] })
              }
            />

            {isLoading && <p style={{ color: "var(--clr-on-surface-var)" }}>Loading tickets…</p>}
            {isError && (
              <p className="alert alert--error">Failed to load tickets.</p>
            )}

            {!isLoading && !isError && tickets.length === 0 && (
              <p style={{ color: "var(--clr-on-surface-var)", marginTop: "1rem" }}>
                No tickets yet. Use the button above to get in touch.
              </p>
            )}

            {tickets.length > 0 && (
              <>
                <p
                  style={{
                    color: "var(--clr-on-surface-var)",
                    fontSize: "0.9rem",
                    margin: "0.75rem 0 1rem",
                  }}
                >
                  {openCount} open · {tickets.length - openCount} closed
                </p>
                {tickets.map((t) => (
                  <TicketCard key={t.id} ticket={t} />
                ))}
              </>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
