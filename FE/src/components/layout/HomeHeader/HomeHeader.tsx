import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Sparkles,
  Globe,
  LogIn,
  UserPlus,
  ArrowRight,
  Sun,
  Moon,
} from 'lucide-react';
import { useAuth } from '../../../contexts/AuthContext';
import { useTheme } from '../../../contexts/ThemeContext';
import '../../../pages/Home/Home.css';
import './HomeHeader.css';

export const HomeHeader: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated, user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { t, i18n } = useTranslation();

  const currentLang = i18n.language || 'vi';

  const toggleLanguage = () => {
    const nextLang = currentLang === 'vi' ? 'en' : 'vi';
    i18n.changeLanguage(nextLang);
    localStorage.setItem('ssp_lang', nextLang);
  };

  const handleNavClick = (hash: string) => {
    const targetId = hash.replace('#', '');
    if (window.location.pathname === '/') {
      const el = document.getElementById(targetId);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        window.history.pushState({}, '', hash);
      }
    } else {
      navigate('/' + hash);
    }
  };

  const handleGetStarted = () => {
    if (isAuthenticated && user) {
      navigate(user.role === 'Admin' ? '/admin' : '/search');
    } else {
      navigate('/login');
    }
  };

  return (
    <header className="ssp-home-header">
      <div className="ssp-home-nav-container">
        <div className="ssp-home-brand" onClick={() => navigate('/')}>
          <div className="ssp-home-brand-badge">
            <Sparkles size={18} />
            <span>SSP</span>
          </div>
          <div className="ssp-home-brand-text">
            <span className="ssp-home-brand-title">{t('brand_title')}</span>
            <span className="ssp-home-brand-sub">{t('brand_subtitle')}</span>
          </div>
        </div>

        <nav className="ssp-home-nav-links">
          <a href="/#features" onClick={(e) => { e.preventDefault(); handleNavClick('#features'); }} className="ssp-home-link">{t('home_nav_features')}</a>
          <a href="/#architecture" onClick={(e) => { e.preventDefault(); handleNavClick('#architecture'); }} className="ssp-home-link">{t('home_nav_architecture')}</a>
          <a href="/#dataset" onClick={(e) => { e.preventDefault(); handleNavClick('#dataset'); }} className="ssp-home-link">{t('home_nav_dataset')}</a>
          <a href="/#workflow" onClick={(e) => { e.preventDefault(); handleNavClick('#workflow'); }} className="ssp-home-link">{t('home_nav_workflow')}</a>
        </nav>

        <div className="ssp-home-header-actions">
          {/* Theme Toggle Button (Light/Dark mode) */}
          <button
            type="button"
            className="ssp-home-lang-btn"
            onClick={toggleTheme}
            title={theme === 'dark' ? t('theme_toggle_light') : t('theme_toggle_dark')}
            aria-label="Toggle light and dark theme mode"
          >
            {theme === 'dark' ? <Sun size={16} style={{ color: '#fbbf24' }} /> : <Moon size={16} style={{ color: '#60a5fa' }} />}
            <span>{theme === 'dark' ? t('theme_day') : t('theme_night')}</span>
          </button>

          {/* Language Switcher */}
          <button
            type="button"
            className="ssp-home-lang-btn"
            onClick={toggleLanguage}
            title={currentLang === 'vi' ? 'Switch to English' : 'Chuyển sang Tiếng Việt'}
          >
            <Globe size={16} />
            <span>{currentLang === 'vi' ? 'EN' : 'VI'}</span>
          </button>

          {isAuthenticated && user ? (
            <button
              type="button"
              className="ssp-home-btn-primary"
              onClick={handleGetStarted}
            >
              <span>{t('home_btn_app')}</span>
              <ArrowRight size={16} />
            </button>
          ) : (
            <>
              <button
                type="button"
                className="ssp-home-btn-outline"
                onClick={() => navigate('/register')}
              >
                <UserPlus size={16} />
                <span>{t('home_btn_register')}</span>
              </button>
              <button
                type="button"
                className="ssp-home-btn-primary"
                onClick={() => navigate('/login')}
              >
                <LogIn size={16} />
                <span>{t('home_btn_login')}</span>
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  );
};

export default HomeHeader;
