import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LayoutDashboard, Database, Users, Activity, LogOut, X } from 'lucide-react';
import { useAuth } from '../../../contexts/AuthContext';
import './Sidebar.css';

export interface AdminSidebarProps {
  activeTab?: string;
  onSelectTab?: (tab: string) => void;
  isOpen?: boolean;
  onClose?: () => void;
}

export const AdminSidebar: React.FC<AdminSidebarProps> = ({
  activeTab = 'dashboard',
  onSelectTab,
  isOpen = false,
  onClose,
}) => {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const { t } = useTranslation();

  const handleNav = (tab: string, path: string) => {
    if (onSelectTab) {
      onSelectTab(tab);
    }
    if (onClose) {
      onClose();
    }
    if (path.startsWith('#')) {
      return;
    }
    navigate(path);
  };

  const handleLogout = async () => {
    if (onClose) onClose();
    await logout();
    navigate('/login');
  };

  return (
    <>
      {isOpen && (
        <div
          className="ssp-sidebar-backdrop"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside className={`ssp-sidebar ${isOpen ? 'mobile-open' : ''}`}>
        <div className="ssp-sidebar-header">
          <div className="ssp-sidebar-header-top">
            <h1 className="ssp-sidebar-title">SSP</h1>
            {onClose && (
              <button
                type="button"
                className="ssp-sidebar-close-btn"
                onClick={onClose}
                aria-label="Close admin sidebar"
              >
                <X size={20} />
              </button>
            )}
          </div>
          <p className="ssp-sidebar-subtitle">Semantic Admin Control</p>
        </div>

        <nav className="ssp-sidebar-nav" aria-label="Admin sidebar navigation">
          <button
            type="button"
            className={`ssp-nav-item ${activeTab === 'dashboard' || activeTab === 'admin' ? 'active' : ''}`}
            onClick={() => handleNav('dashboard', '/admin')}
          >
            <LayoutDashboard size={18} />
            <span>{t('nav_dashboard')}</span>
          </button>

          <button
            type="button"
            className={`ssp-nav-item ${activeTab === 'dataset' ? 'active' : ''}`}
            onClick={() => handleNav('dataset', '/admin/dataset')}
          >
            <Database size={18} />
            <span>{t('nav_dataset')}</span>
          </button>

          <button
            type="button"
            className={`ssp-nav-item ${activeTab === 'users' ? 'active' : ''}`}
            onClick={() => handleNav('users', '/admin/users')}
          >
            <Users size={18} />
            <span>{t('nav_users')}</span>
          </button>

          <button
            type="button"
            className={`ssp-nav-item ${activeTab === 'monitoring' ? 'active' : ''}`}
            onClick={() => handleNav('monitoring', '/admin/monitoring')}
          >
            <Activity size={18} />
            <span>{t('nav_monitoring')}</span>
          </button>
        </nav>

        <div className="ssp-sidebar-footer">
          <button
            type="button"
            className="ssp-btn-logout"
            onClick={handleLogout}
          >
            <LogOut size={18} />
            <span>{t('logout')}</span>
          </button>
        </div>
      </aside>
    </>
  );
};

export default AdminSidebar;
