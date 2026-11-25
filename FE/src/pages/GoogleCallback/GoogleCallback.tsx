import React, { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../contexts/AuthContext';
import { useToast } from '../../components/base/Toast/useToast';
import { ToastContainer } from '../../components/base/Toast/Toast';

export const GoogleCallback: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { loginWithGoogle } = useAuth();
  const { messages, addToast, dismiss } = useToast();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    const error = urlParams.get('error');

    if (error) {
      addToast('error', t('google_failed_title'), t('google_error_from', { error }));
      setTimeout(() => navigate('/login'), 2000);
      return;
    }

    if (!code) {
      addToast('error', t('google_failed_title'), t('google_no_code'));
      setTimeout(() => navigate('/login'), 2000);
      return;
    }

    const redirectUri = `${window.location.origin}/auth/google/callback`;

    loginWithGoogle(code, undefined, redirectUri)
      .then((user) => {
        addToast('success', t('google_ok_title'), t('google_ok_desc'));
        setTimeout(() => {
          if (user.role === 'Admin') {
            navigate('/admin');
          } else {
            navigate('/search');
          }
        }, 700);
      })
      .catch((err: unknown) => {
        const error = err as Error;
        addToast('error', t('google_failed_title'), error.message || t('google_failed_desc'));
        setTimeout(() => navigate('/login'), 2500);
      });
    // `t` is a real dependency now, and safe to add here where it would not be everywhere: the
    // whole body is behind the `processed` ref, so a language change re-runs the effect and it
    // returns immediately rather than exchanging the OAuth code a second time.
  }, [loginWithGoogle, navigate, addToast, t]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#0a0a0f', color: '#f1f5f9' }}>
      <div style={{ color: '#8b5cf6', fontSize: '1.4rem', fontWeight: 600, marginBottom: '0.5rem' }}>
        {t('google_verifying')}
      </div>
      <p style={{ color: '#94a3b8', fontSize: '0.9rem' }}>{t('google_please_wait')}</p>
      <ToastContainer messages={messages} onDismiss={dismiss} />
    </div>
  );
};

export default GoogleCallback;
