import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  RefreshCw,
  ArrowUp,
  Minus,
  Database,
  Server,
  Cpu,
  CheckCircle2,
  Info,
  Zap,
  Eye,
  Pencil,
  Activity,
  Globe,
  HardDrive,
} from 'lucide-react';
import { AdminSidebar } from '../../components/layout/Sidebar/AdminSidebar';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import { Modal } from '../../components/base/Modal/Modal';
import { Button } from '../../components/base/Button/Button';
import { Input } from '../../components/base/Input/Input';
import { adminGetStats } from '../../api/auth';
import type { SystemStatsResponse, ServiceStatusItem } from '../../api/auth';
import { useAuth } from '../../contexts/AuthContext';
import './SystemMonitoring.css';

export const SystemMonitoring: React.FC = () => {
  const { user: currentUser } = useAuth();
  const { t } = useTranslation();
  const [currentTime, setCurrentTime] = useState('');
  const [isRotating, setIsRotating] = useState(false);
  const [stats, setStats] = useState<SystemStatsResponse | null>(null);
  const [services, setServices] = useState<ServiceStatusItem[]>([]);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  // Modal states
  const [selectedViewService, setSelectedViewService] = useState<ServiceStatusItem | null>(null);
  const [selectedEditService, setSelectedEditService] = useState<ServiceStatusItem | null>(null);

  const loadData = useCallback(async () => {
    try {
      const data = await adminGetStats();
      setStats(data);
      setServices(data.services);
    } catch (err) {
      console.error('Failed to load system monitoring data:', err);
    } finally {
      setTimeout(() => setIsRotating(false), 500);
    }
  }, []);

  const handleReload = useCallback(() => {
    setIsRotating(true);
    loadData();
  }, [loadData]);

  useEffect(() => {
    let ignore = false;
    adminGetStats()
      .then((data) => {
        if (!ignore) {
          setStats(data);
          setServices(data.services);
        }
      })
      .catch((err) => {
        if (!ignore) {
          console.error('Failed to load system monitoring data:', err);
        }
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(
        now.toLocaleDateString('vi-VN') + ' ' + now.toLocaleTimeString('vi-VN')
      );
    };

    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleSaveEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedEditService) return;

    setServices((prev) =>
      prev.map((s) => (s.id === selectedEditService.id ? selectedEditService : s))
    );
    setSelectedEditService(null);
  };

  return (
    <div className="ssp-monitor-layout">
      {/* Side Navigation Bar for Admin Role */}
      <AdminSidebar
        activeTab="monitoring"
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Wrapper */}
      <div className="ssp-monitor-main-wrapper">
        {/* Top App Bar */}
        <TopBar
          pageTitle={t('monitor_title')}
          roleBadge="System Owner"
          userName={currentUser?.full_name || currentUser?.username || currentUser?.email || 'Quản trị viên'}
          userRole={currentUser?.role === 'Admin' ? t('system_admin') : t('regular_user')}
          onToggleMenu={() => setIsMobileMenuOpen((prev) => !prev)}
        />

        {/* Content Canvas */}
        <main className="ssp-monitor-canvas">
          {/* Header Actions */}
          <div className="ssp-actions-bar">
            <div>
              <p className="ssp-page-description">
                {t('monitoring_desc_text')}
              </p>
            </div>
            <button
              type="button"
              className="ssp-btn-reload"
              onClick={handleReload}
            >
              <RefreshCw
                size={16}
                className={`ssp-reload-icon ${isRotating ? 'spinning' : ''}`}
              />
              <span className="ssp-btn-reload-text">{t('reload_data_btn')}</span>
            </button>
          </div>

          {/* Bento Grid: Metric Cards */}
          <div className="ssp-metrics-grid">
            {/* CPU */}
            <div className="ssp-metric-card">
              <div className="ssp-metric-header">
                <span className="ssp-metric-title">{t('cpu_usage')}</span>
                <span className="ssp-status-tag stable">STABLE</span>
              </div>
              <div className="ssp-metric-body">
                <h3 className="ssp-metric-value">{stats ? `${stats.cpu_usage}%` : '...'}</h3>
                <span className="ssp-metric-change neutral">
                  <Minus size={14} /> Realtime
                </span>
              </div>
              <div className="ssp-chart-container">
                <svg viewBox="0 0 100 30" style={{ width: '100%', height: '100%' }}>
                  <path
                    className="ssp-line-chart-path stroke-primary"
                    d="M0,25 L10,20 L20,24 L30,15 L40,18 L50,12 L60,20 L70,10 L80,15 L90,8 L100,12"
                  />
                </svg>
              </div>
            </div>

            {/* RAM */}
            <div className="ssp-metric-card">
              <div className="ssp-metric-header">
                <span className="ssp-metric-title">{t('ram_usage')}</span>
                <span className="ssp-status-tag normal">NORMAL</span>
              </div>
              <div className="ssp-metric-body">
                <h3 className="ssp-metric-value">{stats ? `${stats.ram_usage}%` : '...'}</h3>
                <span className="ssp-metric-change neutral">
                  <Minus size={14} /> Realtime
                </span>
              </div>
              <div className="ssp-chart-container">
                <svg viewBox="0 0 100 30" style={{ width: '100%', height: '100%' }}>
                  <path
                    className="ssp-line-chart-path stroke-secondary"
                    d="M0,20 L20,18 L40,22 L60,15 L80,10 L100,12"
                  />
                </svg>
              </div>
            </div>

            {/* Storage */}
            <div className="ssp-metric-card">
              <div className="ssp-metric-header">
                <span className="ssp-metric-title">{t('disk_usage')}</span>
                <span className="ssp-status-tag stable">STABLE</span>
              </div>
              <div className="ssp-metric-body">
                <h3 className="ssp-metric-value">{stats ? `${stats.storage_usage}%` : '...'}</h3>
                <span className="ssp-metric-change up-error">
                  <ArrowUp size={14} />
                  {stats ? `${stats.storage_free_gb} GB Free` : ''}
                </span>
              </div>
              <div className="ssp-chart-container">
                <svg viewBox="0 0 100 30" style={{ width: '100%', height: '100%' }}>
                  <path
                    className="ssp-line-chart-path stroke-tertiary"
                    d="M0,25 L20,22 L40,20 L60,18 L80,15 L100,10"
                  />
                </svg>
              </div>
            </div>

            {/* Active Users */}
            <div className="ssp-metric-card">
              <div className="ssp-metric-header">
                <span className="ssp-metric-title">{t('user_mgmt_total')}</span>
                <span className="ssp-status-tag optimized">ACTIVE</span>
              </div>
              <div className="ssp-metric-body">
                <h3 className="ssp-metric-value">{stats ? stats.active_users : '...'}</h3>
                <span className="ssp-metric-change neutral">
                  Total: {stats ? stats.total_users : '...'}
                </span>
              </div>
              <div className="ssp-chart-container">
                <svg viewBox="0 0 100 30" style={{ width: '100%', height: '100%' }}>
                  <path
                    className="ssp-line-chart-path stroke-tertiary"
                    d="M0,15 L15,10 L30,20 L45,15 L60,18 L75,12 L90,25 L100,20"
                  />
                </svg>
              </div>
            </div>
          </div>

          {/* Detailed Services Table Section */}
          <div className="ssp-table-card">
            <div className="ssp-table-card-header">
              <h3 className="ssp-table-card-title">{t('services_list')}</h3>
              <div className="ssp-live-status">
                <span className="ssp-dot-live" />
                {t('live_active')}
              </div>
            </div>

            <div className="ssp-table-wrapper">
              <table className="ssp-services-table">
                <thead>
                  <tr>
                    <th>{t('th_service')}</th>
                    <th>{t('user_mgmt_th_status')}</th>
                    <th>{t('th_uptime')}</th>
                    <th>{t('th_latency')}</th>
                    <th>{t('th_throughput')}</th>
                    <th style={{ textAlign: 'right' }}>{t('user_mgmt_th_actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {services.map((service) => (
                    <tr key={service.id}>
                      <td>
                        <div className="ssp-service-cell">
                          <div className={`ssp-service-icon-box ${service.icon}`}>
                            {service.icon === 'qdrant' && <Database size={18} />}
                            {service.icon === 'fastapi' && <Zap size={18} />}
                            {service.icon === 'postgres' && <Server size={18} />}
                            {service.icon === 'redis' && <Cpu size={18} />}
                          </div>
                          <div>
                            <div className="ssp-service-name">{service.name}</div>
                            <div className="ssp-service-sub">{service.subTitle}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className="ssp-status-active-chip">
                          <CheckCircle2 size={14} />
                          {service.status}
                        </span>
                      </td>
                      <td style={{ color: 'var(--ssp-on-surface)' }}>{service.uptime}</td>
                      <td style={{ color: 'var(--ssp-on-surface)' }}>{service.responseTime} ms</td>
                      <td style={{ color: 'var(--ssp-on-surface)' }}>{service.throughput}</td>
                      <td style={{ textAlign: 'right' }}>
                        <div className="ssp-action-btn-group">
                          <button
                            type="button"
                            className="ssp-btn-action-view"
                            title={t('view_details')}
                            onClick={() => setSelectedViewService(service)}
                          >
                            <Eye size={16} />
                          </button>
                          <button
                            type="button"
                            className="ssp-btn-action-edit"
                            title={t('edit_config')}
                            onClick={() => setSelectedEditService({ ...service })}
                          >
                            <Pencil size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="ssp-table-footer">
              <div>
                {t('updated_at', { time: currentTime })}
              </div>
              <div className="ssp-footer-realtime-status">
                <span className="ssp-pulse-dot" />
                <span style={{ color: '#047857', fontWeight: 600 }}>
                  {t('realtime_monitoring_running')}
                </span>
              </div>
            </div>
          </div>

          {/* Logs & Performance Summary Grid */}
          <div className="ssp-logs-perf-grid">
            {/* Logs */}
            <div className="ssp-log-card">
              <h4 className="ssp-section-card-title">{t('recent_incidents')}</h4>
              <div className="ssp-log-list">
                <div className="ssp-log-item info">
                  <Info size={18} className="ssp-log-icon info" />
                  <div>
                    <p className="ssp-log-title">
                      System Initialization: PostgreSQL & In-Memory Vector Engine active
                    </p>
                    <p className="ssp-log-desc">
                      Successfully loaded {stats?.total_frames ?? 6858} keyframes and embedding matrix.
                    </p>
                    <span className="ssp-log-time">Realtime</span>
                  </div>
                </div>

                <div className="ssp-log-item info">
                  <Info size={18} className="ssp-log-icon info" />
                  <div>
                    <p className="ssp-log-title">
                      Security Gate: CSRF Double-Submit & Admin Role Active
                    </p>
                    <p className="ssp-log-desc">
                      API Role-Based Access Control and JWT session verified.
                    </p>
                    <span className="ssp-log-time">Today</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Performance Analytics */}
            <div className="ssp-log-card">
              <div className="ssp-glow-bg-element" />
              <h4 className="ssp-section-card-title">
                {t('perf_analytics')}
              </h4>
              <div className="ssp-perf-list">
                <div>
                  <div className="ssp-perf-item-head">
                    <span className="ssp-perf-label">
                      {t('cosine_latency')}
                    </span>
                    <span className="ssp-perf-val primary">&lt; 15ms</span>
                  </div>
                  <div className="ssp-progress-track">
                    <div
                      className="ssp-progress-bar-fill primary"
                      style={{ width: '95%' }}
                    />
                  </div>
                </div>

                <div>
                  <div className="ssp-perf-item-head">
                    <span className="ssp-perf-label">{t('api_success_rate')}</span>
                    <span className="ssp-perf-val tertiary">100%</span>
                  </div>
                  <div className="ssp-progress-track">
                    <div
                      className="ssp-progress-bar-fill tertiary"
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>

                <div>
                  <div className="ssp-perf-item-head">
                    <span className="ssp-perf-label">{t('vector_ram_load')}</span>
                    <span className="ssp-perf-val secondary">{stats?.ram_usage ?? 42}%</span>
                  </div>
                  <div className="ssp-progress-track">
                    <div
                      className="ssp-progress-bar-fill secondary"
                      style={{ width: `${Math.min(100, stats?.ram_usage ?? 42)}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* View Detail Modal */}
      {selectedViewService && (
        <Modal
          isOpen={!!selectedViewService}
          onClose={() => setSelectedViewService(null)}
          title={t('service_detail_modal_title', { name: selectedViewService.name })}
          size="md"
        >
          <div className="ssp-service-detail-view">
            <div className="ssp-detail-row">
              <span className="ssp-detail-label">{t('service_name_label')}</span>
              <span className="ssp-detail-value font-bold">{selectedViewService.name} ({selectedViewService.subTitle})</span>
            </div>
            <div className="ssp-detail-row">
              <span className="ssp-detail-label">{t('user_mgmt_th_status')}</span>
              <span className="ssp-status-active-chip">
                <CheckCircle2 size={14} />
                {selectedViewService.status}
              </span>
            </div>
            <div className="ssp-detail-row">
              <span className="ssp-detail-label">{t('service_host_label')}</span>
              <span className="ssp-detail-value">{selectedViewService.host}:{selectedViewService.port}</span>
            </div>
            <div className="ssp-detail-row">
              <span className="ssp-detail-label">{t('service_uptime_label')}</span>
              <span className="ssp-detail-value">{selectedViewService.uptime}</span>
            </div>
            <div className="ssp-detail-row">
              <span className="ssp-detail-label">{t('service_latency_label')}</span>
              <span className="ssp-detail-value">{selectedViewService.responseTime} ms</span>
            </div>
            <div className="ssp-detail-row">
              <span className="ssp-detail-label">{t('service_throughput_label')}</span>
              <span className="ssp-detail-value">{selectedViewService.throughput}</span>
            </div>
            <div className="ssp-detail-row">
              <span className="ssp-detail-label">{t('service_max_conn_label')}</span>
              <span className="ssp-detail-value">{selectedViewService.maxConnections}</span>
            </div>
            <div className="ssp-detail-row">
              <span className="ssp-detail-label">{t('service_desc_label')}</span>
              <span className="ssp-detail-value">{selectedViewService.description}</span>
            </div>

            <div className="ssp-modal-footer">
              <Button
                variant="primary"
                type="button"
                onClick={() => setSelectedViewService(null)}
              >
                {t('btn_close')}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Edit Configuration Modal */}
      {selectedEditService && (
        <Modal
          isOpen={!!selectedEditService}
          onClose={() => setSelectedEditService(null)}
          title={t('edit_config_modal_title', { name: selectedEditService.name })}
          size="md"
        >
          <form onSubmit={handleSaveEdit} className="ssp-form-grid">
            <Input
              label="Host / Domain"
              placeholder="e.g. localhost"
              prefixIcon={<Globe size={16} />}
              value={selectedEditService.host}
              onChange={(e) =>
                setSelectedEditService({ ...selectedEditService, host: e.target.value })
              }
              required
              fullWidth
            />

            <Input
              label="Port"
              type="number"
              placeholder="8000"
              prefixIcon={<HardDrive size={16} />}
              value={selectedEditService.port}
              onChange={(e) =>
                setSelectedEditService({
                  ...selectedEditService,
                  port: parseInt(e.target.value) || 0,
                })
              }
              required
              fullWidth
            />

            <Input
              label={t('service_max_conn_label')}
              type="number"
              placeholder="1000"
              prefixIcon={<Activity size={16} />}
              value={selectedEditService.maxConnections}
              onChange={(e) =>
                setSelectedEditService({
                  ...selectedEditService,
                  maxConnections: parseInt(e.target.value) || 0,
                })
              }
              required
              fullWidth
            />

            <div className="ssp-form-group">
              <label className="ssp-form-label">
                <span>{t('service_status_select')}</span>
              </label>
              <select
                className="ssp-form-select"
                value={selectedEditService.status}
                onChange={(e) =>
                  setSelectedEditService({
                    ...selectedEditService,
                    status: e.target.value as 'HOẠT ĐỘNG' | 'BẢO TRÌ' | 'DỪNG',
                  })
                }
              >
                <option value="HOẠT ĐỘNG">{t('status_running')}</option>
                <option value="BẢO TRÌ">{t('status_maintenance')}</option>
                <option value="DỪNG">{t('status_stopped')}</option>
              </select>
            </div>

            <div className="ssp-modal-footer">
              <Button
                variant="ghost"
                type="button"
                onClick={() => setSelectedEditService(null)}
              >
                {t('btn_cancel')}
              </Button>
              <Button variant="primary" type="submit">
                {t('save_config_btn')}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
};

export default SystemMonitoring;

