import React from 'react';
import { useTranslation } from 'react-i18next';
import { ExternalLink } from 'lucide-react';
import { Modal } from '../../base/Modal/Modal';
import { Badge } from '../../base/Badge/Badge';
import type { Decision, FrameHit } from '../../../types/api';
import { thumbSrc } from '../../../api/client';
import { formatTimestamp, satisfiedLabel, shortSceneId, type SupportedLang } from '../../../lib/satisfied';
import { MomentPlayer } from '../MomentPlayer/MomentPlayer';
import { ReviewActions } from '../ReviewActions/ReviewActions';
import './SceneDetailModal.css';

interface SceneDetailModalProps {
  hit: FrameHit | null;
  onClose: () => void;
  decision?: Decision;
  onDecide: (frameId: string, decision: Decision) => void;
}

/**
 * Detail for one frame.
 *
 * Every value here comes from the `FrameHit` the API returned. The previous version showed
 * "MP4 / 1080p", "FPS 60" and a 12.4 s duration — none of which exist: the corpus is 2 Hz JPEG
 * keyframes, and there is no video, no frame rate and no clip duration in the response.
 *
 * `hit.source` is the one exception and it is not a walk-back of that. It is not a property of the
 * frame invented for display — it is a URL the corpus's own `videos.json` records, and it is null
 * unless the backend has one. On nuScenes it always is, so this block simply does not render.
 *
 * `score` is shown raw and labelled as a similarity rather than converted into a percentage. It is
 * documented as not a probability, and the number is only meaningful compared against other frames
 * in the same result set.
 *
 * The review controls are repeated here, not only on the card. This is the view a reviewer opens to
 * look properly before deciding, so making them close it and find the card again to record what
 * they just concluded is where verdicts get lost.
 */
export const SceneDetailModal: React.FC<SceneDetailModalProps> = ({ hit, onClose, decision, onDecide }) => {
  const { t, i18n } = useTranslation();
  if (!hit) return null;

  const lang = (i18n.language === 'en' ? 'en' : 'vi') as SupportedLang;
  const label = `${t('scene_modal_scene')} ${shortSceneId(hit.scene_id)} · ${formatTimestamp(hit.timestamp_s)}`;

  return (
    <Modal isOpen={Boolean(hit)} onClose={onClose} title={label} size="lg">
      <div className="scene-detail">
        <div className="scene-detail__preview">
          <img src={thumbSrc(hit.thumb_url)} alt={label} className="scene-detail__img" />
          <span className="scene-detail__cam-label">CAM_FRONT</span>
        </div>

        <div className="scene-detail__meta">
          <div className="scene-detail__status-row">
            <span className="scene-detail__time">
              {formatTimestamp(hit.timestamp_s)} {t('scene_modal_in_clip')}
            </span>
            <ReviewActions
              decision={decision}
              onDecide={(value) => onDecide(hit.frame_id, value)}
              size="detail"
            />
          </div>

          {hit.moment && <MomentPlayer moment={hit.moment} />}

          {hit.source && (
            <div className="scene-detail__source">
              <a
                className="scene-detail__source-link"
                href={hit.source.url}
                target="_blank"
                rel="noopener noreferrer nofollow"
              >
                <ExternalLink size={14} />
                <span>{t('source_watch_original')}</span>
              </a>
              <p className="scene-detail__source-credit">
                {[hit.source.title, hit.source.uploader].filter(Boolean).join(' · ')}
                {hit.source.license && <span className="scene-detail__source-licence"> · {hit.source.license}</span>}
              </p>
              <p className="scene-detail__source-note">{t('source_note')}</p>
            </div>
          )}

          {hit.satisfied.length > 0 && (
            <div className="scene-detail__desc-block">
              <p className="scene-detail__desc-label">{t('scene_modal_matched_conditions')}</p>
              <div className="scene-detail__tags">
                {hit.satisfied.map((token) => (
                  <Badge key={token} variant="success">
                    {satisfiedLabel(token, lang)}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <div className="scene-detail__stats">
            <div className="scene-detail__stat">
              <span className="scene-detail__stat-label">{t('scene_modal_similarity_score')}</span>
              <span className="scene-detail__stat-value" title="Similarity from the retrieval encoder — not a probability">
                {hit.score.toFixed(3)}
              </span>
            </div>
            <div className="scene-detail__stat">
              <span className="scene-detail__stat-label">{t('scene_modal_timestamp')}</span>
              <span className="scene-detail__stat-value">{hit.timestamp_s.toFixed(1)}s</span>
            </div>
            <div className="scene-detail__stat">
              <span className="scene-detail__stat-label">{t('scene_modal_clip_id')}</span>
              <span className="scene-detail__stat-value">{shortSceneId(hit.scene_id)}</span>
            </div>
            <div className="scene-detail__stat">
              <span className="scene-detail__stat-label">{t('scene_modal_frame_id')}</span>
              <span className="scene-detail__stat-value">{hit.frame_id.slice(0, 8)}</span>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
};

export default SceneDetailModal;
