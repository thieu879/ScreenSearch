/**
 * The full-page view of one frame, reached by clicking a result.
 *
 * This page was a static mockup until 2026-08-07: it showed a hardcoded weather badge, a twelve-
 * frame clip stepper over frames that have no clip structure, a camera this archive does not have,
 * and two verdict buttons that wrote to `useState` and told the reviewer "Đã duyệt". During the
 * first day of the feedback window testers recorded verdicts here that were silently discarded.
 *
 * The rule applied throughout: **render what the response actually carries, and nothing else.** A
 * field the reviewer cannot check is worse than a missing one, because it looks checkable — the
 * same reasoning that removed the fixed Ho Chi Minh City GPS from `SceneItemData` for a corpus
 * recorded in Boston and Singapore.
 *
 * Removed rather than reconnected, because nothing behind them exists:
 *
 * - **Weather.** Scene tagging ships `time` only. Weather measured 76.3% and was deliberately not
 *   shipped (M2_DESIGN §11), so `Rainy / Mưa` was not a stale value — it was a constant, printed
 *   over sunny daytime frames.
 * - **`Hành vi phương tiện: Stable Trajectory`** and **`Vật thể nhận diện: Pedestrian, Vehicle`.**
 *   Constants. The objects the retrieval actually matched are the `satisfied` chips, which are real
 *   and already rendered.
 * - **The 12-frame clip stepper.** `TOTAL_CLIP_FRAMES = 12` and `index * 2.0` seconds were
 *   invented; a frame's real position is its `timestamp_s` within its `scene_id`. The stepper now
 *   walks the *search results*, which is data we hold and what a reviewer working through a result
 *   set actually wants.
 */
import React, { useCallback, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, BarChart2, Camera, ChevronLeft, ChevronRight, Download, ExternalLink, ImageOff, Info } from 'lucide-react';

import { MomentPlayer } from '../../components/sceneSearch/MomentPlayer/MomentPlayer';
import { Sidebar } from '../../components/layout/Sidebar/Sidebar';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import { ToastContainer } from '../../components/base/Toast/Toast';
import { useToast } from '../../components/base/Toast/useToast';
import { ReviewActions } from '../../components/sceneSearch/ReviewActions/ReviewActions';
import type { SceneItemData } from '../../components/sceneSearch/ResultCard/ResultCard';
import { frameHitToSceneData } from '../../components/sceneSearch/ResultCard/frameHit';
import { useReviews } from '../../hooks/useReviews';
import { loadLastSearch } from '../../lib/lastSearch';
import { downloadFrame } from '../../lib/downloadFrame';

import type { Decision } from '../../types/api';
import './SceneDetail.css';

interface SceneDetailNavState {
  scene?: SceneItemData;
  searchResults?: SceneItemData[];
  currentIndex?: number;
  query?: string;
  initialDecision?: Decision;
}

export const SceneDetail: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { t, i18n } = useTranslation();
  const { id: frameIdFromUrl } = useParams<{ id: string }>();
  const { messages, addToast, dismiss } = useToast();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const navState = (location.state as SceneDetailNavState | null) ?? {};

  // The stored session is the fallback for a reload or a pasted link, where `location.state` is
  // gone. Without it this page used to fall back to a hardcoded demo frame — a googleusercontent
  // placeholder image and a similarity nobody measured — which is the one outcome worse than an
  // empty state, because it is indistinguishable from a real result.
  const [stored] = useState(loadLastSearch);
  const storedResults = useMemo(
    () => {
      const lang = i18n.language === 'en' ? 'en' : 'vi';
      return stored?.response.results.map((hit) => frameHitToSceneData(hit, lang)) ?? [];
    },
    [stored, i18n.language],
  );

  const hasMatchingStoredResult = storedResults.some((item) => String(item.id) === frameIdFromUrl);

  const results = useMemo(() => {
    if (navState.searchResults?.length) return navState.searchResults;
    if (hasMatchingStoredResult) return storedResults;
    if (navState.scene && String(navState.scene.id) === frameIdFromUrl) return [navState.scene];
    return [];
  }, [navState.searchResults, navState.scene, hasMatchingStoredResult, storedResults, frameIdFromUrl]);

  const query = navState.query ?? (hasMatchingStoredResult ? (stored?.query ?? null) : null);

  const [index, setIndex] = useState(() => {
    const fromUrl = results.findIndex((item) => String(item.id) === frameIdFromUrl);
    if (fromUrl >= 0) return fromUrl;
    return navState.currentIndex ?? 0;
  });

  const scene: SceneItemData | null =
    (results[index] && String(results[index].id) === frameIdFromUrl)
      ? results[index]
      : (navState.scene && String(navState.scene.id) === frameIdFromUrl)
      ? navState.scene
      : results[index] ?? null;

  const reviewError = useCallback(
    (message: string) => addToast('error', t('toast_review_save_failed'), message),
    [addToast, t],
  );

  const initialReviewMap = useMemo(() => {
    if (frameIdFromUrl && navState.initialDecision) {
      return { [frameIdFromUrl]: navState.initialDecision };
    }
    return undefined;
  }, [frameIdFromUrl, navState.initialDecision]);

  const { decisions, decide } = useReviews(query, reviewError, initialReviewMap);

  // Keep the URL on the frame being shown, so a copied link and a refresh both land here. `replace`
  // rather than `push`: stepping through ten results must not bury the results page ten entries
  // deep in history, or "Quay lại" stops meaning what it says.
  const goToIndex = useCallback(
    (next: number) => {
      const target = results[next];
      if (!target) return;
      setIndex(next);
      navigate(`/scene/${target.id}`, {
        replace: true,
        state: {
          scene: target,
          searchResults: results,
          currentIndex: next,
          query: query ?? undefined,
        } satisfies SceneDetailNavState,
      });
    },
    [results, navigate, query],
  );

  // `location.key` is 'default' only on a first entry, i.e. someone opened this URL directly. Going
  // "back" from there would leave the app, so send them to the search page instead.
  const handleBack = useCallback(() => {
    if (location.key === 'default') navigate('/');
    else navigate(-1);
  }, [location.key, navigate]);

  // One toast per outcome. The previous version reported success on every path, including the one
  // where the server had refused and the "file" was an error body renamed `.jpg`.
  const handleDownload = useCallback(async () => {
    if (!scene) return;
    const outcome = await downloadFrame(scene.imgSrc, scene.filename);
    if (outcome === 'failed') {
      addToast('error', t('download_btn'), t('download_failed'));
      return;
    }
    if (outcome === 'opened') {
      addToast('info', t('download_btn'), t('download_opened'));
      return;
    }
    addToast('success', t('download_btn'), `Downloaded ${scene.filename}`);
  }, [scene, addToast, t]);

  return (
    <div className="ssp-app-layout">
      <Sidebar
        activeTab="search"
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      <div className="ssp-main-wrapper">
        <TopBar
          pageTitle={t('detail_title')}
          onToggleMenu={() => setIsMobileMenuOpen((prev) => !prev)}
        />

        <div style={{ padding: '16px 32px 0 32px' }}>
          <button type="button" className="ssp-btn-back" onClick={handleBack}>
            <ArrowLeft size={16} />
            <span>{t('btn_back')}</span>
          </button>
        </div>

        <main className="ssp-content-canvas">
          {scene === null ? (
            <div className="ssp-detail-empty">
              <ImageOff size={32} />
              <h2>{t('empty_frame_data_title')}</h2>
              <p>{t('empty_frame_data_desc')}</p>
              <button type="button" className="ssp-btn-main-action" onClick={() => navigate('/')}>
                {t('btn_back_home')}
              </button>
            </div>
          ) : (
            <>
              <div className="ssp-scene-header">
                <div className="ssp-scene-title-group">
                  <h2>{t('frame_detail_header')}</h2>
                  <p>{scene.filename}</p>
                </div>

                {results.length > 1 && (
                  <div className="ssp-pagination-bar">
                    <div className="ssp-page-stepper">
                      <button
                        type="button"
                        className="ssp-btn-step"
                        onClick={() => goToIndex(index - 1)}
                        disabled={index <= 0}
                        aria-label={t('prev_page')}
                      >
                        <ChevronLeft size={18} />
                      </button>
                      <span>
                        {t('result_step', { current: index + 1, total: results.length })}
                      </span>
                      <button
                        type="button"
                        className="ssp-btn-step"
                        onClick={() => goToIndex(index + 1)}
                        disabled={index >= results.length - 1}
                        aria-label={t('next_page')}
                      >
                        <ChevronRight size={18} />
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <div className="ssp-left-col">
                <div className="ssp-frame-card">
                  <img alt={scene.filename} src={scene.imgSrc} />

                  {/* <div className="ssp-glass-metrics">
                    <span className="ssp-glass-metrics-label">{t('similarity_score')}</span>
                    <span className="ssp-glass-metrics-value">{scene.similarity}</span>
                  </div> */}

                  <div className="ssp-frame-camera-badge">
                    <Camera size={14} />
                    <span>
                      {scene.cameraId} · {scene.timestamp}
                    </span>
                  </div>
                </div>

                {scene.rawHit?.moment && (
                  <div className="ssp-moment-card">
                    <MomentPlayer moment={scene.rawHit.moment} />
                  </div>
                )}

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

                {scene.description && (
                  <div className="ssp-analysis-card">
                    <div className="ssp-analysis-title">
                      <BarChart2 size={18} />
                      <span>{t('caption_florence')}</span>
                    </div>
                    <p className="ssp-analysis-desc">"{scene.description}"</p>
                  </div>
                )}
              </div>

              <div className="ssp-right-col">
                <div className="ssp-action-group">
                  <button type="button" className="ssp-btn-main-action" onClick={handleDownload}>
                    <Download size={18} />
                    <span>{t('btn_download_frame')}</span>
                  </button>

                  {query ? (
                    <div className="ssp-detail-review">
                      <ReviewActions
                        decision={decisions[String(scene.id)]}
                        onDecide={(value) => void decide(String(scene.id), value)}
                        size="detail"
                      />
                    </div>
                  ) : (
                    <p className="ssp-detail-review-note">
                      {t('open_from_search_note')}
                    </p>
                  )}
                </div>

                <div className="ssp-meta-card">
                  <div className="ssp-meta-card-header">
                    <h4 className="ssp-meta-card-title">
                      <Info size={16} />
                      <span>{t('meta_card_title')}</span>
                    </h4>
                  </div>
                  <div className="ssp-meta-list">
                    <div className="ssp-meta-item">
                      <span className="ssp-meta-key">{t('similarity_score')}</span>
                      <span className="ssp-meta-val ssp-meta-highlight">{scene.similarity}</span>
                    </div>
                    <div className="ssp-meta-item">
                      <span className="ssp-meta-key">{t('timestamp_lbl')}</span>
                      <span className="ssp-meta-val">{scene.timestamp}</span>
                    </div>
                    <div className="ssp-meta-item">
                      <span className="ssp-meta-key">{t('dataset_lbl')}</span>
                      <span className="ssp-meta-val">{scene.dataset ?? '—'}</span>
                    </div>
                    <div className="ssp-meta-item">
                      <span className="ssp-meta-key">{t('camera_id')}</span>
                      <span className="ssp-meta-val">{scene.cameraId}</span>
                    </div>
                    {scene.rawHit && (
                      <div className="ssp-meta-item">
                        <span className="ssp-meta-key">{t('clip_scene_id')}</span>
                        <span className="ssp-meta-val ssp-meta-mono">{scene.rawHit.scene_id}</span>
                      </div>
                    )}
                    {scene.rawHit && (
                      <div className="ssp-meta-item">
                        <span className="ssp-meta-key">{t('frame_id_lbl')}</span>
                        <span className="ssp-meta-val ssp-meta-mono">{scene.rawHit.frame_id}</span>
                      </div>
                    )}
                  </div>
                </div>

                {scene.labels.length > 0 && (
                  <div className="ssp-tag-cloud-card">
                    <h4 className="ssp-tag-cloud-title">{t('satisfied_conditions_title')}</h4>
                    <div className="ssp-tag-cloud">
                      {scene.labels.map((tag, idx) => (
                        <span key={`${tag}-${idx}`} className="ssp-chip-tag">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </main>
      </div>

      <ToastContainer messages={messages} onDismiss={dismiss} />
    </div>
  );
};

export default SceneDetail;
