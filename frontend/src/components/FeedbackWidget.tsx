import { useState, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { tokenStore } from "../api/auth";
import { feedbackApi } from "../api/feedback";

const EMOJI_MAP: Record<number, string> = {
  1: "😞",
  2: "😕",
  3: "😐",
  4: "🙂",
  5: "😄",
};

export function FeedbackWidget() {
  const isAuthenticated = tokenStore.get() !== null;

  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const [body, setBody] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const submit = useMutation({
    mutationFn: () => feedbackApi.submit(rating!, body.trim() || null),
    onSuccess: () => {
      setOpen(false);
      setRating(null);
      setBody("");
      setSubmitted(true);
    },
  });

  useEffect(() => {
    if (!submitted) return;
    const timer = setTimeout(() => setSubmitted(false), 3000);
    return () => clearTimeout(timer);
  }, [submitted]);

  if (!isAuthenticated) return null;

  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) setOpen(false);
  }

  return (
    <>
      <button
        className="feedback-fab"
        onClick={() => setOpen(true)}
        title="Give feedback"
        aria-label="Give feedback"
      >
        <span className="material-icons">feedback</span>
      </button>

      {open && (
        <div className="feedback-overlay" onClick={handleBackdropClick}>
          <div className="feedback-card" role="dialog" aria-modal="true" aria-label="Feedback form">
            <h2 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 500 }}>
              Share Feedback
            </h2>

            <div>
              <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem", color: "var(--clr-on-surface-var)" }}>
                How are you finding Lumios?
              </p>
              <div className="feedback-rating">
                {([1, 2, 3, 4, 5] as const).map((n) => (
                  <button
                    key={n}
                    className={`feedback-emoji${rating === n ? " feedback-emoji--selected" : ""}`}
                    onClick={() => setRating(n)}
                    aria-label={`Rating ${n}`}
                    aria-pressed={rating === n}
                  >
                    {EMOJI_MAP[n]}
                  </button>
                ))}
              </div>
            </div>

            <div className="text-field">
              <label htmlFor="feedback-body">
                Tell us more{" "}
                <span style={{ color: "var(--clr-on-surface-var)", fontWeight: 400 }}>
                  (optional)
                </span>
              </label>
              <textarea
                id="feedback-body"
                rows={4}
                maxLength={2000}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="What could be better? What do you love?"
              />
              <div style={{ fontSize: "0.75rem", color: "var(--clr-on-surface-var)", textAlign: "right", marginTop: "0.25rem" }}>
                {body.length}/2000
              </div>
            </div>

            {submit.isError && (
              <div className="alert alert--error">
                {(submit.error as Error).message}
              </div>
            )}

            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
              <button
                className="btn btn-outlined"
                onClick={() => setOpen(false)}
                disabled={submit.isPending}
              >
                Cancel
              </button>
              <button
                className="btn btn-contained"
                disabled={!rating || submit.isPending}
                onClick={() => submit.mutate()}
              >
                {submit.isPending ? "Sending…" : "Submit"}
              </button>
            </div>
          </div>
        </div>
      )}

      {submitted && (
        <div className="feedback-toast" role="status">
          Thanks for your feedback!
        </div>
      )}
    </>
  );
}
