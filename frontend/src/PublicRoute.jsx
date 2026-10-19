import { Navigate } from "react-router-dom";

export default function PublicRoute({ children }) {
  const token = localStorage.getItem("access_token");
  const userData = localStorage.getItem("user");

  let user = null;

  try {
    user = userData ? JSON.parse(userData) : null;
  } catch (error) {
    console.error("Invalid user data in localStorage:", error);
    localStorage.removeItem("user");
  }

  if (token && user) {
    switch (user.role) {
      case "superadmin":
        return <Navigate to="/dashboard/superadmin" replace />;

      case "admin":
        return <Navigate to="/dashboard/admin" replace />;

      case "subadmin":
        return <Navigate to="/dashboard/member" replace />;   // FIX: /dashboard/subadmin does not exist (caused a redirect loop)

      case "member":
        return <Navigate to="/dashboard/member" replace />;

      default:
        break;
    }
  }

  return children;
}