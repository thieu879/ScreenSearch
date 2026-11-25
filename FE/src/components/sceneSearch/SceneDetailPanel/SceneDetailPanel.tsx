import React from 'react';
import { useTranslation } from 'react-i18next';
import { Download, BarChart2, Database, ExternalLink, ImageOff } from 'lucide-react';
import { SlideOver } from '../../base/SlideOver/SlideOver';
import type { Decision } from '../../../types/api';
import type { SceneItemData } from '../ResultCard/ResultCard';
import { translateCaption } from '../../../lib/captionTranslator';
import { downloadFrame } from '../../../lib/downloadFrame';
import { MomentPlayer } from '../MomentPlayer/MomentPlayer';
import { ReviewActions } from '../ReviewActions/ReviewActions';
import './SceneDetailPanel.css';

export interface SceneDetailPanelProps {
  scene: SceneItemData | null;
  isOpen: boolean;
  onClose: () => void;
  decision?: Decision;
  onDecide?: (frameId: string, decision: Decision) => void;
  /** Raised when the server refuses the frame. This component has no toast of its own — the page
   *  that opens the panel owns the container, the same way it owns the review-error toast. */
  onDownloadError?: () => void;
}

export const SceneDetailPanel: React.FC<SceneDetailPanelProps> = ({
  scene,
  isOpen,
  onClose,
  decision,
  onDecide,
  onDownloadError,
}) => {
  const { t, i18n } = useTranslation();
  const [imgError, setImgError] = React.useState(false);

  if (!scene) return null;

  const handleDownload = async () => {
    if (!scene) return;
    if ((await downloadFrame(scene.imgSrc, scene.filename)) === 'failed') onDownloadError?.();
  };

  const headerAction = (
    <button type="button" className="ssp-btn-download" onClick={handleDownload}>
      <Download size={16} />
      <span>{t('download_btn')}</span>
    </button>
  );

  return (
    <SlideOver
      isOpen={isOpen}
      onClose={onClose}
      title={t('scene_detail_title')}
      headerAction={headerAction}
      width="600px"
    >
      <div className="ssp-panel-body">
        {/* Hero Image */}
        <div className="ssp-panel-hero-image">
          {imgError ? (
            <div className="ssp-panel-img-fallback">
              <ImageOff size={32} />
              <span>{t('img_load_error')}</span>
            </div>
          ) : (
            <img
              src={scene.imgSrc}
              alt={scene.filename}
              onError={() => setImgError(true)}
            />
          )}
        </div>

        {scene.rawHit?.moment && <MomentPlayer moment={scene.rawHit.moment} />}

        {scene.rawHit?.source && (
          <p className="ssp-source-link">
            <a href={scene.rawHit.source.url} target="_blank" rel="noopener noreferrer nofollow">
              <ExternalLink size={14} /> {t('source_watch_original')}
            </a>
            <span className="ssp-source-credit">
              {[scene.rawHit.source.title, scene.rawHit.source.uploader].filter(Boolean).join(' · ')}
              {scene.rawHit.source.license ? ` · ${scene.rawHit.source.license}` : ''}
            </span>
          </p>
        )}

        {onDecide && (
          <div className="ssp-panel-review-actions" style={{ marginBottom: '16px' }}>
            <ReviewActions
              decision={decision}
              onDecide={(val) => onDecide(String(scene.id), val)}
              size="detail"
            />
          </div>
        )}

        {/* Info Cards Grid */}
        <div className="ssp-info-cards-grid">
          <div className="ssp-info-box">
            <p className="ssp-info-label">{t('filename_lbl')}</p>
            <p className="ssp-info-value">{scene.filename}</p>
          </div>

          <div className="ssp-info-box">
            <p className="ssp-info-label">{t('similarity_lbl')}</p>
            <div className="ssp-similarity-progress">
              <span className="ssp-similarity-text">{scene.similarity}</span>
              <div className="ssp-progress-bar-bg">
                <div
                  className="ssp-progress-bar-fill"
                  style={{ width: `${scene.similarityVal}%` }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Semantic Analysis */}
        <section className="ssp-detail-section">
          <h4 className="ssp-section-title">
            <BarChart2 size={18} className="ssp-section-icon" />
            <span>{t('semantic_analysis')}</span>
          </h4>

          <div className="ssp-analysis-box">
            <div>
              <p className="ssp-info-label" style={{ marginBottom: '8px' }}>
                {t('system_labels')}
              </p>
              <div className="ssp-card-tags">
                {scene.labels.map((label, idx) => (
                  <span key={`${label}-${idx}`} className="ssp-detail-tag">
                    {label}
                  </span>
                ))}
              </div>
            </div>

            {scene.description && (
              <div>
                <p className="ssp-info-label" style={{ marginBottom: '8px' }}>
                  {t('caption_florence')}
                </p>
                <p className="ssp-analysis-text">"{translateCaption(scene.description, i18n.language)}"</p>
              </div>
            )}
          </div>
        </section>

        {/* Metadata Table */}
        <section className="ssp-detail-section" style={{ paddingBottom: '32px' }}>
          <h4 className="ssp-section-title">
            <Database size={18} className="ssp-section-icon" />
            <span>{t('meta_detailed')}</span>
          </h4>

          <table className="ssp-metadata-table">
            <tbody>
              <tr>
                <th>{t('record_time')}</th>
                <td>{scene.timestamp}</td>
              </tr>
              {scene.dataset && (
                <tr>
                  <th>Dataset</th>
                  <td>{scene.dataset}</td>
                </tr>
              )}
              <tr>
                <th>Camera ID</th>
                <td>{scene.cameraId ?? 'CAM_FRONT'}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </SlideOver>
  );
};

export default SceneDetailPanel;
