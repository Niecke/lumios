// AppBar.tsx — sticky top navigation shared across all authenticated pages

import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useRef, useEffect } from "react";
import { authApi } from "../api/auth";
import { notificationsApi, type Notification } from "../api/notifications";

interface AppBarProps {
  name?: string;
  picture?: string;
}

function formatTimeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function notificationMessage(n: Notification): string {
  if (n.type === "library_marked") {
    return `Library "${n.library_name ?? "Unknown"}" was marked as finished by the customer`;
  }
  return "New notification";
}

export function AppBar({ name, picture }: AppBarProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const logout = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => navigate({ to: "/login" }),
  });

  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: notificationsApi.list,
    refetchInterval: 30000,
  });

  const markSeen = useMutation({
    mutationFn: notificationsApi.markSeen,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const unseenCount = data?.unseen_count ?? 0;

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setShowDropdown(false);
      }
    }
    if (showDropdown) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [showDropdown]);

  function handleNotificationClick(n: Notification) {
    if (!n.seen_at) {
      markSeen.mutate(n.id);
    }
    if (n.related_object) {
      setShowDropdown(false);
      navigate({ to: "/library/$libraryUuid", params: { libraryUuid: n.related_object } });
    }
  }

  return (
    <header className="app-bar">
      <Link to="/" className="app-bar__brand">
        Lumios
      </Link>

      <div className="notification-wrapper" ref={dropdownRef}>
        <button
          className="icon-btn notification-bell"
          onClick={() => setShowDropdown((v) => !v)}
          title="Notifications"
        >
          <span className="material-icons">
            {unseenCount > 0 ? "notifications_active" : "notifications_none"}
          </span>
          {unseenCount > 0 && (
            <span className="notification-badge">{unseenCount > 9 ? "9+" : unseenCount}</span>
          )}
        </button>

        {showDropdown && (
          <div className="notification-dropdown">
            <div className="notification-dropdown__header">
              <span>Notifications</span>
            </div>
            {(!data || data.notifications.length === 0) ? (
              <div className="notification-dropdown__empty">
                No notifications yet
              </div>
            ) : (
              <div className="notification-dropdown__list">
                {data.notifications.map((n) => (
                  <button
                    key={n.id}
                    className={`notification-item ${!n.seen_at ? "notification-item--unseen" : ""}`}
                    onClick={() => handleNotificationClick(n)}
                  >
                    <span className="material-icons notification-item__icon">
                      {n.type === "library_marked" ? "check_circle" : "info"}
                    </span>
                    <div className="notification-item__body">
                      <span className="notification-item__text">
                        {notificationMessage(n)}
                      </span>
                      <span className="notification-item__time">
                        {formatTimeAgo(n.created_at)}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <Link to="/account" className="btn btn-text app-bar__account-btn">
        {picture ? (
          <img
            className="app-bar__avatar"
            src={picture}
            alt=""
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="material-icons">account_circle</span>
        )}
        {name ?? "Account"}
      </Link>

      <button
        className="btn btn-outlined"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
      >
        {logout.isPending ? "…" : "Logout"}
      </button>
    </header>
  );
}
