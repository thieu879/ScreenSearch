import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  User, Mail, Shield, Calendar, Edit3, Save, X, Lock, Eye, EyeOff, ArrowLeft, Check,
} from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { updateProfile, changePassword } from '../../api/auth';
import { useToast } from '../../components/base/Toast/useToast';
import { ToastContainer } from '../../components/base/Toast/Toast';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import './Profile.css';

const Profile: React.FC = () => {
  const navigate = useNavigate();
  const { user, refreshUser } = useAuth();
  const { t, i18n } = useTranslation();
  const { messages, addToast, dismiss } = useToast();

  const [isEditing, setIsEditing] = useState(false);
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [showCurrentPw, setShowCurrentPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);

  const [editData, setEditData] = useState({
    full_name: user?.full_name || '',
    username: user?.username || '',
  });

  const [pwData, setPwData] = useState({
    current_password: '',
    new_password: '',
    confirm_password: '',
  });

  if (!user) return null;

  const handleSaveProfile = async () => {
    setIsSaving(true);
    try {
      await updateProfile({
        full_name: editData.full_name || undefined,
        username: editData.username || undefined,
      });
      await refreshUser();
      setIsEditing(false);
      addToast('success', t('btn_confirm'), t('profile_title'));
    } catch (err: unknown) {
      const error = err as Error;
      addToast('error', t('toast_error'), error.message || t('profile_update_failed'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleChangePassword = async () => {
    if (pwData.new_password.length < 8) {
      addToast('error', t('toast_error'), t('profile_password_short'));
      return;
    }
    if (pwData.new_password !== pwData.confirm_password) {
      addToast('error', t('toast_error'), t('profile_password_mismatch'));
      return;
    }

    setIsSaving(true);
    try {
      const res = await changePassword(pwData.current_password, pwData.new_password, pwData.confirm_password);
      addToast('success', t('btn_confirm'), res.message);
      setIsChangingPassword(false);
      setPwData({ current_password: '', new_password: '', confirm_password: '' });
    } catch (err: unknown) {
      const error = err as Error;
      addToast('error', t('toast_error'), error.message || t('profile_password_failed'));
    } finally {
      setIsSaving(false);
    }
  };

  const avatarInitial = (user.full_name || user.email || '?')[0].toUpperCase();
  const dateLocale = i18n.language === 'en' ? 'en-US' : 'vi-VN';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', backgroundColor: 'var(--bg-primary, #f4f7f8)' }}>
      <TopBar />
      <div className="profile-page" style={{ flex: 1 }}>
        <div className="profile-container">
          {/* Back button */}
          <button type="button" className="profile-back-btn" onClick={() => navigate(-1)}>
            <ArrowLeft size={18} />
            <span>{t('btn_back_prev')}</span>
          </button>

        {/* Profile Header Card */}
        <div className="profile-header-card">
          <div className="profile-avatar-lg">
            {user.avatar ? (
              <img src={user.avatar} alt="Avatar" className="profile-avatar-img" />
            ) : (
              <span className="profile-avatar-initial">{avatarInitial}</span>
            )}
          </div>
          <div className="profile-header-info">
            <h1 className="profile-name">{user.full_name || user.email}</h1>
            <span className={`profile-role-badge ${user.role === 'Admin' ? 'admin' : 'user'}`}>
              <Shield size={14} />
              {user.role === 'Admin' ? t('system_admin') : t('regular_user')}
            </span>
            <p className="profile-email-sub">{user.email}</p>
          </div>
        </div>

        {/* Profile Details */}
        <div className="profile-section">
          <div className="profile-section-header">
            <h2>{t('profile_title')}</h2>
            {!isEditing ? (
              <button type="button" className="profile-edit-btn" onClick={() => {
                setEditData({ full_name: user.full_name || '', username: user.username || '' });
                setIsEditing(true);
              }}>
                <Edit3 size={16} />
                <span>{t('profile_edit')}</span>
              </button>
            ) : (
              <div className="profile-edit-actions">
                <button type="button" className="profile-save-btn" onClick={handleSaveProfile} disabled={isSaving}>
                  <Save size={16} />
                  <span>{isSaving ? t('profile_saving') : t('profile_save')}</span>
                </button>
                <button type="button" className="profile-cancel-btn" onClick={() => setIsEditing(false)}>
                  <X size={16} />
                  <span>{t('btn_cancel')}</span>
                </button>
              </div>
            )}
          </div>

          <div className="profile-fields">
            <div className="profile-field">
              <div className="profile-field-icon"><User size={18} /></div>
              <div className="profile-field-content">
                <span className="profile-field-label">{t('profile_fullname')}</span>
                {isEditing ? (
                  <input
                    type="text"
                    className="profile-field-input"
                    value={editData.full_name}
                    onChange={(e) => setEditData(prev => ({ ...prev, full_name: e.target.value }))}
                    placeholder={t('lbl_fullname')}
                  />
                ) : (
                  <span className="profile-field-value">{user.full_name || '—'}</span>
                )}
              </div>
            </div>

            <div className="profile-field">
              <div className="profile-field-icon"><User size={18} /></div>
              <div className="profile-field-content">
                <span className="profile-field-label">{t('profile_username')}</span>
                {isEditing ? (
                  <input
                    type="text"
                    className="profile-field-input"
                    value={editData.username}
                    onChange={(e) => setEditData(prev => ({ ...prev, username: e.target.value }))}
                    placeholder={t('lbl_username')}
                    minLength={3}
                    maxLength={50}
                  />
                ) : (
                  <span className="profile-field-value">{user.username || '—'}</span>
                )}
              </div>
            </div>

            <div className="profile-field">
              <div className="profile-field-icon"><Mail size={18} /></div>
              <div className="profile-field-content">
                <span className="profile-field-label">{t('profile_email')}</span>
                <span className="profile-field-value">{user.email}</span>
              </div>
            </div>

            <div className="profile-field">
              <div className="profile-field-icon"><Shield size={18} /></div>
              <div className="profile-field-content">
                <span className="profile-field-label">{t('profile_role')}</span>
                <span className="profile-field-value">{user.role}</span>
              </div>
            </div>

            <div className="profile-field">
              <div className="profile-field-icon"><Check size={18} /></div>
              <div className="profile-field-content">
                <span className="profile-field-label">{t('profile_status')}</span>
                <span className="profile-field-value profile-status-active">{user.status}</span>
              </div>
            </div>

            <div className="profile-field">
              <div className="profile-field-icon"><Calendar size={18} /></div>
              <div className="profile-field-content">
                <span className="profile-field-label">{t('profile_created_at')}</span>
                <span className="profile-field-value">
                  {new Date(user.created_at).toLocaleDateString(dateLocale, {
                    year: 'numeric', month: 'long', day: 'numeric',
                  })}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Change Password Section */}
        <div className="profile-section">
          <div className="profile-section-header">
            <h2>{t('profile_change_pw')}</h2>
            {!isChangingPassword && (
              <button type="button" className="profile-edit-btn" onClick={() => setIsChangingPassword(true)}>
                <Lock size={16} />
                <span>{t('profile_change_pw')}</span>
              </button>
            )}
          </div>

          {isChangingPassword && (
            <div className="profile-password-form">
              <div className="profile-pw-field">
                <label>{t('current_password')}</label>
                <div className="profile-pw-input-wrap">
                  <input
                    type={showCurrentPw ? 'text' : 'password'}
                    value={pwData.current_password}
                    onChange={(e) => setPwData(prev => ({ ...prev, current_password: e.target.value }))}
                    placeholder="••••••••"
                  />
                  <button type="button" className="profile-pw-eye" onClick={() => setShowCurrentPw(!showCurrentPw)}>
                    {showCurrentPw ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="profile-pw-field">
                <label>{t('new_password')}</label>
                <div className="profile-pw-input-wrap">
                  <input
                    type={showNewPw ? 'text' : 'password'}
                    value={pwData.new_password}
                    onChange={(e) => setPwData(prev => ({ ...prev, new_password: e.target.value }))}
                    placeholder="••••••••"
                    minLength={8}
                  />
                  <button type="button" className="profile-pw-eye" onClick={() => setShowNewPw(!showNewPw)}>
                    {showNewPw ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="profile-pw-field">
                <label>{t('confirm_new_password')}</label>
                <div className="profile-pw-input-wrap">
                  <input
                    type="password"
                    value={pwData.confirm_password}
                    onChange={(e) => setPwData(prev => ({ ...prev, confirm_password: e.target.value }))}
                    placeholder="••••••••"
                    minLength={8}
                  />
                </div>
              </div>

              <div className="profile-pw-actions">
                <button type="button" className="profile-save-btn" onClick={handleChangePassword} disabled={isSaving}>
                  <Save size={16} />
                  <span>{isSaving ? t('profile_saving') : t('profile_change_pw')}</span>
                </button>
                <button type="button" className="profile-cancel-btn" onClick={() => {
                  setIsChangingPassword(false);
                  setPwData({ current_password: '', new_password: '', confirm_password: '' });
                }}>
                  <X size={16} />
                  <span>{t('btn_cancel')}</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <ToastContainer messages={messages} onDismiss={dismiss} />
    </div>
    </div>
  );
};

export default Profile;
