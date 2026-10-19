import { Routes, Route, Navigate } from "react-router-dom";
import AuthPage from "./Pages/Auth Page/AuthPage";
import SuperAdminDashboard from "./Pages/Dashboard/SuperAdmin/SuperAdminDashboard";
import AdminDashboard from "./Pages/Dashboard/Admin/AdminDashboard";
import MemberDashboard from "./Pages/Dashboard/Member/MemberDashboard";
import ProtectedRoute from "./ProtectedRoute";
import PublicRoute from "./PublicRoute";

export default function App() {
  return (
    <Routes>
      <Route
        path="/auth"
        element={
          <PublicRoute>
            <AuthPage />
          </PublicRoute>
        }
      />
       <Route
        path="/dashboard/superadmin"
        element={
          <ProtectedRoute allowedRoles={["superadmin"]}>
            <SuperAdminDashboard />
          </ProtectedRoute>
        }
      />

      {/* Admin */}
      <Route
        path="/dashboard/admin"
        element={
          <ProtectedRoute allowedRoles={["admin"]}>
            <AdminDashboard />
          </ProtectedRoute>
        }
      />

      {/* Member */}
      <Route
        path="/dashboard/member"
        element={
          <ProtectedRoute allowedRoles={["member", "subadmin"]}>
            <MemberDashboard />
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<Navigate to="/auth" replace />} />
    </Routes>
  );
}