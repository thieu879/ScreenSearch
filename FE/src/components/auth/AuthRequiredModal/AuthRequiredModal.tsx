import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Lock, LogIn, UserPlus, Sparkles } from 'lucide-react';
import './AuthRequiredModal.css';

interface AuthRequiredModalProps {
  isOpen: boolean;
  onClose?: () => void;
}

export const AuthRequiredModal: React.FC<AuthRequiredModalProps> = ({ isOpen, onClose }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();

  if (!isOpen) return null;

  const handleLogin = () => {
    navigate('/login', { state: { from: location, warning: t('login_toast_req_login') } });
  };

  const handleRegister = () => {
    navigate('/register');
  };

  const handleClose = () => {
    if (onClose) {
      onClose();
    } else {
      handleLogin();
    }
  };

  return (
    <div className="ssp-auth-modal-backdrop" onClick={handleClose}>
      <div className="ssp-auth-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Glow Header Accent */}
        <div className="ssp-auth-modal-glow" />

        {/* Icon */}
        <div className="ssp-auth-modal-icon-wrap">
          <Lock size={32} className="ssp-auth-modal-icon" />
        </div>

        {/* Title & Desc */}
        <h3 className="ssp-auth-modal-title">{t('auth_modal_title')}</h3>
        <p className="ssp-auth-modal-desc">
          {t('auth_modal_desc')}
        </p>

        {/* Action Buttons */}
        <div className="ssp-auth-modal-actions">
          <button type="button" className="ssp-auth-btn-primary" onClick={handleLogin}>
            <LogIn size={18} />
            <span>{t('auth_modal_btn_login')}</span>
          </button>
          <button type="button" className="ssp-auth-btn-secondary" onClick={handleRegister}>
            <UserPlus size={18} />
            <span>{t('auth_modal_btn_register')}</span>
          </button>
        </div>

        {/* Footer info */}
        <div className="ssp-auth-modal-footer">
          <Sparkles size={14} />
          <span>Semantic Search Platform</span>
        </div>
      </div>
    </div>
  );
};

export default AuthRequiredModal;
