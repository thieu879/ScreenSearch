import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Search,
  History,
  Share2,
  Bell,
  HelpCircle,
  Settings,
  LogOut,
  User,
  Menu,
  Sparkles,
  Globe,
  LogIn,
  UserPlus,
  Sun,
  Moon,
} from 'lucide-react';
import { useAuth } from '../../../contexts/AuthContext';
import { useTheme } from '../../../contexts/ThemeContext';
import './TopBar.css';

export interface TopBarProps {
  activeTab?: string;
  pageTitle?: string;
  roleBadge?: string;
  userName?: string;
  userRole?: string;
  avatarUrl?: string;
  onToggleMenu?: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  activeTab,
  pageTitle,
  roleBadge,
  userName,
  userRole,
  avatarUrl,
  onToggleMenu,
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { t, i18n } = useTranslation();

  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  const currentPath = location.pathname;
  const isAdminPage = currentPath.startsWith('/admin');

  const currentLang = i18n.language || 'vi';

  const toggleLanguage = () => {
    const nextLang = currentLang === 'vi' ? 'en' : 'vi';
    i18n.changeLanguage(nextLang);
    localStorage.setItem('ssp_lang', nextLang);
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setIsUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const isActive = (tabKey: string, path: string) => {
    if (activeTab) return activeTab === tabKey;
    return currentPath === path || currentPath.startsWith(path);
  };

  // A signed-in person's name and role come from their account, never from a caller's prop.
  //
  // Preferring `userRole` for a non-Admin is what put "Engineer" in the corner on `/search` and
  // "Người dùng" on `/history` for the same user one click apart — `SceneSearchAI` was passing a
  // hardcoded `userRole="Engineer"` and `userName="Engineer A"`, and `Engineer` is not a role this
  // system has: there are two, `Admin` and `User`. The props stay for a caller with no session, and
  // the four admin pages that still pass them now pass exactly what this derives anyway.
  const finalName = user?.full_name || user?.username || user?.email?.split('@')[0] || userName || t('regular_user');
  const finalRole = user
    ? user.role === 'Admin'
      ? t('system_admin')
      : t('regular_user')
    : userRole || t('regular_user');
  const finalAvatar = user?.avatar || avatarUrl;
  const initials = finalName.substring(0, 2).toUpperCase();

  const handleLogout = async () => {
    setIsUserMenuOpen(false);
    await logout();
    navigate('/login');
  };

  // If rendering inside Admin pages (/admin, /admin/users, /admin/monitoring):
  if (isAdminPage) {
    return (
      <header className="ssp-top-bar">
        <div className="ssp-top-bar-left">
          <button
            type="button"
            className="ssp-btn-menu-toggle"
            onClick={onToggleMenu}
            title="Menu"
            aria-label="Toggle navigation menu"
          >
            <Menu size={22} />
          </button>
          <h2 className="ssp-page-title">{pageTitle || t('nav_dashboard')}</h2>
          {roleBadge && <span className="ssp-role-badge">{roleBadge}</span>}
        </div>

        <div className="ssp-top-bar-right">
          <div className="ssp-icon-actions">
            <button
              type="button"
              className="ssp-lang-toggle-btn"
              onClick={toggleTheme}
              title={theme === 'dark' ? t('theme_toggle_light') : t('theme_toggle_dark')}
              aria-label="Toggle theme mode"
            >
              {theme === 'dark' ? <Sun size={16} style={{ color: '#fbbf24' }} /> : <Moon size={16} style={{ color: '#60a5fa' }} />}
              <span>{theme === 'dark' ? t('theme_day') : t('theme_night')}</span>
            </button>
            <button
              type="button"
              className="ssp-lang-toggle-btn"
              onClick={toggleLanguage}
              title={currentLang === 'vi' ? 'Switch to English' : 'Chuyển sang Tiếng Việt'}
            >
              <Globe size={16} />
              <span>{currentLang === 'vi' ? 'EN' : 'VI'}</span>
            </button>
            <button type="button" className="ssp-btn-icon" title={t('notifications')} aria-label={t('notifications')}>
              <Bell size={18} />
            </button>
            <button type="button" className="ssp-btn-icon" title={t('help')} aria-label={t('help')}>
              <HelpCircle size={18} />
            </button>
            <button type="button" className="ssp-btn-icon" title={t('settings')} aria-label={t('settings')}>
              <Settings size={18} />
            </button>
          </div>

          {isAuthenticated && user ? (
            <div className="ssp-user-profile-wrapper" ref={userMenuRef}>
              <button
                type="button"
                className="ssp-user-profile-btn"
                onClick={() => setIsUserMenuOpen((prev) => !prev)}
                aria-label="User Profile Menu"
              >
                <div className="ssp-user-info">
                  <p className="ssp-user-name">{finalName}</p>
                  <p className="ssp-user-role">{finalRole}</p>
                </div>
                {finalAvatar ? (
                  <img className="ssp-avatar" alt="Profile" src={finalAvatar} />
                ) : (
                  <div className="ssp-avatar-fallback">{initials}</div>
                )}
              </button>

              {isUserMenuOpen && (
                <div className="ssp-user-dropdown-menu">
                  <button
                    type="button"
                    className="ssp-dropdown-item"
                    onClick={() => {
                      setIsUserMenuOpen(false);
                      navigate('/profile');
                    }}
                  >
                    <User size={16} />
                    <span>{t('profile')}</span>
                  </button>
                  <div className="ssp-dropdown-divider" />
                  <button
                    type="button"
                    className="ssp-dropdown-item danger"
                    onClick={handleLogout}
                  >
                    <LogOut size={16} />
                    <span>{t('logout')}</span>
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="ssp-auth-buttons">
              <button
                type="button"
                className="ssp-btn-register"
                onClick={() => navigate('/register')}
              >
                <UserPlus size={16} />
                <span>{t('register')}</span>
              </button>
              <button
                type="button"
                className="ssp-btn-login"
                onClick={() => navigate('/login')}
              >
                <LogIn size={16} />
                <span>{t('login')}</span>
              </button>
            </div>
          )}
        </div>
      </header>
    );
  }

  // User Pages (/search, /history, /export):
  return (
    <header className="ssp-header-root">
      <div className="ssp-header-container">
        {/* Left: Brand Logo & Title */}
        <div className="ssp-header-brand" onClick={() => navigate('/')}>
          <div className="ssp-brand-badge">
            <Sparkles size={16} />
            <span>SSP</span>
          </div>
          <div className="ssp-brand-text-wrap">
            <span className="ssp-brand-title">{t('brand_title')}</span>
            <span className="ssp-brand-subtitle">{t('brand_subtitle')}</span>
          </div>
        </div>

        {/* Center: Main Navigation Links */}
        <nav className="ssp-header-nav" aria-label="Main Navigation">
          <button
            type="button"
            className={`ssp-nav-tab ${isActive('search', '/search') ? 'active' : ''}`}
            onClick={() => navigate('/search')}
          >
            <Search size={17} />
            <span>{t('nav_search')}</span>
          </button>

          <button
            type="button"
            className={`ssp-nav-tab ${isActive('history', '/history') ? 'active' : ''}`}
            onClick={() => navigate('/history')}
          >
            <History size={17} />
            <span>{t('nav_history')}</span>
          </button>

          <button
            type="button"
            className={`ssp-nav-tab ${isActive('export', '/export') ? 'active' : ''}`}
            onClick={() => navigate('/export')}
          >
            <Share2 size={17} />
            <span>{t('nav_export')}</span>
          </button>
        </nav>

        {/* Right: Actions & Profile */}
        <div className="ssp-header-right">
          <div className="ssp-quick-actions">
            <button
              type="button"
              className="ssp-lang-toggle-btn"
              onClick={toggleTheme}
              title={theme === 'dark' ? t('theme_toggle_light') : t('theme_toggle_dark')}
              aria-label="Toggle theme mode"
            >
              {theme === 'dark' ? <Sun size={16} style={{ color: '#fbbf24' }} /> : <Moon size={16} style={{ color: '#60a5fa' }} />}
              <span>{theme === 'dark' ? t('theme_day') : t('theme_night')}</span>
            </button>
            <button
              type="button"
              className="ssp-lang-toggle-btn"
              onClick={toggleLanguage}
              title={currentLang === 'vi' ? 'Switch to English' : 'Chuyển sang Tiếng Việt'}
            >
              <Globe size={16} />
              <span>{currentLang === 'vi' ? 'EN' : 'VI'}</span>
            </button>
          </div>

          {isAuthenticated && user ? (
            <div className="ssp-user-profile-wrapper" ref={userMenuRef}>
              <button
                type="button"
                className="ssp-user-profile-btn"
                onClick={() => setIsUserMenuOpen((prev) => !prev)}
                aria-label="User Profile Menu"
              >
                <div className="ssp-user-info">
                  <p className="ssp-user-name">{finalName}</p>
                  <span className="ssp-user-role">{finalRole}</span>
                </div>
                {finalAvatar ? (
                  <img className="ssp-avatar" alt={finalName} src={finalAvatar} />
                ) : (
                  <div className="ssp-avatar-fallback">{initials}</div>
                )}
              </button>

              {isUserMenuOpen && (
                <div className="ssp-user-dropdown-menu">
                  <button
                    type="button"
                    className="ssp-dropdown-item"
                    onClick={() => {
                      setIsUserMenuOpen(false);
                      navigate('/profile');
                    }}
                  >
                    <User size={16} />
                    <span>{t('profile')}</span>
                  </button>
                  <div className="ssp-dropdown-divider" />
                  <button
                    type="button"
                    className="ssp-dropdown-item danger"
                    onClick={handleLogout}
                  >
                    <LogOut size={16} />
                    <span>{t('logout')}</span>
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="ssp-auth-buttons">
              <button
                type="button"
                className="ssp-btn-register"
                onClick={() => navigate('/register')}
              >
                <UserPlus size={16} />
                <span>{t('register')}</span>
              </button>
              <button
                type="button"
                className="ssp-btn-login"
                onClick={() => navigate('/login')}
              >
                <LogIn size={16} />
                <span>{t('login')}</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};

export default TopBar;
