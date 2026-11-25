import React, { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Mail,
  Lock,
  Key,
  Eye,
  EyeOff,
  Sparkles,
  ShieldCheck,
  Cpu,
  Layers,
  ArrowLeft,
  ArrowRight,
  Activity,
} from 'lucide-react';
import { useToast } from '../../components/base/Toast/useToast';
import { ToastContainer } from '../../components/base/Toast/Toast';
import { fetchCorpusStatus } from '../../api/client';
import { authSendOtp, authResetPassword } from '../../api/auth';
import type { CorpusStatus } from '../../types/api';

import '../Login/Login.css';
import './ForgotPassword.css';

export const ForgotPassword: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { messages, addToast, dismiss } = useToast();

  const [isLoading, setIsLoading] = useState(false);
  const [corpus, setCorpus] = useState<CorpusStatus | null>(null);
  const [email, setEmail] = useState('');
  
  // OTP Reset password states
  const [isResetMode, setIsResetMode] = useState(false);
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // Timers
  const [resendCooldown, setResendCooldown] = useState(0);
  const [otpExpirySeconds, setOtpExpirySeconds] = useState(0);

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

  const handleSendOtp = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!email || !email.includes('@')) {
      addToast('error', t('forgot_email_invalid_title'), t('forgot_email_invalid_desc'));
      return;
    }

    setIsLoading(true);
    addToast('info', t('forgot_btn_sending'), t('forgot_connecting'));

    try {
      const res = await authSendOtp(email, 'forgot_password');
      setIsResetMode(true);
      setResendCooldown(60);
      setOtpExpirySeconds(300);
      addToast('success', t('forgot_otp_sent_title'), res.message || t('forgot_otp_sent_desc'));
    } catch (err: unknown) {
      const error = err as Error;
      addToast('error', t('forgot_otp_failed_title'), error.message || t('forgot_otp_failed_desc'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!otp || otp.length !== 6) {
      addToast('error', t('forgot_otp_invalid_title'), t('forgot_otp_invalid_desc'));
      return;
    }

    if (newPassword.length < 8) {
      addToast('error', t('forgot_weak_title'), t('forgot_weak_desc'));
      return;
    }

    if (newPassword !== confirmPassword) {
      addToast('error', t('forgot_mismatch_title'), t('forgot_mismatch_desc'));
      return;
    }

    setIsLoading(true);
    addToast('info', t('forgot_btn_resetting'), t('forgot_saving'));

    try {
      await authResetPassword(email, otp, newPassword, confirmPassword);
      addToast('success', t('forgot_reset_ok_title'), t('forgot_reset_ok_desc'));
      setTimeout(() => {
        navigate('/login');
      }, 1200);
    } catch (err: unknown) {
      const error = err as Error;
      addToast('error', t('forgot_reset_failed_title'), error.message || t('forgot_reset_failed_desc'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="ssp-login-split-layout">
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
            {t('forgot_hero_title_1')} <br />
            <span className="ssp-gradient-text">{t('forgot_hero_title_2')}</span>
          </h1>

          <p className="ssp-hero-description">
            {t('forgot_hero_desc')}
          </p>

          {/* Counts, not claims */}
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
            {/* Back button link */}
            <Link to="/login" className="ssp-btn-back-login">
              <ArrowLeft size={16} />
              <span>{t('forgot_back_login')}</span>
            </Link>

            {/* Brand Logo & Header */}
            <div className="ssp-form-header">
              <div className="ssp-brand-logo-ring">
                <span className="ssp-brand-logo-text">SSP</span>
              </div>
              <h2 className="ssp-form-title">
                {!isResetMode ? t('forgot_form_title') : t('forgot_reset_form_title')}
              </h2>
              <p className="ssp-form-subtitle">
                {!isResetMode
                  ? t('forgot_form_subtitle')
                  : t('forgot_reset_form_subtitle')}
              </p>
            </div>

            {/* Forgot Password Form */}
            <form className="ssp-form-body" onSubmit={!isResetMode ? handleSendOtp : handleResetPassword}>
              {!isResetMode ? (
                /* Step 1: Email Field */
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
              ) : (
                /* Step 2: Reset Password & OTP Fields */
                <>
                  <div className="ssp-form-field">
                    <label className="ssp-field-label" htmlFor="email">
                      {t('login_label_email')}
                    </label>
                    <div className="ssp-input-input-wrap">
                      <Mail className="ssp-field-left-icon" size={18} />
                      <input
                        id="email"
                        type="email"
                        className="ssp-real-input"
                        value={email}
                        readOnly
                        style={{ opacity: 0.7, cursor: 'not-allowed' }}
                      />
                    </div>
                  </div>

                  {/* OTP Field with Countdown */}
                  <div className="ssp-form-field">
                    <div className="ssp-label-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label className="ssp-field-label" htmlFor="otp">
                        {t('reg_otp_label')}
                      </label>
                      {otpExpirySeconds > 0 && (
                        <span style={{ fontSize: '0.78rem', color: '#c084fc', fontWeight: 600 }}>
                          {t('reg_otp_expires_in', { seconds: Math.floor(otpExpirySeconds / 60).toString().padStart(2, '0') + ':' + (otpExpirySeconds % 60).toString().padStart(2, '0') })}
                        </span>
                      )}
                    </div>
                    <div className="ssp-input-input-wrap">
                      <Key className="ssp-field-left-icon" size={18} />
                      <input
                        id="otp"
                        name="otp"
                        type="text"
                        className="ssp-real-input has-right-btn"
                        placeholder="123456"
                        maxLength={6}
                        value={otp}
                        onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                        required
                      />
                      <button
                        type="button"
                        onClick={() => handleSendOtp()}
                        disabled={isLoading || resendCooldown > 0}
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
                          cursor: isLoading || resendCooldown > 0 ? 'not-allowed' : 'pointer',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {resendCooldown > 0 ? t('reg_resend_otp_in', { seconds: resendCooldown }) : t('reg_send_otp')}
                      </button>
                    </div>
                  </div>

                  {/* New Password */}
                  <div className="ssp-form-field">
                    <label className="ssp-field-label" htmlFor="newPassword">
                      {t('forgot_new_pw_label')}
                    </label>
                    <div className="ssp-input-input-wrap">
                      <Lock className="ssp-field-left-icon" size={18} />
                      <input
                        id="newPassword"
                        name="newPassword"
                        type={showNewPassword ? 'text' : 'password'}
                        className="ssp-real-input has-right-btn"
                        placeholder="••••••••"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        required
                        minLength={8}
                      />
                      <button
                        type="button"
                        className="ssp-btn-eye"
                        onClick={() => setShowNewPassword(!showNewPassword)}
                        aria-label="Toggle new password visibility"
                      >
                        {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                  </div>

                  {/* Confirm New Password */}
                  <div className="ssp-form-field">
                    <label className="ssp-field-label" htmlFor="confirmPassword">
                      {t('forgot_confirm_pw_label')}
                    </label>
                    <div className="ssp-input-input-wrap">
                      <Lock className="ssp-field-left-icon" size={18} />
                      <input
                        id="confirmPassword"
                        name="confirmPassword"
                        type={showConfirmPassword ? 'text' : 'password'}
                        className="ssp-real-input has-right-btn"
                        placeholder="••••••••"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
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
                </>
              )}

              {/* Submit Button */}
              <button
                type="submit"
                className="ssp-btn-login-submit"
                disabled={isLoading}
              >
                <span>
                  {isLoading
                    ? t('forgot_btn_sending')
                    : !isResetMode
                    ? t('forgot_btn_send_otp')
                    : t('forgot_btn_reset_pw')}
                </span>
                <ArrowRight size={18} />
              </button>
            </form>

            <div className="ssp-form-security-footer">
              <ShieldCheck size={14} />
              <span>{t('login_security_footer')}</span>
            </div>
          </div>
        </main>
      </div>

      <ToastContainer messages={messages} onDismiss={dismiss} />
    </div>
  );
};

export default ForgotPassword;
