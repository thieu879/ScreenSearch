import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Plus,
  Search,
  Filter,
  RefreshCw,
  Folder,
  ChevronLeft,
  ChevronRight,
  Eye
} from 'lucide-react';
import { AdminSidebar } from '../../components/layout/Sidebar/AdminSidebar';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import { Badge } from '../../components/base/Badge/Badge';
import { DatasetDetailModal } from '../../components/dataset/DatasetDetailModal/DatasetDetailModal';
import type { DatasetItem } from '../../components/dataset/DatasetDetailModal/DatasetDetailModal';
import { useAuth } from '../../contexts/AuthContext';
import './DatasetManagement.css';

const initialDatasets: DatasetItem[] = [
  {
    id: 1,
    name: 'nuScenes',
    frames: '1.4M',
    status: 'completed',
    statusText: 'Hoàn thành',
    createdAt: '20/05/2024',
    videoSource: 'boston_traffic_cam_01.mp4',
    imgSrc:
      'https://images.unsplash.com/photo-1506521781263-d8422e82f27a?auto=format&fit=crop&w=800&q=80',
    extractedFrames: [
      {
        id: 'ns-1',
        frameIndex: 102,
        timestamp: '00:01:15',
        videoName: 'boston_traffic_cam_01.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1506521781263-d8422e82f27a?auto=format&fit=crop&w=800&q=80',
        resolution: '1920x1080',
        objectsDetected: ['Xe ô tô', 'Xe tải', 'Cột đèn'],
        isKeyframe: true
      },
      {
        id: 'ns-2',
        frameIndex: 108,
        timestamp: '00:01:21',
        videoName: 'boston_traffic_cam_01.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1519003722824-194d4455a60c?auto=format&fit=crop&w=800&q=80',
        resolution: '1920x1080',
        objectsDetected: ['Xe ô tô', 'Đèn giao thông'],
        isKeyframe: false
      },
      {
        id: 'ns-3',
        frameIndex: 145,
        timestamp: '00:02:05',
        videoName: 'boston_traffic_cam_02.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1494515843206-f3117d3f51b7?auto=format&fit=crop&w=800&q=80',
        resolution: '1920x1080',
        objectsDetected: ['Xe buýt', 'Người đi bộ'],
        isKeyframe: true
      },
      {
        id: 'ns-4',
        frameIndex: 210,
        timestamp: '00:03:30',
        videoName: 'cam_front_left.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?auto=format&fit=crop&w=800&q=80',
        resolution: '1920x1080',
        objectsDetected: ['Vạch kẻ đường', 'Xe máy'],
        isKeyframe: false
      },
      {
        id: 'ns-5',
        frameIndex: 280,
        timestamp: '00:04:40',
        videoName: 'cam_front_right.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1542282088-72c9c27ed0cd?auto=format&fit=crop&w=800&q=80',
        resolution: '1920x1080',
        objectsDetected: ['Xe ô tô', 'Biển báo'],
        isKeyframe: true
      },
      {
        id: 'ns-6',
        frameIndex: 355,
        timestamp: '00:05:55',
        videoName: 'cam_rear.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=800&q=80',
        resolution: '1920x1080',
        objectsDetected: ['Cây xanh', 'Con đường'],
        isKeyframe: false
      }
    ]
  },
  {
    id: 2,
    name: 'Waymo Open',
    frames: '10.6M',
    status: 'indexing',
    statusText: 'Đang index',
    createdAt: '19/05/2024',
    videoSource: 'sf_downtown_hd.mp4',
    imgSrc:
      'https://images.unsplash.com/photo-1519003722824-194d4455a60c?auto=format&fit=crop&w=800&q=80',
    extractedFrames: [
      {
        id: 'wm-1',
        frameIndex: 45,
        timestamp: '00:00:45',
        videoName: 'sf_downtown_hd.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1519003722824-194d4455a60c?auto=format&fit=crop&w=800&q=80',
        resolution: '3840x2160',
        objectsDetected: ['Xe tự hành', 'Người đi bộ', 'Đèn LED'],
        isKeyframe: true
      },
      {
        id: 'wm-2',
        frameIndex: 90,
        timestamp: '00:01:30',
        videoName: 'sf_downtown_hd.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1502877338535-766e1452684a?auto=format&fit=crop&w=800&q=80',
        resolution: '3840x2160',
        objectsDetected: ['Xe ô tô', 'Vỉa hè'],
        isKeyframe: true
      },
      {
        id: 'wm-3',
        frameIndex: 175,
        timestamp: '00:02:55',
        videoName: 'highway_101_north.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1471478331149-c72f17e33c73?auto=format&fit=crop&w=800&q=80',
        resolution: '3840x2160',
        objectsDetected: ['Xe container', 'Cầu vượt'],
        isKeyframe: false
      },
      {
        id: 'wm-4',
        frameIndex: 230,
        timestamp: '00:03:50',
        videoName: 'highway_101_north.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1506521781263-d8422e82f27a?auto=format&fit=crop&w=800&q=80',
        resolution: '3840x2160',
        objectsDetected: ['Xe ô tô', 'Biển chỉ dẫn'],
        isKeyframe: false
      }
    ]
  },
  {
    id: 3,
    name: 'Argoverse 2',
    frames: '1.2M',
    status: 'indexing',
    statusText: 'Đang index',
    createdAt: '18/05/2024',
    videoSource: 'pittsburgh_sensor_array.mp4',
    imgSrc:
      'https://images.unsplash.com/photo-1494515843206-f3117d3f51b7?auto=format&fit=crop&w=800&q=80',
    extractedFrames: [
      {
        id: 'av-1',
        frameIndex: 12,
        timestamp: '00:00:12',
        videoName: 'pittsburgh_sensor_array.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1494515843206-f3117d3f51b7?auto=format&fit=crop&w=800&q=80',
        resolution: '2048x1536',
        objectsDetected: ['Xe ô tô', 'Bãi đỗ xe'],
        isKeyframe: true
      },
      {
        id: 'av-2',
        frameIndex: 88,
        timestamp: '00:01:28',
        videoName: 'pittsburgh_sensor_array.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?auto=format&fit=crop&w=800&q=80',
        resolution: '2048x1536',
        objectsDetected: ['Vô tầng', 'Người đạp xe'],
        isKeyframe: false
      },
      {
        id: 'av-3',
        frameIndex: 160,
        timestamp: '00:02:40',
        videoName: 'miami_beach_road.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1542282088-72c9c27ed0cd?auto=format&fit=crop&w=800&q=80',
        resolution: '2048x1536',
        objectsDetected: ['Hàng cây', 'Xe ô tô'],
        isKeyframe: true
      }
    ]
  },
  {
    id: 4,
    name: 'KITTI',
    frames: '0.4M',
    status: 'completed',
    statusText: 'Hoàn thành',
    createdAt: '15/05/2024',
    videoSource: 'karlsruhe_suburban.mp4',
    imgSrc:
      'https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?auto=format&fit=crop&w=800&q=80',
    extractedFrames: [
      {
        id: 'kt-1',
        frameIndex: 15,
        timestamp: '00:00:15',
        videoName: 'karlsruhe_suburban.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?auto=format&fit=crop&w=800&q=80',
        resolution: '1242x375',
        objectsDetected: ['Car', 'Pedestrian', 'Cyclist'],
        isKeyframe: true
      },
      {
        id: 'kt-2',
        frameIndex: 42,
        timestamp: '00:00:42',
        videoName: 'karlsruhe_suburban.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=800&q=80',
        resolution: '1242x375',
        objectsDetected: ['Tree', 'Road'],
        isKeyframe: false
      },
      {
        id: 'kt-3',
        frameIndex: 98,
        timestamp: '00:01:38',
        videoName: 'residential_drive.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1502877338535-766e1452684a?auto=format&fit=crop&w=800&q=80',
        resolution: '1242x375',
        objectsDetected: ['Car', 'Building'],
        isKeyframe: true
      }
    ]
  },
  {
    id: 5,
    name: 'Custom Dataset',
    frames: '2.0M',
    status: 'pending',
    statusText: 'Chưa index',
    createdAt: '14/05/2024',
    videoSource: 'drone_surveillance_cam01.mp4',
    imgSrc: null,
    extractedFrames: [
      {
        id: 'cd-1',
        frameIndex: 1,
        timestamp: '00:00:01',
        videoName: 'drone_surveillance_cam01.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1471478331149-c72f17e33c73?auto=format&fit=crop&w=800&q=80',
        resolution: '1920x1080',
        objectsDetected: ['Giao lộ', 'Xe cộ'],
        isKeyframe: true
      },
      {
        id: 'cd-2',
        frameIndex: 24,
        timestamp: '00:00:24',
        videoName: 'drone_surveillance_cam01.mp4',
        imgUrl: 'https://images.unsplash.com/photo-1506521781263-d8422e82f27a?auto=format&fit=crop&w=800&q=80',
        resolution: '1920x1080',
        objectsDetected: ['Ô tô', 'Tàu hỏa'],
        isKeyframe: false
      }
    ]
  }
];

export const DatasetManagement: React.FC = () => {
  const { user: currentUser } = useAuth();
  const { t } = useTranslation();
  const [searchTerm, setSearchTerm] = useState('');
  const [datasets] = useState<DatasetItem[]>(initialDatasets);

  const [selectedDataset, setSelectedDataset] = useState<DatasetItem | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const handleOpenDetail = (dataset: DatasetItem) => {
    setSelectedDataset(dataset);
    setIsDetailModalOpen(true);
  };

  const handleCloseDetail = () => {
    setIsDetailModalOpen(false);
    setSelectedDataset(null);
  };

  const filteredDatasets = datasets.filter((ds) =>
    ds.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="ssp-dataset-layout">
      {/* Side Navigation Bar for Admin Role */}
      <AdminSidebar
        activeTab="dataset"
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Wrapper */}
      <div className="ssp-dataset-main-wrapper">
        {/* Top App Bar */}
        <TopBar
          pageTitle={t('dataset_page_title')}
          roleBadge="System Admin"
          userName={currentUser?.full_name || currentUser?.username || currentUser?.email || 'Quản trị viên'}
          userRole={currentUser?.role === 'Admin' ? t('system_admin') : t('regular_user')}
          onToggleMenu={() => setIsMobileMenuOpen((prev) => !prev)}
        />

        {/* Content Canvas */}
        <main className="ssp-dataset-canvas">
          {/* Header Actions */}
          <div className="ssp-action-header">
            <div>
              <p className="ssp-page-description">
                {t('dataset_page_desc')}
              </p>
            </div>
            <button type="button" className="ssp-btn-add-dataset">
              <Plus size={18} />
              <span>{t('add_dataset_btn')}</span>
            </button>
          </div>

          {/* Stats Bento Grid */}
          <div className="ssp-stats-grid">
            <div className="ssp-stat-card">
              <p className="ssp-stat-label">{t('stat_total_datasets')}</p>
              <div className="ssp-stat-body">
                <span className="ssp-stat-value">12</span>
                <span className="ssp-stat-subtext">+2 tháng này</span>
              </div>
            </div>

            <div className="ssp-stat-card">
              <p className="ssp-stat-label">{t('stat_total_frames')}</p>
              <div className="ssp-stat-body">
                <span className="ssp-stat-value">2.5M</span>
                <span className="ssp-stat-subtext">
                  {t('raw_data')}
                </span>
              </div>
            </div>

            <div className="ssp-stat-card">
              <p className="ssp-stat-label">{t('stat_indexing_status')}</p>
              <div className="ssp-indexing-pulse-group">
                <span className="ssp-pulse-dot" />
                <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--color-tertiary, #10b981)'}}>
                  {t('processing_count', { count: 2 })}
                </span>
              </div>
            </div>

            <div className="ssp-stat-card">
              <p className="ssp-stat-label">{t('stat_storage')}</p>
              <span className="ssp-stat-value">4.2 TB</span>
            </div>
          </div>

          {/* Table Container */}
          <div className="ssp-table-card">
            <div className="ssp-table-toolbar">
              <div className="ssp-search-box">
                <Search size={16} className="ssp-search-icon" />
                <input
                  type="text"
                  className="ssp-search-input"
                  placeholder={t('dataset_search_placeholder')}
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
              </div>

              <div className="ssp-toolbar-actions">
                <button type="button" className="ssp-btn-tool" title="Filter">
                  <Filter size={18} />
                </button>
                <button type="button" className="ssp-btn-tool" title={t('btn_refresh')}>
                  <RefreshCw size={18} />
                </button>
              </div>
            </div>

            <table className="ssp-dataset-table">
              <thead>
                <tr>
                  <th>{t('th_dataset_name')}</th>
                  <th>{t('th_frames')}</th>
                  <th style={{ textAlign: 'center' }}>{t('user_mgmt_th_status')}</th>
                  <th>{t('th_created_date')}</th>
                  <th style={{ textAlign: 'right' }}>{t('user_mgmt_th_actions')}</th>
                </tr>
              </thead>
              <tbody>
                {filteredDatasets.map((ds) => (
                  <tr key={ds.id}>
                    <td>
                      <div className="ssp-dataset-name-cell">
                        {ds.imgSrc ? (
                          <div className="ssp-dataset-thumb">
                            <img alt={ds.name} src={ds.imgSrc} />
                          </div>
                        ) : (
                          <div className="ssp-dataset-thumb ssp-dataset-thumb-placeholder">
                            <Folder size={18} />
                          </div>
                        )}
                        <span className="ssp-dataset-name">{ds.name}</span>
                      </div>
                    </td>
                    <td>
                      <span className="ssp-frames-text">{ds.frames}</span>
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      {ds.status === 'completed' && (
                        <Badge variant="success">{t('status_completed')}</Badge>
                      )}
                      {ds.status === 'indexing' && (
                        <Badge variant="primary">Indexing</Badge>
                      )}
                      {ds.status === 'pending' && (
                        <Badge variant="warning">{t('status_offline')}</Badge>
                      )}
                    </td>
                    <td>
                      <span className="ssp-date-text">{ds.createdAt}</span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div className="ssp-action-buttons-group">
                        <button
                          type="button"
                          className="ssp-btn-action-view"
                          title={t('view_extracted_frames_tooltip')}
                          onClick={() => handleOpenDetail(ds)}
                        >
                          <Eye size={18} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Table Footer */}
            <div className="ssp-table-footer">
              <p className="ssp-footer-text">
                {t('showing_datasets', { count: filteredDatasets.length, total: datasets.length })}
              </p>
              <div className="ssp-pagination">
                <button type="button" className="ssp-btn-page" disabled title={t('prev_page')}>
                  <ChevronLeft size={16} />
                </button>
                <button type="button" className="ssp-page-number">1</button>
                <button type="button" className="ssp-btn-page" disabled title={t('next_page')}>
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* Dataset Detail & Extracted Video Frames Modal */}
      <DatasetDetailModal
        isOpen={isDetailModalOpen}
        onClose={handleCloseDetail}
        dataset={selectedDataset}
      />
    </div>
  );
};

export default DatasetManagement;
