import { Link, Navigate, Outlet, createBrowserRouter } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import AuthPage from "../pages/Auth";
import AnalyticsPage from "../pages/Analytics";
import DashboardPage from "../pages/Dashboard";
import MeetingsPage from "../pages/Meetings";
import SearchPage from "../pages/Search";
import MeetingDetailsPage from "../pages/MeetingDetails";
import UploadPage from "../pages/Upload";

export function ProtectedLayout() {
  const { user, isAuthenticated, logout } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/dashboard">MannerAI</Link>
        <nav aria-label="Main navigation">
          <Link to="/dashboard">Dashboard</Link>
          <Link to="/meetings">Meetings</Link>
          <Link to="/search">Search</Link>
          <Link to="/analytics">Analytics</Link>
        </nav>
        <div className="account-menu">
          <span>{user?.email}</span>
          <button className="button button-quiet" onClick={() => void logout()} type="button">Log out</button>
        </div>
      </header>
      <main className="page-container"><Outlet /></main>
    </div>
  );
}

function Placeholder({ title, description }: { title: string; description: string }) {
  return (
    <section className="placeholder-card" aria-labelledby="placeholder-title">
      <p className="eyebrow">Phase 14</p>
      <h1 id="placeholder-title">{title}</h1>
      <p>{description}</p>
      <p className="muted">This page will be implemented in a later Phase 14 block.</p>
    </section>
  );
}

export const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/dashboard" replace /> },
  { path: "/login", element: <AuthPage mode="login" /> },
  { path: "/signup", element: <AuthPage mode="signup" /> },
  {
    element: <ProtectedLayout />,
    children: [
      { path: "/dashboard", element: <DashboardPage /> },
      { path: "/meetings", element: <MeetingsPage /> },
      { path: "/meetings/:meetingId", element: <MeetingDetailsPage /> },
      { path: "/upload", element: <UploadPage /> },
      { path: "/search", element: <SearchPage /> },
      { path: "/analytics", element: <AnalyticsPage /> },
    ],
  },
  { path: "*", element: <Placeholder title="Page not found" description="The requested page does not exist." /> },
]);
