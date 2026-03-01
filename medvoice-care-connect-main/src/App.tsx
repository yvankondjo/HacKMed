import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { DashboardLayout } from "@/components/DashboardLayout";
import { PatientLayout } from "@/components/PatientLayout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import AppointmentDetail from "./pages/AppointmentDetail";
import Patients from "./pages/Patients";
import PatientDetail from "./pages/PatientDetail";
import PatientDashboard from "./pages/PatientDashboard";
import NotFound from "./pages/NotFound";
import ProductLifecycle from "./pages/ProductLifecycle";
import Agenda from "./pages/Agenda";

const queryClient = new QueryClient();

function ProtectedRoute({ children, role }: { children: React.ReactNode; role?: "doctor" | "patient" }) {
  const { isAuthenticated, user } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (role && user?.role !== role) {
    return <Navigate to={user?.role === "patient" ? "/patient" : "/"} replace />;
  }
  return <>{children}</>;
}

const AppRoutes = () => {
  const { isAuthenticated, user } = useAuth();

  const defaultRedirect = user?.role === "patient" ? "/patient" : "/";

  return (
    <Routes>
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to={defaultRedirect} replace /> : <Login />}
      />
      {/* Doctor routes */}
      <Route
        path="/"
        element={
          <ProtectedRoute role="doctor">
            <DashboardLayout><Dashboard /></DashboardLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/appointments/:id"
        element={
          <ProtectedRoute role="doctor">
            <DashboardLayout><AppointmentDetail /></DashboardLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/patients"
        element={
          <ProtectedRoute role="doctor">
            <DashboardLayout><Patients /></DashboardLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/patients/:id"
        element={
          <ProtectedRoute role="doctor">
            <DashboardLayout><PatientDetail /></DashboardLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/agenda"
        element={
          <ProtectedRoute role="doctor">
            <DashboardLayout><Agenda /></DashboardLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/lifecycle"
        element={
          <ProtectedRoute role="doctor">
            <DashboardLayout><ProductLifecycle /></DashboardLayout>
          </ProtectedRoute>
        }
      />
      {/* Patient routes */}
      <Route
        path="/patient"
        element={
          <ProtectedRoute role="patient">
            <PatientLayout><PatientDashboard /></PatientLayout>
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
};

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
