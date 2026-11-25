import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Database,
  Image as ImageIcon,
  Network,
  Users,
  TrendingUp,
  RefreshCw,
} from 'lucide-react';
import { AdminSidebar } from '../../components/layout/Sidebar/AdminSidebar';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import { Badge } from '../../components/base/Badge/Badge';
import { adminGetStats } from '../../api/auth';
import type { SystemStatsResponse } from '../../api/auth';
import { useAuth } from '../../contexts/AuthContext';
import './AdminDashboard.css';

export const AdminDashboard: React.FC = () => {
  const { user: currentUser } = useAuth();
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState('dashboard');
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [stats, setStats] = useState<SystemStatsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>('');

  const loadStats = useCallback(async () => {
    try {
      const data = await adminGetStats();
      setStats(data);
      const now = new Date();
      setLastUpdated(now.toLocaleTimeString('vi-VN') + ', ' + now.toLocaleDateString('vi-VN'));
    } catch (err) {
      console.error('Failed to load admin stats:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleRefresh = useCallback(() => {
    setIsLoading(true);
    loadStats();
  }, [loadStats]);

  useEffect(() => {
    let ignore = false;
    adminGetStats()
      .then((data) => {
        if (!ignore) {
          setStats(data);
          const now = new Date();
          setLastUpdated(now.toLocaleTimeString('vi-VN') + ', ' + now.toLocaleDateString('vi-VN'));
          setIsLoading(false);
        }
      })
      .catch((err) => {
        if (!ignore) {
          console.error('Failed to load admin stats:', err);
          setIsLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, []);

  const formatNumber = (num: number): string => {
    if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M';
    if (num >= 1_000) return (num / 1_000).toFixed(1) + 'k';
    return num.toString();
  };

  return (
    <div className="ssp-admin-layout">
      {/* Side Navigation Bar for Admin Role */}
      <AdminSidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Wrapper */}
      <div className="ssp-admin-main-wrapper">
        {/* Top Header Bar with Admin Credentials */}
        <TopBar
          pageTitle={t('admin_db_title')}
          roleBadge="System Admin"
          userName={currentUser?.full_name || currentUser?.username || currentUser?.email || 'Quản trị viên'}
          userRole={currentUser?.role === 'Admin' ? t('system_admin') : t('regular_user')}
          onToggleMenu={() => setIsMobileMenuOpen((prev) => !prev)}
        />

        {/* Main Content Canvas */}
        <main className="ssp-admin-canvas">
          {/* Key Metrics Bento Grid */}
          <div className="ssp-metrics-grid">
            {/* Metric Card 1: Datasets */}
            <div className="ssp-metric-card">
              <div className="ssp-metric-header">
                <span className="ssp-metric-label">Corpus / Dataset</span>
                <div className="ssp-metric-icon-badge dataset">
                  <Database size={18} />
                </div>
              </div>
              <div className="ssp-metric-body">
                <span className="ssp-metric-val">1</span>
                <span className="ssp-metric-trend">
                  nuScenes <TrendingUp size={14} />
                </span>
              </div>
              <p className="ssp-metric-hint">{t('metric_dataset_hint')}</p>
            </div>

            {/* Metric Card 2: Frames */}
            <div className="ssp-metric-card">
              <div className="ssp-metric-header">
                <span className="ssp-metric-label">Frames</span>
                <div className="ssp-metric-icon-badge frames">
                  <ImageIcon size={18} />
                </div>
              </div>
              <div className="ssp-metric-body">
                <span className="ssp-metric-val">
                  {isLoading ? '...' : formatNumber(stats?.total_frames ?? 0)}
                </span>
                <span className="ssp-metric-trend">
                  +100% <TrendingUp size={14} />
                </span>
              </div>
              <p className="ssp-metric-hint">{t('metric_frames_hint')}</p>
            </div>

            {/* Metric Card 3: Embedding */}
            <div className="ssp-metric-card">
              <div className="ssp-metric-header">
                <span className="ssp-metric-label">Embedding</span>
                <div className="ssp-metric-icon-badge embedding">
                  <Network size={18} />
                </div>
              </div>
              <div className="ssp-metric-body">
                <span className="ssp-metric-val">
                  {isLoading ? '...' : formatNumber(stats?.total_embeddings ?? 0)}
                </span>
                <span className="ssp-metric-hint" style={{ fontWeight: 700 }}>
                  100% Ready
                </span>
              </div>
              <p className="ssp-metric-hint">SigLIP2 & MiniLM vectors</p>
            </div>

            {/* Metric Card 4: Users */}
            <div className="ssp-metric-card">
              <div className="ssp-metric-header">
                <span className="ssp-metric-label">{t('stat_total_users')}</span>
                <div className="ssp-metric-icon-badge users">
                  <Users size={18} />
                </div>
              </div>
              <div className="ssp-metric-body">
                <span className="ssp-metric-val">
                  {isLoading ? '...' : stats?.total_users ?? 0}
                </span>
                <span className="ssp-metric-hint" style={{ fontWeight: 700 }}>
                  {stats?.active_users ?? 0} Active
                </span>
              </div>
              <p className="ssp-metric-hint">{t('metric_users_hint')}</p>
            </div>
          </div>

          {/* Two Column Grid */}
          <div className="ssp-dashboard-grid">
            {/* Indexing Status Table */}
            <div className="ssp-table-card" id="dataset">
              <div className="ssp-card-top">
                <h3 className="ssp-card-title">{t('indexing_status')}</h3>
                <button type="button" className="ssp-btn-link" onClick={handleRefresh}>
                  {t('btn_refresh')} <RefreshCw size={14} />
                </button>
              </div>

              <div className="ssp-table-wrap">
                <table className="ssp-data-table">
                  <thead>
                    <tr>
                      <th>Dataset</th>
                      <th>{t('th_progress')}</th>
                      <th style={{ textAlign: 'center' }}>{t('user_mgmt_th_status')}</th>
                      <th style={{ textAlign: 'right' }}>{t('th_frames_count')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="ssp-dataset-name">nuScenes 170 scenes</td>
                      <td className="ssp-progress-col">
                        <div className="ssp-progress-box">
                          <div className="ssp-progress-track-bg">
                            <div
                              className="ssp-progress-bar-inner"
                              style={{
                                width: '100%',
                                backgroundColor: 'var(--color-tertiary, #10b981)'
                              }}
                            />
                          </div>
                          <span
                            className="ssp-progress-text"
                            style={{ color: 'var(--color-tertiary, #10b981)' }}
                          >
                            100%
                          </span>
                        </div>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <Badge variant="success">{t('status_completed')}</Badge>
                      </td>
                      <td
                        style={{
                          textAlign: 'right',
                          color: 'var(--color-on-surface-variant, #64748b)',
                          fontSize: '13px'
                        }}
                      >
                        {stats?.total_frames ?? 6858} frames
                      </td>
                    </tr>
                    <tr>
                      <td className="ssp-dataset-name">Human Reviews Buffer</td>
                      <td className="ssp-progress-col">
                        <div className="ssp-progress-box">
                          <div className="ssp-progress-track-bg">
                            <div
                              className="ssp-progress-bar-inner"
                              style={{
                                width: '100%',
                                backgroundColor: 'var(--color-primary, #2563eb)'
                              }}
                            />
                          </div>
                          <span
                            className="ssp-progress-text"
                            style={{ color: 'var(--color-primary, #2563eb)' }}
                          >
                            100%
                          </span>
                        </div>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <Badge variant="primary">{t('status_ready')}</Badge>
                      </td>
                      <td
                        style={{
                          textAlign: 'right',
                          color: 'var(--color-on-surface-variant, #64748b)',
                          fontSize: '13px'
                        }}
                      >
                        {stats?.total_reviews ?? 0} reviews
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* System Resources */}
            <div className="ssp-resources-card" id="monitoring">
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}
              >
                <h3 className="ssp-card-title">{t('system_resources_real')}</h3>
                <button
                  type="button"
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-on-surface-variant)' }}
                  title={t('btn_refresh')}
                  onClick={handleRefresh}
                >
                  <RefreshCw size={18} className={isLoading ? 'spinning' : ''} />
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                {/* CPU Usage */}
                <div className="ssp-resource-item">
                  <div className="ssp-resource-head">
                    <span className="ssp-resource-name">CPU Usage</span>
                    <span
                      className="ssp-resource-val"
                      style={{ color: 'var(--color-primary, #2563eb)' }}
                    >
                      {isLoading ? '...' : `${stats?.cpu_usage ?? 18.5}%`}
                    </span>
                  </div>
                  <div className="ssp-progress-track-bg" style={{ height: '6px' }}>
                    <div
                      className="ssp-progress-bar-inner"
                      style={{
                        width: `${Math.min(100, stats?.cpu_usage ?? 18.5)}%`,
                        backgroundColor: 'var(--color-primary, #2563eb)'
                      }}
                    />
                  </div>
                </div>

                {/* RAM */}
                <div className="ssp-resource-item">
                  <div className="ssp-resource-head">
                    <span className="ssp-resource-name">RAM (Memory)</span>
                    <span
                      className="ssp-resource-val"
                      style={{ color: 'var(--color-secondary, #4e6073)' }}
                    >
                      {isLoading ? '...' : `${stats?.ram_usage ?? 42}%`}
                    </span>
                  </div>
                  <div className="ssp-progress-track-bg" style={{ height: '6px' }}>
                    <div
                      className="ssp-progress-bar-inner"
                      style={{
                        width: `${Math.min(100, stats?.ram_usage ?? 42)}%`,
                        backgroundColor: 'var(--color-secondary, #4e6073)'
                      }}
                    />
                  </div>
                </div>

                {/* Storage */}
                <div className="ssp-resource-item">
                  <div className="ssp-resource-head">
                    <span className="ssp-resource-name">Storage</span>
                    <span className="ssp-resource-val">
                      {isLoading ? '...' : `${stats?.storage_usage ?? 0}%`}
                    </span>
                  </div>
                  <div className="ssp-progress-track-bg" style={{ height: '6px' }}>
                    <div
                      className="ssp-progress-bar-inner"
                      style={{
                        width: `${Math.min(100, stats?.storage_usage ?? 0)}%`,
                        backgroundColor: 'var(--color-on-surface, #0f172a)'
                      }}
                    />
                  </div>
                  <p
                    style={{
                      textAlign: 'right',
                      fontSize: '11px',
                      color: 'var(--color-on-surface-variant, #64748b)',
                      marginTop: '4px'
                    }}
                  >
                    {stats?.storage_free_gb ?? 0} GB free / {stats?.storage_total_gb ?? 0} GB total
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom Info Bar */}
          <footer className="ssp-dashboard-footer">
            <p>{t('copyright_footer')}</p>
            <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
              <div className="ssp-status-pulse-group">
                <span className="ssp-pulse-dot" />
                <span>{t('system_stable')}</span>
              </div>
              <p>{t('last_updated', { time: lastUpdated || t('just_now') })}</p>
            </div>
          </footer>
        </main>
      </div>

      {/* Contextual FAB */}
      <div className="ssp-fab-container">
        <button className="ssp-btn-fab" title={t('refresh_data')} onClick={handleRefresh}>
          <RefreshCw size={24} className={isLoading ? 'spinning' : ''} />
        </button>
      </div>
    </div>
  );
};

export default AdminDashboard;

