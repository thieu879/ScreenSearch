import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Mail,
  Lock,
  Eye,
  EyeOff,
  Sparkles,
  ShieldCheck,
  Cpu,
  Layers,
  ArrowRight,
  Activity,
} from 'lucide-react';
import { useToast } from '../../components/base/Toast/useToast';
import { ToastContainer } from '../../components/base/Toast/Toast';
import { fetchCorpusStatus } from '../../api/client';
import { useAuth } from '../../contexts/AuthContext';
import { HomeHeader } from '../../components/layout/HomeHeader/HomeHeader';
import type { CorpusStatus } from '../../types/api';

import './Login.css';

// Baked in at build time by `vite build` (Dockerfile, frontend stage), NOT read at runtime — so a
// deploy whose image was built without it can never acquire it from the server's .env. Empty means
// Google sign-in is not configured for this build, and the button is hidden rather than shown
// broken: through v1.7 it was rendered and told a visitor to edit a server file.
const GOOGLE_CLIENT_ID: string = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';


export const Login: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const { messages, addToast, dismiss } = useToast();
  const { login } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [isLoading, setIsLoading] = useState(false);

  // Every figure in the hero is read from the running server.
  const [corpus, setCorpus] = useState<CorpusStatus | null>(null);

  useEffect(() => {
    const warningMsg = location.state?.warning || location.state?.message;
    if (warningMsg) {
      addToast('warning', t('login_toast_req_login'), warningMsg);
    }
  }, [location.state, addToast, t]);

  useEffect(() => {
    let cancelled = false;
    fetchCorpusStatus()
      .then((value) => !cancelled && setCorpus(value))
      .catch(() => {
        /* Hero metrics are decoration; a login page must still render without the API. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    addToast('info', t('login_toast_authenticating_title'), t('login_toast_authenticating_msg'));

    try {
      const user = await login(email, password);

      addToast('success', t('login_toast_success_title'), t('login_toast_success_msg'));
      const fromPath = location.state?.from?.pathname || (typeof location.state?.from === 'string' ? location.state.from : null);
      setTimeout(() => {
        if (fromPath) {
          navigate(fromPath);
        } else if (user.role === 'Admin') {
          navigate('/admin');
        } else {
          navigate('/search');
        }
      }, 700);
    } catch (err: unknown) {
      const error = err as Error;
      addToast('error', t('login_toast_failed_title'), error.message || t('login_toast_failed_msg'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', backgroundColor: '#0b0f19' }}>
      <HomeHeader />
      <div className="ssp-login-split-layout" style={{ flex: 1, minHeight: 'calc(100vh - 76px)' }}>
        {/* Ambient Animated Orbs */}
        <div className="ssp-glow-orb orb-1" />
        <div className="ssp-glow-orb orb-2" />
        <div className="ssp-glow-orb orb-3" />

        {/* Left Column: AI Hero & Technology Showcase */}
        <div className="ssp-login-hero-side">
          <div className="ssp-hero-content-wrap">
            <div className="ssp-badge-version">
              <Sparkles size={14} className="ssp-sparkle-icon" />
              <span>{t('login_hero_badge')}</span>
            </div>

            {/* Main Hero Headline */}
            <h1 className="ssp-hero-headline">
              {t('login_hero_title_1')} <br />
              <span className="ssp-gradient-text">{t('login_hero_title_2')}</span>
            </h1>

            <p className="ssp-hero-description">
              {t('login_hero_desc')}
            </p>

            {/* Counts, not claims — and only once the server has told us what they are. */}
            {corpus !== null && (
              <div className="ssp-hero-metrics-grid">
                <div className="ssp-hero-metric-card">
                  <div className="ssp-metric-icon-wrap green">
                    <Layers size={20} />
                  </div>
                  <div className="ssp-metric-info">
                    <div className="ssp-metric-value">{corpus.corpus_frames.toLocaleString('vi-VN')}</div>
                    <div className="ssp-metric-label">{t('login_metric_frames')}</div>
                  </div>
                </div>

                {corpus.provenance?.n_scenes !== undefined && (
                  <div className="ssp-hero-metric-card">
                    <div className="ssp-metric-icon-wrap blue">
                      <Activity size={20} />
                    </div>
                    <div className="ssp-metric-info">
                      <div className="ssp-metric-value">{corpus.provenance.n_scenes}</div>
                      <div className="ssp-metric-label">{t('login_metric_scenes')}</div>
                    </div>
                  </div>
                )}

                <div className="ssp-hero-metric-card">
                  <div className="ssp-metric-icon-wrap">
                    <Cpu size={20} />
                  </div>
                  <div className="ssp-metric-info">
                    <div className="ssp-metric-value ssp-metric-value--text">
                      {corpus.encoder.split(':')[1] ?? corpus.encoder}
                    </div>
                    <div className="ssp-metric-label">{t('login_metric_encoder')}</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Premium Form Section */}
        <div className="ssp-login-form-side">
          <main className="ssp-form-card-wrapper">
            <div className="ssp-login-glass-card">
              {/* Brand Logo & Header */}
              <div className="ssp-form-header">
                <div className="ssp-brand-logo-ring">
                  <span className="ssp-brand-logo-text">SSP</span>
                </div>
                <h2 className="ssp-form-title">{t('login_form_title')}</h2>
                <p className="ssp-form-subtitle">{t('login_form_subtitle')}</p>
              </div>

              {/* Login Form */}
              <form className="ssp-form-body" onSubmit={handleSubmit}>
                {/* Email Field */}
                <div className="ssp-form-field">
                  <label className="ssp-field-label" htmlFor="email">
                    {t('login_label_email')}
                  </label>
                  <div className="ssp-input-input-wrap">
                    <Mail className="ssp-field-left-icon" size={18} />
                    <input
                      id="email"
                      name="email"
                      type="email"
                      className="ssp-real-input"
                      placeholder={t('login_placeholder_email')}
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required
                    />
                  </div>
                </div>

                {/* Password Field */}
                <div className="ssp-form-field">
                  <div className="ssp-label-row">
                    <label className="ssp-field-label" htmlFor="password">
                      {t('login_label_password')}
                    </label>
                    <Link
                      to="/forgot-password"
                      className="ssp-link-forgot"
                    >
                      {t('login_forgot_password')}
                    </Link>
                  </div>
                  <div className="ssp-input-input-wrap">
                    <Lock className="ssp-field-left-icon" size={18} />
                    <input
                      id="password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      className="ssp-real-input has-right-btn"
                      placeholder="••••••••"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                    />
                    <button
                      type="button"
                      className="ssp-btn-eye"
                      onClick={() => setShowPassword(!showPassword)}
                      aria-label="Toggle password visibility"
                    >
                      {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </div>

                {/* Remember Me Options */}
                <div className="ssp-options-flex">
                  <label className="ssp-checkbox-container" htmlFor="remember-me">
                    <input
                      id="remember-me"
                      type="checkbox"
                      checked={rememberMe}
                      onChange={(e) => setRememberMe(e.target.checked)}
                    />
                    <span className="ssp-custom-checkbox" />
                    <span className="ssp-checkbox-text">{t('login_remember_me')}</span>
                  </label>
                </div>

                {/* Submit CTA Button */}
                <button
                  type="submit"
                  className="ssp-btn-login-submit"
                  disabled={isLoading}
                >
                  <span>{isLoading ? t('login_btn_submitting') : t('login_btn_submit')}</span>
                  <ArrowRight size={18} />
                </button>
              </form>

              {GOOGLE_CLIENT_ID && (
                <>
                {/* Google OAuth SSO */}
                <div className="ssp-divider-or" style={{ display: 'flex', alignItems: 'center', margin: '1.2rem 0', color: '#64748b', fontSize: '0.8rem' }}>
                  <div style={{ flex: 1, height: '1px', background: 'rgba(255, 255, 255, 0.1)' }} />
                  <span style={{ padding: '0 0.8rem' }}>{t('login_or')}</span>
                  <div style={{ flex: 1, height: '1px', background: 'rgba(255, 255, 255, 0.1)' }} />
                </div>

                <button
                  type="button"
                  className="ssp-btn-google-login"
                  onClick={() => {
                    const clientId = GOOGLE_CLIENT_ID;
                    const redirectUri = import.meta.env.VITE_GOOGLE_REDIRECT_URI || `${window.location.origin}/auth/google/callback`;
                    const params = new URLSearchParams({
                      client_id: clientId,
                      redirect_uri: redirectUri,
                      response_type: 'code',
                      scope: 'openid email profile',
                      prompt: 'select_account',
                    });
                    window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
                  }}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '10px',
                    padding: '0.75rem',
                    borderRadius: '10px',
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid rgba(255, 255, 255, 0.15)',
                    color: '#f8fafc',
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                  }}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
                  </svg>
                  <span>{t('login_btn_google')}</span>
                </button>
                </>
              )}

              {/* Register Prompt */}
              <div className="ssp-register-prompt" style={{ marginTop: '1.5rem' }}>
                <span>{t('login_no_account')}</span>
                <Link to="/register" className="ssp-link-register">
                  {t('login_register_now')}
                </Link>
              </div>

              <div className="ssp-form-security-footer">
                <ShieldCheck size={14} />
                <span>{t('login_security_footer')}</span>
              </div>
            </div>
          </main>
        </div>

        <ToastContainer messages={messages} onDismiss={dismiss} />
      </div>
    </div>
  );
};

export default Login;
