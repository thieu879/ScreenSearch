import React, { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
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
  User,
  Key,
} from 'lucide-react';
import { useToast } from '../../components/base/Toast/useToast';
import { ToastContainer } from '../../components/base/Toast/Toast';
import { fetchCorpusStatus } from '../../api/client';
import { useAuth } from '../../contexts/AuthContext';
import { authSendOtp } from '../../api/auth';
import { HomeHeader } from '../../components/layout/HomeHeader/HomeHeader';
import type { CorpusStatus } from '../../types/api';

import '../Login/Login.css';
import './Register.css';

// Baked in at build time by `vite build` (Dockerfile, frontend stage), NOT read at runtime — so a
// deploy whose image was built without it can never acquire it from the server's .env. Empty means
// Google sign-in is not configured for this build, and the button is hidden rather than shown
// broken: through v1.7 it was rendered and told a visitor to edit a server file.
const GOOGLE_CLIENT_ID: string = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';


export const Register: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { messages, addToast, dismiss } = useToast();
  const { register } = useAuth();

  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // OTP State
  const [otp, setOtp] = useState('');
  const [isSendingOtp, setIsSendingOtp] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [otpExpirySeconds, setOtpExpirySeconds] = useState(0);

  const [isLoading, setIsLoading] = useState(false);
  const [corpus, setCorpus] = useState<CorpusStatus | null>(null);

  const [formData, setFormData] = useState({
    fullName: '',
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
  });

  useEffect(() => {
    let cancelled = false;
    fetchCorpusStatus()
      .then((value) => !cancelled && setCorpus(value))
      .catch(() => {
        /* Hero metrics are decoration */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Timers for OTP resend cooldown (60s) & expiration (300s = 5m)
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setInterval(() => {
      setResendCooldown((prev) => prev - 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [resendCooldown]);

  useEffect(() => {
    if (otpExpirySeconds <= 0) return;
    const timer = setInterval(() => {
      setOtpExpirySeconds((prev) => prev - 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [otpExpirySeconds]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSendOtp = async () => {
    if (!formData.email || !formData.email.includes('@')) {
      addToast('error', t('auth_error_title'), t('auth_error_email_invalid'));
      return;
    }

    setIsSendingOtp(true);
    addToast('info', t('otp_sending_title'), t('otp_sending_desc'));

    try {
      const res = await authSendOtp(formData.email, 'register');
      addToast('success', t('otp_sent_title'), res.message);
      setOtpSent(true);
      setResendCooldown(60);
      setOtpExpirySeconds(300);
    } catch (err: unknown) {
      const error = err as Error;
      addToast('error', t('otp_fail_title'), error.message || t('otp_fail_desc'));
    } finally {
      setIsSendingOtp(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!otpSent || otp.length !== 6) {
      addToast('error', t('auth_error_title'), t('auth_error_otp_invalid'));
      return;
    }

    if (formData.password.length < 8) {
      addToast('error', t('auth_error_title'), t('auth_error_pass_short'));
      return;
    }

    if (formData.password !== formData.confirmPassword) {
      addToast('error', t('auth_error_title'), t('auth_error_pass_mismatch'));
      return;
    }

    setIsLoading(true);
    addToast('info', t('reg_submit_title'), t('reg_submit_desc'));

    try {
      await register(
        formData.email,
        formData.password,
        otp,
        formData.fullName || undefined,
        formData.username || undefined,
      );
      addToast('success', t('reg_success_title'), t('reg_success_desc'));
      setTimeout(() => {
        navigate('/login');
      }, 1200);
    } catch (err: unknown) {
      const error = err as Error;
      addToast('error', t('reg_fail_title'), error.message || t('reg_fail_desc'));
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

            <h1 className="ssp-hero-headline">
              {t('reg_hero_title_1')} <br />
              <span className="ssp-gradient-text">{t('reg_hero_title_2')}</span>
            </h1>

            <p className="ssp-hero-description">
              {t('reg_hero_desc')}
            </p>

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
                <h2 className="ssp-form-title">{t('reg_form_title')}</h2>
                <p className="ssp-form-subtitle">{t('reg_form_subtitle')}</p>
              </div>

              {/* Registration Form */}
              <form className="ssp-form-body" onSubmit={handleSubmit}>
                {/* Full Name Field */}
                <div className="ssp-form-field">
                  <label className="ssp-field-label" htmlFor="fullName">
                    {t('reg_fullname_label')}
                  </label>
                  <div className="ssp-input-input-wrap">
                    <User className="ssp-field-left-icon" size={18} />
                    <input
                      id="fullName"
                      name="fullName"
                      type="text"
                      className="ssp-real-input"
                      placeholder={t('reg_fullname_ph')}
                      value={formData.fullName}
                      onChange={handleChange}
                      required
                    />
                  </div>
                </div>

                {/* Username Field */}
                <div className="ssp-form-field">
                  <label className="ssp-field-label" htmlFor="username">
                    {t('reg_username_label')}
                  </label>
                  <div className="ssp-input-input-wrap">
                    <User className="ssp-field-left-icon" size={18} />
                    <input
                      id="username"
                      name="username"
                      type="text"
                      className="ssp-real-input"
                      placeholder={t('reg_username_ph')}
                      value={formData.username}
                      onChange={handleChange}
                      minLength={3}
                      maxLength={50}
                    />
                  </div>
                </div>

                {/* Email Field with Send OTP Button */}
                <div className="ssp-form-field">
                  <label className="ssp-field-label" htmlFor="email">
                    {t('reg_email_label')}
                  </label>
                  <div className="ssp-input-input-wrap">
                    <Mail className="ssp-field-left-icon" size={18} />
                    <input
                      id="email"
                      name="email"
                      type="email"
                      className="ssp-real-input has-right-btn"
                      placeholder={t('reg_email_ph')}
                      value={formData.email}
                      onChange={handleChange}
                      required
                    />
                    <button
                      type="button"
                      onClick={handleSendOtp}
                      disabled={isSendingOtp || resendCooldown > 0}
                      style={{
                        position: 'absolute',
                        right: '8px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        padding: '0.4rem 0.75rem',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        borderRadius: '8px',
                        background: resendCooldown > 0 ? 'rgba(255,255,255,0.05)' : 'var(--color-primary-600, #8b5cf6)',
                        color: resendCooldown > 0 ? '#94a3b8' : '#ffffff',
                        border: 'none',
                        cursor: isSendingOtp || resendCooldown > 0 ? 'not-allowed' : 'pointer',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {isSendingOtp ? '...' : resendCooldown > 0 ? t('reg_resend_otp_in', { seconds: resendCooldown }) : t('reg_send_otp')}
                    </button>
                  </div>
                </div>

                {/* OTP Field */}
                <div className="ssp-form-field">
                  <div className="ssp-label-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <label className="ssp-field-label" htmlFor="otp">
                      {t('reg_otp_label')}
                    </label>
                    {otpExpirySeconds > 0 && (
                      <span style={{ fontSize: '0.78rem', color: '#c084fc', fontWeight: 600 }}>
                        {t('reg_otp_expires_in', { seconds: otpExpirySeconds })}
                      </span>
                    )}
                  </div>
                  <div className="ssp-input-input-wrap">
                    <Key className="ssp-field-left-icon" size={18} />
                    <input
                      id="otp"
                      name="otp"
                      type="text"
                      className="ssp-real-input"
                      placeholder={t('reg_otp_ph')}
                      maxLength={6}
                      value={otp}
                      onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      required
                    />
                  </div>
                </div>

                {/* Password Field */}
                <div className="ssp-form-field">
                  <label className="ssp-field-label" htmlFor="password">
                    {t('reg_password_label')}
                  </label>
                  <div className="ssp-input-input-wrap">
                    <Lock className="ssp-field-left-icon" size={18} />
                    <input
                      id="password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      className="ssp-real-input has-right-btn"
                      placeholder="••••••••"
                      value={formData.password}
                      onChange={handleChange}
                      required
                      minLength={8}
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

                {/* Confirm Password Field */}
                <div className="ssp-form-field">
                  <label className="ssp-field-label" htmlFor="confirmPassword">
                    {t('reg_confirm_password_label')}
                  </label>
                  <div className="ssp-input-input-wrap">
                    <Lock className="ssp-field-left-icon" size={18} />
                    <input
                      id="confirmPassword"
                      name="confirmPassword"
                      type={showConfirmPassword ? 'text' : 'password'}
                      className="ssp-real-input has-right-btn"
                      placeholder="••••••••"
                      value={formData.confirmPassword}
                      onChange={handleChange}
                      required
                      minLength={8}
                    />
                    <button
                      type="button"
                      className="ssp-btn-eye"
                      onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                      aria-label="Toggle confirm password visibility"
                    >
                      {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </div>

                {/* Submit Button */}
                <button
                  type="submit"
                  className="ssp-btn-login-submit"
                  disabled={isLoading}
                >
                  <span>{isLoading ? t('reg_submitting') : t('reg_submit')}</span>
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

              {/* Back to Login link */}
              <div className="ssp-login-prompt-link" style={{ marginTop: '1.5rem' }}>
                <span>{t('reg_has_account')} </span>
                <Link to="/login" className="ssp-link-login-redirect">
                  {t('reg_login_now')}
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

export default Register;
