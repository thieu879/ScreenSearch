import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Users,
  UserCheck,
  UserX,
  Wrench,
  UserPlus,
  Search,
  Lock,
  Unlock,
  ChevronLeft,
  ChevronRight,
  Filter,
  User as UserIcon,
  Mail,
  AtSign,
  Key,
} from 'lucide-react';
import { AdminSidebar } from '../../components/layout/Sidebar/AdminSidebar';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import { Modal } from '../../components/base/Modal/Modal';
import { Button } from '../../components/base/Button/Button';
import { Input } from '../../components/base/Input/Input';
import {
  adminListUsers,
  adminCreateUser,
  adminUpdateUser,
} from '../../api/auth';
import type { UserProfile } from '../../api/auth';
import { useAuth } from '../../contexts/AuthContext';
import './UserManagement.css';

export interface UserItem {
  id: string;
  name: string;
  username: string;
  email: string;
  role: 'Admin' | 'User';
  status: string;
  createdAt: string;
  initials: string;
  rawStatus: string;
}

export const UserManagement: React.FC = () => {
  const { user: currentUser } = useAuth();
  const { t, i18n } = useTranslation();
  const [searchTerm, setSearchTerm] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('All');
  const [users, setUsers] = useState<UserItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  // New user form state
  const [newUser, setNewUser] = useState({
    name: '',
    username: '',
    email: '',
    password: '',
    role: 'User' as 'Admin' | 'User',
    status: 'Hoạt động' as 'Hoạt động' | 'Ngoại tuyến',
  });

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 10;

  const mapProfileToUserItem = useCallback(
    (u: UserProfile): UserItem => {
      const name = u.full_name || u.username || u.email.split('@')[0];
      const initials =
        name
          .trim()
          .split(' ')
          .slice(-2)
          .map((n) => n[0]?.toUpperCase())
          .join('') || 'US';

      const locale = i18n.language === 'en' ? 'en-US' : 'vi-VN';
      const dateStr = u.created_at ? new Date(u.created_at).toLocaleDateString(locale) : '';

      return {
        id: u.user_id,
        name: name,
        username: u.username ? (u.username.startsWith('@') ? u.username : `@${u.username}`) : `@${u.email.split('@')[0]}`,
        email: u.email,
        role: (u.role === 'Admin' ? 'Admin' : 'User') as 'Admin' | 'User',
        status: u.status === 'active' ? t('status_active') : t('status_offline'),
        createdAt: dateStr,
        initials: initials,
        rawStatus: u.status,
      };
    },
    [i18n.language, t]
  );

  const loadUsers = useCallback(async () => {
    try {
      const data = await adminListUsers();
      // Lọc không hiển thị tài khoản Admin trong trang quản lý người dùng
      const regularUsers = data.filter((u) => u.role !== 'Admin');
      setUsers(regularUsers.map(mapProfileToUserItem));
    } catch (err: unknown) {
      console.error('Failed to load users:', err);
      const message = err instanceof Error ? err.message : 'Không thể tải danh sách người dùng.';
      setErrorMsg(message);
    } finally {
      setIsLoading(false);
    }
  }, [mapProfileToUserItem]);

  useEffect(() => {
    let ignore = false;
    adminListUsers()
      .then((data) => {
        if (!ignore) {
          const regularUsers = data.filter((u) => u.role !== 'Admin');
          setUsers(regularUsers.map(mapProfileToUserItem));
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          console.error('Failed to load users:', err);
          const message = err instanceof Error ? err.message : 'Không thể tải danh sách người dùng.';
          setErrorMsg(message);
          setIsLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [mapProfileToUserItem]);

  // Filtered users calculation
  const filteredUsers = useMemo(() => {
    return users.filter((userItem) => {
      const matchesSearch =
        userItem.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        userItem.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
        userItem.username.toLowerCase().includes(searchTerm.toLowerCase());

      const matchesRole = roleFilter === 'All' || userItem.role === roleFilter;

      return matchesSearch && matchesRole;
    });
  }, [users, searchTerm, roleFilter]);

  // Real-time metrics
  const totalCount = users.length;
  const activeCount = users.filter((u) => u.status === 'Hoạt động').length;
  const offlineCount = users.filter((u) => u.status === 'Ngoại tuyến').length;
  const regularUserCount = users.filter((u) => u.role === 'User').length;

  // Pagination bounds
  const totalPages = Math.max(1, Math.ceil(filteredUsers.length / pageSize));
  const currentUsers = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredUsers.slice(start, start + pageSize);
  }, [filteredUsers, currentPage, pageSize]);

  // Actions
  const handleAddUserSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUser.email.trim() || !newUser.password.trim()) return;

    try {
      await adminCreateUser({
        email: newUser.email.trim(),
        password: newUser.password.trim(),
        full_name: newUser.name.trim() || undefined,
        username: newUser.username.replace(/^@/, '').trim() || undefined,
        role: newUser.role,
        status: newUser.status === 'Hoạt động' ? 'active' : 'disabled',
      });

      setNewUser({
        name: '',
        username: '',
        email: '',
        password: '',
        role: 'User',
        status: 'Hoạt động',
      });
      setIsAddModalOpen(false);
      await loadUsers();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Không thể tạo người dùng';
      alert(message);
    }
  };

  const handleToggleStatus = async (userItem: UserItem) => {
    try {
      const newStatus = userItem.rawStatus === 'active' ? 'disabled' : 'active';
      await adminUpdateUser(userItem.id, { status: newStatus });
      await loadUsers();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Cập nhật trạng thái thất bại.';
      alert(message);
    }
  };

  return (
    <div className="ssp-user-layout">
      {/* Sidebar navigation */}
      <AdminSidebar
        activeTab="users"
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Wrapper */}
      <div className="ssp-user-main-wrapper">
        {/* Top App Bar */}
        <TopBar
          pageTitle={t('user_mgmt_title')}
          roleBadge="System Admin"
          userName={currentUser?.full_name || currentUser?.username || currentUser?.email || 'Quản trị viên'}
          userRole={currentUser?.role === 'Admin' ? t('system_admin') : t('regular_user')}
          onToggleMenu={() => setIsMobileMenuOpen((prev) => !prev)}
        />

        {/* Main Canvas */}
        <main className="ssp-user-canvas">
          {/* Header Action Row */}
          <div className="ssp-header-actions-row">
            <div>
              <p className="ssp-page-description">
                {t('user_mgmt_desc')}
              </p>
            </div>
            <button
              type="button"
              className="ssp-btn-add-user"
              onClick={() => setIsAddModalOpen(true)}
            >
              <UserPlus size={18} />
              <span>{t('user_mgmt_add_btn')}</span>
            </button>
          </div>

          {errorMsg && (
            <div style={{ padding: '12px 16px', borderRadius: '8px', backgroundColor: '#fef2f2', color: '#dc2626', marginBottom: '16px' }}>
              {errorMsg}
            </div>
          )}

          {/* Stats Bento Grid */}
          <div className="ssp-stats-grid">
            <div className="ssp-stat-card">
              <div className="ssp-stat-icon-wrap total">
                <Users size={22} />
              </div>
              <div>
                <p className="ssp-stat-label">{t('user_mgmt_total')}</p>
                <p className="ssp-stat-val">{isLoading ? '...' : totalCount}</p>
              </div>
            </div>

            <div className="ssp-stat-card">
              <div className="ssp-stat-icon-wrap active">
                <UserCheck size={22} />
              </div>
              <div>
                <p className="ssp-stat-label">{t('user_mgmt_active')}</p>
                <p className="ssp-stat-val">{isLoading ? '...' : activeCount}</p>
              </div>
            </div>

            <div className="ssp-stat-card">
              <div className="ssp-stat-icon-wrap offline">
                <UserX size={22} />
              </div>
              <div>
                <p className="ssp-stat-label">{t('user_mgmt_offline')}</p>
                <p className="ssp-stat-val">{isLoading ? '...' : offlineCount}</p>
              </div>
            </div>

            <div className="ssp-stat-card">
              <div className="ssp-stat-icon-wrap admin">
                <Wrench size={22} />
              </div>
              <div>
                <p className="ssp-stat-label">{t('user_mgmt_regular')}</p>
                <p className="ssp-stat-val">{isLoading ? '...' : regularUserCount}</p>
              </div>
            </div>
          </div>

          {/* Filter & Search Bar */}
          <div className="ssp-controls-bar">
            <div className="ssp-search-box-large">
              <Search size={18} className="ssp-search-icon" />
              <input
                type="text"
                placeholder={t('user_mgmt_search_placeholder')}
                value={searchTerm}
                onChange={(e) => {
                  setSearchTerm(e.target.value);
                  setCurrentPage(1);
                }}
              />
            </div>

            <div className="ssp-filter-group">
              <Filter size={16} style={{ color: 'var(--ssp-on-surface-variant)' }} />
              <select
                className="ssp-select-filter"
                value={roleFilter}
                onChange={(e) => {
                  setRoleFilter(e.target.value);
                  setCurrentPage(1);
                }}
              >
                <option value="All">{t('user_mgmt_filter_all')}</option>
                <option value="User">{t('user_mgmt_filter_user')}</option>
              </select>
            </div>
          </div>

          {/* User Data Table Card */}
          <div className="ssp-table-card">
            <div className="ssp-table-wrapper">
              <table className="ssp-user-table">
                <thead>
                  <tr>
                    <th>{t('user_mgmt_th_name')}</th>
                    <th>{t('user_mgmt_th_email')}</th>
                    <th>{t('user_mgmt_th_role')}</th>
                    <th style={{ textAlign: 'center' }}>{t('user_mgmt_th_status')}</th>
                    <th>{t('user_mgmt_th_created')}</th>
                    <th style={{ textAlign: 'right' }}>{t('user_mgmt_th_actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {isLoading ? (
                    <tr>
                      <td colSpan={6} style={{ textAlign: 'center', padding: '32px', color: 'var(--ssp-on-surface-variant)' }}>
                        {t('loading_users_db')}
                      </td>
                    </tr>
                  ) : currentUsers.length === 0 ? (
                    <tr>
                      <td colSpan={6} style={{ textAlign: 'center', padding: '32px', color: 'var(--ssp-on-surface-variant)' }}>
                        {t('no_users_found')}
                      </td>
                    </tr>
                  ) : (
                    currentUsers.map((userItem) => (
                      <tr key={userItem.id}>
                        <td>
                          <div className="ssp-user-info-cell">
                            <div className="ssp-user-avatar-badge">
                              {userItem.initials}
                            </div>
                            <div>
                              <div className="ssp-user-full-name">{userItem.name}</div>
                              <div className="ssp-user-username">{userItem.username}</div>
                            </div>
                          </div>
                        </td>
                        <td>{userItem.email}</td>
                        <td>
                          <span className={`ssp-role-pill role-${userItem.role.toLowerCase()}`}>{userItem.role}</span>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <span
                            className={`ssp-status-chip ${
                              userItem.rawStatus === 'active' ? 'active' : 'offline'
                            }`}
                          >
                            <span className="ssp-status-chip-dot" />
                            {userItem.status}
                          </span>
                        </td>
                        <td style={{ color: 'var(--ssp-on-surface-variant)' }}>
                          {userItem.createdAt}
                        </td>
                        <td style={{ textAlign: 'right' }} className="ssp-action-cell">
                          <button
                            type="button"
                            className={`ssp-action-btn-icon ${
                              userItem.rawStatus === 'active' ? 'lock-btn' : 'unlock-btn'
                            }`}
                            title={
                              userItem.rawStatus === 'active'
                                ? t('disable_user_title')
                                : t('enable_user_title')
                            }
                            onClick={() => handleToggleStatus(userItem)}
                          >
                            {userItem.rawStatus === 'active' ? (
                              <Lock size={18} />
                            ) : (
                              <Unlock size={18} />
                            )}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            <div className="ssp-table-pagination">
              <span className="ssp-pagination-info">
                {t('user_pagination_showing', {
                  start: filteredUsers.length > 0 ? (currentPage - 1) * pageSize + 1 : 0,
                  end: Math.min(currentPage * pageSize, filteredUsers.length),
                  total: filteredUsers.length
                })}
              </span>
              <div className="ssp-pagination-controls">
                <button
                  type="button"
                  className="ssp-btn-page-step"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
                  title={t('prev_page')}
                >
                  <ChevronLeft size={18} />
                </button>
                {Array.from({ length: totalPages }).map((_, index) => {
                  const pageNum = index + 1;
                  return (
                    <button
                      key={pageNum}
                      type="button"
                      className={`ssp-btn-page-num ${
                        currentPage === pageNum ? 'active' : ''
                      }`}
                      onClick={() => setCurrentPage(pageNum)}
                    >
                      {pageNum}
                    </button>
                  );
                })}
                <button
                  type="button"
                  className="ssp-btn-page-step"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage((prev) => Math.min(totalPages, prev + 1))}
                  title={t('next_page')}
                >
                  <ChevronRight size={18} />
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* Add User Modal */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="Thêm người dùng mới"
        size="md"
      >
        <form onSubmit={handleAddUserSubmit} className="ssp-form-grid">
          <Input
            label="Họ và tên"
            placeholder="Ví dụ: Nguyễn Văn A"
            prefixIcon={<UserIcon size={16} />}
            value={newUser.name}
            onChange={(e) => setNewUser({ ...newUser, name: e.target.value })}
            fullWidth
          />

          <Input
            label="Username"
            placeholder="@nguyenvana"
            prefixIcon={<AtSign size={16} />}
            value={newUser.username}
            onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
            fullWidth
          />

          <Input
            label="Email *"
            type="email"
            placeholder="nguyenvana@ssp.com"
            prefixIcon={<Mail size={16} />}
            value={newUser.email}
            onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
            required
            fullWidth
          />

          <Input
            label={t('lbl_password')}
            type="password"
            placeholder="Minimum 6 characters"
            prefixIcon={<Key size={16} />}
            value={newUser.password}
            onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
            required
            fullWidth
          />

          <div className="ssp-form-group">
            <label className="ssp-form-label">
              <Wrench size={15} className="ssp-label-icon" />
              <span>{t('user_mgmt_th_role')}</span>
            </label>
            <select
              className="ssp-form-select"
              value={newUser.role}
              onChange={(e) =>
                setNewUser({
                  ...newUser,
                  role: e.target.value as 'Admin' | 'User',
                })
              }
            >
              <option value="User">{t('user_mgmt_filter_user')}</option>
              <option value="Admin">{t('system_admin')}</option>
            </select>
          </div>

          <div className="ssp-modal-footer">
            <Button
              variant="ghost"
              type="button"
              onClick={() => setIsAddModalOpen(false)}
            >
              {t('btn_cancel')}
            </Button>
            <Button
              variant="primary"
              type="submit"
              leftIcon={<UserPlus size={16} />}
            >
              {t('btn_confirm_add')}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};

export default UserManagement;

