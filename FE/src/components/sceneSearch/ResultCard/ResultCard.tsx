import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Clock, ImageOff, Database, Sparkles } from 'lucide-react';
import type { Decision, FrameHit } from '../../../types/api';
import { translateCaption } from '../../../lib/captionTranslator';
import { ReviewActions } from '../ReviewActions/ReviewActions';
import './ResultCard.css';

export interface SceneItemData {
  id: string | number;
  filename: string;
  similarity: string;
  similarityVal: number;
  labels: string[];
  timestamp: string;
  imgSrc: string;
  dataset?: string;
  cameraId?: string;
  description?: string;
  rawHit?: FrameHit;
}

export interface ResultCardProps {
  scene: SceneItemData;
  viewMode?: 'grid' | 'list';
  onClick: (scene: SceneItemData) => void;
  decision?: Decision;
  onDecide?: (decision: Decision) => void;
}

export const ResultCard: React.FC<ResultCardProps> = ({
  scene,
  viewMode = 'grid',
  onClick,
  decision,
  onDecide,
}) => {
  const { t, i18n } = useTranslation();
  const [imgError, setImgError] = useState(false);

  const translatedDescription = translateCaption(scene.description, i18n.language);

  return (
    <div
      className={`ssp-scene-card ssp-scene-card--${viewMode}`}
      onClick={() => onClick(scene)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick(scene);
        }
      }}
    >
      <div className="ssp-card-thumbnail">
        {imgError ? (
          <div className="ssp-card-img-fallback">
            <ImageOff size={24} />
            <span>{t('failed_to_load_img')}</span>
          </div>
        ) : (
          <img
            src={scene.imgSrc}
            alt={scene.filename}
            loading="lazy"
            onError={() => setImgError(true)}
          />
        )}
        {viewMode === 'grid' && scene.similarity && (
          <span className="ssp-similarity-badge">{scene.similarity}</span>
        )}
      </div>

      {viewMode === 'list' ? (
        <div className="ssp-card-list-body">
          {/* Main Info Column */}
          <div className="ssp-card-main-col">
            {/* Top row: Filename & inline metadata */}
            <div className="ssp-card-header-row">
              <h4 className="ssp-card-filename" title={scene.filename}>
                {scene.filename}
              </h4>
              <div className="ssp-card-meta-line">
                <span className="ssp-card-timestamp">
                  <Clock size={12} className="ssp-card-clock-icon" />
                  <span>{scene.timestamp}</span>
                </span>
                {scene.similarity && (
                  <span className="ssp-card-sim-chip" title={t('similarity_score')}>
                    <Sparkles size={11} />
                    <span>{t('similarity_label')}: {scene.similarity}</span>
                  </span>
                )}
                {scene.dataset && (
                  <span className="ssp-card-meta-chip dataset">
                    <Database size={11} /> {scene.dataset}
                  </span>
                )}
              </div>
            </div>

            {/* Middle: Translated AI Description */}
            {translatedDescription && (
              <p className="ssp-card-caption-desc" title={translatedDescription}>
                {translatedDescription}
              </p>
            )}

            {/* Bottom Row: Tags & Review Actions together on the left! */}
            <div className="ssp-card-bottom-row">
              <div className="ssp-card-tags">
                {scene.labels.map((label, idx) => (
                  <span
                    key={`${label}-${idx}`}
                    className={`ssp-tag ${idx % 2 === 0 ? 'ssp-tag-tertiary' : 'ssp-tag-secondary'}`}
                  >
                    {label === 'Frame' || label === 'FRAME' ? (i18n.language === 'vi' ? 'Khung hình' : 'Frame') : label}
                  </span>
                ))}
              </div>

              {onDecide && (
                <div className="ssp-card-review-inline" onClick={(e) => e.stopPropagation()}>
                  <ReviewActions
                    decision={decision}
                    onDecide={onDecide}
                    size="card"
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="ssp-card-content">
          <div className="ssp-card-tags">
            {scene.labels.map((label, idx) => (
              <span
                key={`${label}-${idx}`}
                className={`ssp-tag ${idx % 2 === 0 ? 'ssp-tag-tertiary' : 'ssp-tag-secondary'}`}
              >
                {label === 'Frame' || label === 'FRAME' ? (i18n.language === 'vi' ? 'Khung hình' : 'Frame') : label}
              </span>
            ))}
          </div>

          <p className="ssp-card-filename" title={scene.filename}>
            {scene.filename}
          </p>

          <p className="ssp-card-timestamp">
            <Clock size={13} className="ssp-card-clock-icon" />
            <span>{scene.timestamp}</span>
          </p>

          {onDecide && (
            <div className="ssp-card-review">
              <ReviewActions
                decision={decision}
                onDecide={onDecide}
                size="card"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ResultCard;
