import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import AuthRequiredModal from '../components/auth/AuthRequiredModal/AuthRequiredModal';
import Home from '../pages/Home/Home';
import SceneSearchAI from '../pages/SceneSearchAI/SceneSearchAI';
import SceneDetail from '../pages/SceneDetail/SceneDetail';
import SearchHistory from '../pages/SearchHistory/SearchHistory';
import ExportData from '../pages/ExportData/ExportData';
import Login from '../pages/Login/Login';
import Register from '../pages/Register/Register';
import ForgotPassword from '../pages/ForgotPassword/ForgotPassword';
import GoogleCallback from '../pages/GoogleCallback/GoogleCallback';
import Profile from '../pages/Profile/Profile';
import AdminDashboard from '../pages/AdminDashboard/AdminDashboard';
import DatasetManagement from '../pages/DatasetManagement/DatasetManagement';
import UserManagement from '../pages/UserManagement/UserManagement';
import SystemMonitoring from '../pages/SystemMonitoring/SystemMonitoring';
// `i18n.t` rather than the hook: these two are plain returns inside route guards, and adding a
// hook to a component that renders one line of text would be the larger change.
import i18n from '../i18n';

/**
 * ProtectedRoute — uses AuthContext instead of localStorage.
 *
 * Shows a loading spinner while the auth state is being restored from cookies on mount.
 * Shows a sleek AuthRequiredModal if unauthenticated.
 */
const ProtectedRoute: React.FC<{ children: React.ReactNode; requireAdmin?: boolean }> = ({ children, requireAdmin }) => {
  const { isAuthenticated, user, loading } = useAuth();

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#0a0a0f' }}>
        <div style={{ color: '#8b5cf6', fontSize: '1.2rem' }}>{i18n.t('app_loading')}</div>
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return <AuthRequiredModal isOpen={true} />;
  }

  if (requireAdmin && user.role !== 'Admin') {
    return <Navigate to="/search" replace />;
  }

  return <>{children}</>;
};

/**
 * GuestRoute — redirects authenticated users away from login/register.
 */
const GuestRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, user, loading } = useAuth();

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#0a0a0f' }}>
        <div style={{ color: '#8b5cf6', fontSize: '1.2rem' }}>{i18n.t('app_loading')}</div>
      </div>
    );
  }

  if (isAuthenticated && user) {
    return <Navigate to={user.role === 'Admin' ? '/admin' : '/search'} replace />;
  }

  return <>{children}</>;
};

export const AppRouter: React.FC = () => {
  return (
    <Routes>
      {/* Public / Guest Routes */}
      <Route path="/login" element={<GuestRoute><Login /></GuestRoute>} />
      <Route path="/register" element={<GuestRoute><Register /></GuestRoute>} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/auth/google/callback" element={<GoogleCallback />} />

      {/* Public Home Landing Page (Không cần đăng nhập vẫn mở được) */}
      <Route path="/" element={<Home />} />

      {/* Protected Product Routes (Yêu cầu đăng nhập) */}
      <Route path="/search" element={<ProtectedRoute><SceneSearchAI /></ProtectedRoute>} />
      <Route path="/archive" element={<ProtectedRoute><SceneSearchAI /></ProtectedRoute>} />
      <Route path="/history" element={<ProtectedRoute><SearchHistory /></ProtectedRoute>} />
      <Route path="/export" element={<ProtectedRoute><ExportData /></ProtectedRoute>} />
      <Route path="/scene/:id" element={<ProtectedRoute><SceneDetail /></ProtectedRoute>} />
      <Route path="/detail" element={<ProtectedRoute><SceneDetail /></ProtectedRoute>} />
      <Route path="/profile" element={<ProtectedRoute><Profile /></ProtectedRoute>} />

      {/* Protected Admin Routes */}
      <Route path="/admin" element={<ProtectedRoute requireAdmin><AdminDashboard /></ProtectedRoute>} />
      <Route path="/dashboard" element={<ProtectedRoute requireAdmin><AdminDashboard /></ProtectedRoute>} />
      <Route path="/admin/dataset" element={<ProtectedRoute requireAdmin><DatasetManagement /></ProtectedRoute>} />
      <Route path="/dataset" element={<ProtectedRoute requireAdmin><DatasetManagement /></ProtectedRoute>} />
      <Route path="/admin/users" element={<ProtectedRoute requireAdmin><UserManagement /></ProtectedRoute>} />
      <Route path="/users" element={<ProtectedRoute requireAdmin><UserManagement /></ProtectedRoute>} />
      <Route path="/admin/monitoring" element={<ProtectedRoute requireAdmin><SystemMonitoring /></ProtectedRoute>} />
      <Route path="/monitoring" element={<ProtectedRoute requireAdmin><SystemMonitoring /></ProtectedRoute>} />

      {/* Fallback to Home landing page */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default AppRouter;
