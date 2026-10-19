import { Navigate } from "react-router-dom";

// Where each role lands. "subadmin" has no dashboard of its own yet, so it uses the member one.
const ROLE_HOME = {
  superadmin: "/dashboard/superadmin",
  admin: "/dashboard/admin",
  subadmin: "/dashboard/member",
  member: "/dashboard/member",
};

export default function ProtectedRoute({ children, allowedRoles }) {
  const token = localStorage.getItem("access_token");
  if (!token) {
    return <Navigate to="/auth" replace />;
  }

  let user = null;
  try {
    user = JSON.parse(localStorage.getItem("user") || "null");
  } catch {
    user = null;
  }

  // Broken session data: clear it so PublicRoute cannot bounce back here (no redirect loop)
  if (!user?.role) {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    return <Navigate to="/auth" replace />;
  }

  // Wrong role for this page: send them to their own dashboard
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to={ROLE_HOME[user.role] ?? "/auth"} replace />;
  }

  return children;
}