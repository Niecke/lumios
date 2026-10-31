// AppBar.tsx — sticky top navigation shared across all authenticated pages

import type { TFunction } from "i18next";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { authApi } from "../api/auth";
import { formatTimeAgo } from "../i18n";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { notificationsApi, type Notification } from "../api/notifications";

interface AppBarProps {
  name?: string;
  picture?: string;
}

function notificationMessage(n: Notification, t: TFunction): string {
  if (n.type === "library_marked") {
    return t("notifications.libraryMarked", { name: n.library_name ?? t("notifications.unknown") });
  }
  if (n.type === "library_viewed") {
    return t("notifications.libraryViewed", { name: n.library_name ?? t("notifications.unknown") });
  }
  if (n.type === "ticket_comment_added") {
    return t("notifications.ticketComment", {
      subject: n.ticket_subject ?? t("notifications.supportTicket"),
    });
  }
  return t("notifications.generic");
}

export function AppBar({ name, picture }: AppBarProps) {
  const { t } = useTranslation();
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
    setShowDropdown(false);
    if ((n.type === "library_marked" || n.type === "library_viewed") && n.related_object) {
      navigate({ to: "/library/$libraryUuid", params: { libraryUuid: n.related_object } });
    } else if (n.type === "ticket_comment_added") {
      navigate({ to: "/support" });
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
          title={t("notifications.title")}
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
              <span>{t("notifications.title")}</span>
            </div>
            {(!data || data.notifications.length === 0) ? (
              <div className="notification-dropdown__empty">
                {t("notifications.empty")}
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
                      {n.type === "library_marked" ? "check_circle" : n.type === "library_viewed" ? "visibility" : n.type === "ticket_comment_added" ? "chat" : "info"}
                    </span>
                    <div className="notification-item__body">
                      <span className="notification-item__text">
                        {notificationMessage(n, t)}
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

      <LanguageSwitcher />

      <Link to="/support" className="btn btn-text">
        <span className="material-icons">help_outline</span>
        <span className="app-bar__label">{t("nav.support")}</span>
      </Link>

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
        <span className="app-bar__label">{name ?? t("nav.account")}</span>
      </Link>

      <button
        className="btn btn-outlined"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
        title={t("nav.logout")}
      >
        <span className="material-icons">logout</span>
        <span className="app-bar__label">{logout.isPending ? "…" : t("nav.logout")}</span>
      </button>
    </header>
  );
}
