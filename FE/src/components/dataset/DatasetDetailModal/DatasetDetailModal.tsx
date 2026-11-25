import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  X,
  Search,
  Film,
  Calendar,
  Layers,
  CheckCircle2,
  Clock,
  AlertCircle,
  Maximize2,
  Tag,
  Download,
  Info
} from 'lucide-react';
import { Modal } from '../../base/Modal/Modal';
import { Badge } from '../../base/Badge/Badge';
import './DatasetDetailModal.css';

export interface ExtractedFrame {
  id: string;
  frameIndex: number;
  timestamp: string;
  videoName: string;
  imgUrl: string;
  resolution: string;
  objectsDetected?: string[];
  isKeyframe?: boolean;
}

export interface DatasetItem {
  id: number;
  name: string;
  frames: string;
  status: 'completed' | 'indexing' | 'pending';
  statusText: string;
  createdAt: string;
  imgSrc: string | null;
  videoSource?: string;
  extractedFramesCount?: number;
  extractedFrames?: ExtractedFrame[];
}

interface DatasetDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  dataset: DatasetItem | null;
}

export const DatasetDetailModal: React.FC<DatasetDetailModalProps> = ({
  isOpen,
  onClose,
  dataset,
}) => {
  const { t } = useTranslation();
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState<'all' | 'keyframe' | 'objects'>('all');
  const [activeFrame, setActiveFrame] = useState<ExtractedFrame | null>(null);

  if (!dataset) return null;

  const frames = dataset.extractedFrames || [];

  const filteredFrames = frames.filter((frame) => {
    const matchesSearch =
      frame.videoName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      `frame ${frame.frameIndex}`.toLowerCase().includes(searchTerm.toLowerCase()) ||
      frame.timestamp.includes(searchTerm) ||
      frame.objectsDetected?.some((obj) => obj.toLowerCase().includes(searchTerm.toLowerCase()));

    if (!matchesSearch) return false;

    if (filterType === 'keyframe') return frame.isKeyframe;
    if (filterType === 'objects') return frame.objectsDetected && frame.objectsDetected.length > 0;
    return true;
  });

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="" size="lg">
      <div className="ssp-ds-modal-container">
        {/* Header section */}
        <div className="ssp-ds-modal-header">
          <div className="ssp-ds-header-title-row">
            <div className="ssp-ds-icon-wrapper">
              <Film size={22} className="ssp-ds-film-icon" />
            </div>
            <div>
              <div className="ssp-ds-title-group">
                <h2 className="ssp-ds-modal-title">{dataset.name}</h2>
                {dataset.status === 'completed' && (
                  <Badge variant="success">
                    <CheckCircle2 size={12} style={{ marginRight: 4 }} />
                    {t('status_completed')}
                  </Badge>
                )}
                {dataset.status === 'indexing' && (
                  <Badge variant="primary">
                    <Clock size={12} style={{ marginRight: 4 }} />
                    Indexing
                  </Badge>
                )}
                {dataset.status === 'pending' && (
                  <Badge variant="warning">
                    <AlertCircle size={12} style={{ marginRight: 4 }} />
                    {t('status_offline')}
                  </Badge>
                )}
              </div>
              <p className="ssp-ds-modal-subtitle">
                {t('ds_detail_subtitle')}
              </p>
            </div>
          </div>
        </div>

        {/* Metadata summary cards */}
        <div className="ssp-ds-meta-grid">
          <div className="ssp-ds-meta-card">
            <div className="ssp-ds-meta-icon"><Layers size={16} /></div>
            <div>
              <span className="ssp-ds-meta-label">{t('ds_total_frames_lbl')}</span>
              <span className="ssp-ds-meta-value">{dataset.frames}</span>
            </div>
          </div>

          <div className="ssp-ds-meta-card">
            <div className="ssp-ds-meta-icon"><Film size={16} /></div>
            <div>
              <span className="ssp-ds-meta-label">{t('ds_source_video_lbl')}</span>
              <span className="ssp-ds-meta-value">{dataset.videoSource || 'cam_feed_main.mp4'}</span>
            </div>
          </div>

          <div className="ssp-ds-meta-card">
            <div className="ssp-ds-meta-icon"><Calendar size={16} /></div>
            <div>
              <span className="ssp-ds-meta-label">{t('ds_extraction_date_lbl')}</span>
              <span className="ssp-ds-meta-value">{dataset.createdAt}</span>
            </div>
          </div>

          <div className="ssp-ds-meta-card">
            <div className="ssp-ds-meta-icon"><Info size={16} /></div>
            <div>
              <span className="ssp-ds-meta-label">{t('ds_extraction_fps_lbl')}</span>
              <span className="ssp-ds-meta-value">{t('ds_frames_per_sec')}</span>
            </div>
          </div>
        </div>

        {/* Search & Filter Toolbar */}
        <div className="ssp-ds-toolbar">
          <div className="ssp-ds-search-box">
            <Search size={16} className="ssp-ds-search-icon" />
            <input
              type="text"
              placeholder={t('ds_search_frames_placeholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="ssp-ds-search-input"
            />
          </div>

          <div className="ssp-ds-filter-tabs">
            <button
              type="button"
              className={`ssp-ds-tab ${filterType === 'all' ? 'active' : ''}`}
              onClick={() => setFilterType('all')}
            >
              {t('tab_all_images', { count: frames.length })}
            </button>
            <button
              type="button"
              className={`ssp-ds-tab ${filterType === 'keyframe' ? 'active' : ''}`}
              onClick={() => setFilterType('keyframe')}
            >
              {t('tab_keyframes', { count: frames.filter(f => f.isKeyframe).length })}
            </button>
            <button
              type="button"
              className={`ssp-ds-tab ${filterType === 'objects' ? 'active' : ''}`}
              onClick={() => setFilterType('objects')}
            >
              {t('tab_labeled', { count: frames.filter(f => f.objectsDetected && f.objectsDetected.length > 0).length })}
            </button>
          </div>
        </div>

        {/* Extracted Frames Gallery */}
        <div className="ssp-ds-frames-section">
          <div className="ssp-ds-section-header">
            <h3 className="ssp-ds-section-title">
              {t('ds_extracted_section_title', { count: filteredFrames.length })}
            </h3>
            <span className="ssp-ds-section-note">
              {t('ds_extracted_section_note')}
            </span>
          </div>

          {filteredFrames.length === 0 ? (
            <div className="ssp-ds-empty-state">
              <Film size={40} className="ssp-ds-empty-icon" />
              <p>{t('ds_empty_frames')}</p>
            </div>
          ) : (
            <div className="ssp-ds-frames-grid">
              {filteredFrames.map((frame) => (
                <div
                  key={frame.id}
                  className="ssp-ds-frame-card"
                  onClick={() => setActiveFrame(frame)}
                >
                  <div className="ssp-ds-frame-img-wrapper">
                    <img src={frame.imgUrl} alt={`Frame ${frame.frameIndex}`} className="ssp-ds-frame-img" />
                    <div className="ssp-ds-frame-overlay">
                      <span className="ssp-ds-zoom-btn" title={t('ds_zoom_tooltip')}>
                        <Maximize2 size={16} />
                      </span>
                    </div>
                    {frame.isKeyframe && (
                      <span className="ssp-ds-keyframe-badge">Keyframe</span>
                    )}
                    <span className="ssp-ds-timestamp-badge">{frame.timestamp}</span>
                  </div>

                  <div className="ssp-ds-frame-info">
                    <div className="ssp-ds-frame-title-row">
                      <span className="ssp-ds-frame-name">Frame #{frame.frameIndex}</span>
                      <span className="ssp-ds-frame-res">{frame.resolution}</span>
                    </div>
                    <span className="ssp-ds-frame-video">{frame.videoName}</span>

                    {frame.objectsDetected && frame.objectsDetected.length > 0 && (
                      <div className="ssp-ds-tags-row">
                        {frame.objectsDetected.map((tag, idx) => (
                          <span key={idx} className="ssp-ds-tag-pill">
                            <Tag size={10} />
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Lightbox Modal for enlarged frame inspection */}
      {activeFrame && (
        <div className="ssp-ds-lightbox-backdrop" onClick={() => setActiveFrame(null)}>
          <div className="ssp-ds-lightbox-content" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="ssp-ds-lightbox-close"
              onClick={() => setActiveFrame(null)}
              title={t('ds_close_zoom')}
            >
              <X size={20} />
            </button>

            <div className="ssp-ds-lightbox-body">
              <div className="ssp-ds-lightbox-img-col">
                <img
                  src={activeFrame.imgUrl}
                  alt={`Frame ${activeFrame.frameIndex}`}
                  className="ssp-ds-lightbox-img"
                />
              </div>

              <div className="ssp-ds-lightbox-info-col">
                <div className="ssp-ds-lightbox-header">
                  <h3>Frame #{activeFrame.frameIndex}</h3>
                  <span className="ssp-ds-lightbox-time">{activeFrame.timestamp}</span>
                </div>

                <div className="ssp-ds-lightbox-details">
                  <div className="ssp-ds-detail-row">
                    <span className="ssp-ds-detail-label">{t('ds_source_video_lbl')}</span>
                    <span className="ssp-ds-detail-val">{activeFrame.videoName}</span>
                  </div>
                  <div className="ssp-ds-detail-row">
                    <span className="ssp-ds-detail-label">{t('ds_resolution_lbl')}</span>
                    <span className="ssp-ds-detail-val">{activeFrame.resolution}</span>
                  </div>
                  <div className="ssp-ds-detail-row">
                    <span className="ssp-ds-detail-label">{t('ds_frame_type_lbl')}</span>
                    <span className="ssp-ds-detail-val">
                      {activeFrame.isKeyframe ? t('ds_keyframe_type') : t('ds_standard_frame_type')}
                    </span>
                  </div>
                  {activeFrame.objectsDetected && (
                    <div className="ssp-ds-detail-row ssp-ds-detail-row-col">
                      <span className="ssp-ds-detail-label">{t('ds_objects_detected_lbl')}</span>
                      <div className="ssp-ds-lightbox-tags">
                        {activeFrame.objectsDetected.map((obj, i) => (
                          <span key={i} className="ssp-ds-tag-pill ssp-ds-tag-pill-lg">
                            {obj}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <div className="ssp-ds-lightbox-actions">
                  <a
                    href={activeFrame.imgUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="ssp-ds-btn-download"
                  >
                    <Download size={16} />
                    {t('ds_download_original')}
                  </a>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
};
