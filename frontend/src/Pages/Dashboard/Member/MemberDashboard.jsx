import React, { useState, useEffect, useRef } from "react";
import api from "../../../api/axiosInstance"; // ⚠️ verify this matches this file's actual depth
import {
  House,
  Building2,
  Bell,
  ChevronDown,
  Wallet,
  Landmark,
  CreditCard,
  Settings,
  User,
  ShieldCheck,
  LifeBuoy,
  LogOut,
  X,
  Menu,
} from "lucide-react";

import "./MemberDashboard.css";
import HomePage from "./pages/HomePage";
import ProfileWizard from "./pages/ProfileWizard";
import MySangha from "./pages/MySangha";
import MyPayments from "./pages/MyPayments";
import SanghaSavings from "./pages/SanghaSavings";
import Loans from "./pages/Loans";
import SettingsPage from "./pages/SettingsPage";
import HelpSupport from "./pages/HelpSupport";
import Notifications from "./pages/Notifications";
import AccountStatusModal from "./Modal/AccountStatusModal";
import EmploymentProfileModal from "./Modal/EmploymentProfileModal";

// Settings moved into the profile dropdown
const NAV_ITEMS = [
  { key: "home", label: "Home", icon: House },
  { key: "payments", label: "My Payments", icon: Wallet },
  { key: "savings", label: "Sangha Savings", icon: Landmark },
  { key: "loans", label: "Loans", icon: CreditCard },
  { key: "notifications", label: "Notifications", icon: Bell },
];

export default function MemberDashboard() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [page, setPage] = useState("home");
  const [sanghasName, setSanghasName] = useState("");
  const [showAccountStatus, setShowAccountStatus] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [showEmploymentProfileModal, setShowEmploymentProfileModal] =
    useState(false);

  const menuRef = useRef(null);
  const user = JSON.parse(localStorage.getItem("user") || "{}");

  // ================= NOTIFICATIONS =================
  // Lifted here (rather than living inside Notifications.jsx) because the
  // unread count badge in the top nav needs this data too.

  const [notifications, setNotifications] = useState([]);
  const [notifLoading, setNotifLoading] = useState(true);
  const [notifError, setNotifError] = useState("");
  const [markingId, setMarkingId] = useState(null);

  const unreadNotifications = notifications.filter((n) => !n.isRead).length;

  const fetchNotifications = async () => {
    try {
      setNotifLoading(true);
      setNotifError("");
      const res = await api.get(`/me/notifications`);
      setNotifications(res.data);
    } catch (error) {
      console.error("Error fetching notifications:", error);
      setNotifError(
        error.response?.data?.detail || "Failed to load notifications.",
      );
    } finally {
      setNotifLoading(false);
    }
  };

  // Fetch logged-in member's Sangha(s)
  const fetchSanghas = async () => {
    try {
      const response = await api.get("/member/my-sangha");
      const data = response.data;
      setSanghasName(data?.[0]?.name || "");
    } catch (err) {
      console.error("Failed to fetch Sanghas:", err);
    }
  };

  useEffect(() => {
    fetchNotifications();
    fetchSanghas();

    let active = true;

    const checkEmploymentProfile = async () => {
      try {
        const response = await api.get("/me/employment-profile");

        if (active && response.data?.needs_completion) {
          setShowEmploymentProfileModal(true);
        }
      } catch (error) {
        console.error(
          "Unable to check employment profile:",
          error.response?.data?.detail || error.message,
        );
      }
    };

    checkEmploymentProfile();

    return () => {
      active = false;
    };
  }, []);

  const handleMarkRead = async (notification) => {
    if (notification.isRead) return;

    try {
      setMarkingId(notification.id);
      await api.patch(`/me/notifications/${notification.id}/read`, {});
      setNotifications((prev) =>
        prev.map((n) =>
          n.id === notification.id ? { ...n, isRead: true } : n,
        ),
      );
    } catch (error) {
      console.error("Error marking notification as read:", error);
    } finally {
      setMarkingId(null);
    }
  };

  // Close profile dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  // Logout
  const handleLogout = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    window.location.href = "/auth";
  };

  // User initials
  const initials = (user.fullname || "Member")
    .split(" ")
    .map((word) => word[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  // Navigation
  const handleNavigation = (selectedPage) => {
    setPage(selectedPage);
    setMenuOpen(false);
    setMobileMenuOpen(false);
  };

  const openAccountStatus = () => {
    setMenuOpen(false);
    setShowAccountStatus(true);
  };

  const PAGES = {
    home: () => <HomePage user={user} onNavigate={handleNavigation} />,
    payments: () => <MyPayments />,
    savings: () => <SanghaSavings />,
    loans: () => <Loans />,
    settings: () => <SettingsPage />,
    help: () => <HelpSupport />,
    sangha: () => <MySangha />,
    notifications: () => (
      <Notifications
        notifications={notifications}
        loading={notifLoading}
        error={notifError}
        markingId={markingId}
        onRetry={fetchNotifications}
        onMarkRead={handleMarkRead}
      />
    ),
    profile: () => (
      <section className="md-profile-page">
        <ProfileWizard onBack={() => setPage("home")} />
      </section>
    ),
  };

  const renderPage = PAGES[page] ?? PAGES.home;

  return (
    <div className="md-shell">
      <header className="md-topbar">
        <div className="md-brand" onClick={() => handleNavigation("home")}>
          <div className="md-brand__mark">RS</div>
          <div className="md-brand__text">
            <span className="md-brand__title">R S Sangha</span>
            <span className="md-brand__subtitle">Member Portal</span>
          </div>
        </div>

        <nav className="md-navigation">
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              className={`md-navigation__item ${page === key ? "md-navigation__item--active" : ""}`}
              onClick={() => handleNavigation(key)}
            >
              {key === "notifications" ? (
                <span className="md-navigation__notification-icon">
                  <Icon size={18} strokeWidth={2} />
                  {unreadNotifications > 0 && (
                    <span className="md-notification-badge">
                      {unreadNotifications > 9 ? "9+" : unreadNotifications}
                    </span>
                  )}
                </span>
              ) : (
                <Icon size={18} strokeWidth={2} />
              )}
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="md-profile" ref={menuRef}>
          <button
            type="button"
            className="md-profile__trigger"
            aria-label={
              mobileMenuOpen ? "Close profile menu" : "Open profile menu"
            }
            aria-expanded={menuOpen}
            onClick={() => {
              setMenuOpen((value) => !value);
              setMobileMenuOpen((value) => !value);
            }}
          >
            <span className="md-avatar">{initials}</span>

            <span className="md-profile__name">
              {user.fullname || "Member"}
            </span>

            <ChevronDown
              size={16}
              className="md-profile__caret md-desktop-caret"
            />

            <span className="md-mobile-menu-icon">
              {menuOpen ? <X size={21} /> : <Menu size={21} />}
              <span>Menu</span>
            </span>
          </button>

          {menuOpen && (
            <div className="md-profile__menu">
              <div className="md-profile__menu-header">
                <div className="md-profile__menu-name">
                  {user.fullname || "Member"}
                </div>
                <div className="md-profile__menu-email">{user.email || ""}</div>
              </div>

              <button
                type="button"
                className="md-profile__menu-item"
                onClick={() => handleNavigation("profile")}
              >
                <User size={16} />
                My Profile
              </button>

              <button
                type="button"
                className="md-profile__menu-item"
                onClick={() => handleNavigation("settings")}
              >
                <Settings size={16} />
                Settings
              </button>

              <button
                type="button"
                className="md-profile__menu-item"
                onClick={openAccountStatus}
              >
                <ShieldCheck size={16} />
                Account Status
              </button>

              <button
                type="button"
                className="md-profile__menu-item"
                onClick={() => handleNavigation("help")}
              >
                <LifeBuoy size={16} />
                Help &amp; Support
              </button>

              <div className="md-profile__menu-divider" />

              <button
                type="button"
                className="md-profile__menu-item md-profile__menu-item--danger"
                onClick={handleLogout}
              >
                <LogOut size={16} />
                Logout
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="md-content">{renderPage()}</main>

      {showAccountStatus && (
        <AccountStatusModal
          onClose={() => setShowAccountStatus(false)}
          onNavigate={(pageKey) => {
            setShowAccountStatus(false);
            handleNavigation(pageKey);
          }}
        />
      )}
      {showEmploymentProfileModal && (
        <EmploymentProfileModal
          onCompleted={() => {
            setShowEmploymentProfileModal(false);
            setPage("home");
          }}
        />
      )}
    </div>
  );
}
