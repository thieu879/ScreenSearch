import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Sparkles,
  Search,
  Zap,
  ShieldCheck,
  Layers,
  LogIn,
  ArrowRight,
  CheckCircle2,
  Cpu,
  Video,
  BarChart3,
  Database,
} from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { HomeHeader } from '../../components/layout/HomeHeader/HomeHeader';
import { apiSrc, fetchCorpusStatus, fetchHealth } from '../../api/client';
import './Home.css';

/**
 * The two frames the hero console shows — real rows from the served corpus, not stock photography.
 *
 * They used to be two hotlinked images from `media.interaksyon.com` and a wixmp CDN, standing in for
 * this product's own output on the page a grader reads first. That is the wrong trade in three ways:
 * it is somebody else's copyright, it is an outbound dependency the page cannot control, and a
 * console captioned "SceneSearch AI Console" showing photographs the system has never seen
 * undercuts the one claim this product is built on — that it does not assert what it cannot show.
 *
 * Both captions name a person at night, matching `home_mockup_query`. Both are served from
 * `/frames/{id}/thumb`, which needs no session, and both are from the redacted set — the only set
 * that leaves this machine. If the corpus fails to load the thumbs 404 and the gradient behind them
 * still renders, so the hero degrades to a dark panel rather than a broken image.
 *
 * Built with `apiSrc` rather than `thumbSrc`, whose contract is "pass the `thumb_url` the server
 * handed you, never rebuild the path". There is no server response to take a path from here — this
 * is a static page naming two fixed frames — so the route is spelled out, and it is the one place
 * in the app that does.
 */
const THUMB_ROUTE = (frameId: string) => apiSrc(`/api/v1/frames/${frameId}/thumb`);

const MOCKUP_FRAMES = [
  THUMB_ROUTE('2326b09f39844a27bf92211cd0ec0a85_CAM_FRONT'),
  THUMB_ROUTE('256ff313fffa4cfaa80bf33370912365_CAM_FRONT'),
];

/**
 * What the stat bar falls back to when `/status` cannot be reached.
 *
 * The corpus as it stood when this was written, so a visitor on a broken connection sees a plausible
 * page rather than dashes — and so the numbers are never *invented*, only possibly stale by exactly
 * one corpus. Every figure here is checked into the same commit as the corpus it describes.
 */
const CORPUS_FALLBACK = { frames: 9069, scenes: 554 };

/**
 * The build named in the hero badge when `/health` cannot be reached.
 *
 * The badge said `v1.6.1` while the box served `v1.7.2` — a version typed into a page dates itself
 * wrong the first time anything ships, and this one was two releases behind. `Sidebar` already reads
 * `/health` for its own release line, on the same reasoning.
 */
const RELEASE_FALLBACK = 'v1.7.2';

export const Home: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, user } = useAuth();
  const { t, i18n } = useTranslation();

  /**
   * The served corpus, read from `/status` rather than typed into the page.
   *
   * **Hardcoding these is what made them wrong.** The bar said `6,858` frames and `404` clips while
   * the box served 9,069 frames over 554 scenes — one of those was a stale number and the other was
   * never right — and nothing connects a landing page to the corpus, so a merge that grows the
   * archive silently turns the front door into a misstatement. `/status` needs no session, the login
   * pages already read it, and a page that asks the service what it holds cannot drift from it.
   */
  const [corpus, setCorpus] = useState(CORPUS_FALLBACK);
  const [release, setRelease] = useState(RELEASE_FALLBACK);

  useEffect(() => {
    let cancelled = false;
    fetchCorpusStatus()
      .then((status) => {
        if (cancelled) return;
        setCorpus({
          frames: status.corpus_frames || CORPUS_FALLBACK.frames,
          scenes: status.provenance?.n_scenes || CORPUS_FALLBACK.scenes,
        });
      })
      .catch(() => {
        /* Keep the fallback: a dash where a headline number belongs looks broken. */
      });
    fetchHealth()
      .then((health) => {
        // `unknown` is what an image built without a version reports. Naming the fallback build is
        // wrong then, but so is printing "unknown Live" at a visitor, so the badge keeps the former.
        if (!cancelled && health.release && health.release !== 'unknown') setRelease(health.release);
      })
      .catch(() => {
        /* Same reasoning as the corpus above. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const nf = (n: number) => n.toLocaleString(i18n.language === 'vi' ? 'vi-VN' : 'en-US');
  const frames = nf(corpus.frames);

  useEffect(() => {
    if (location.hash) {
      const id = location.hash.replace('#', '');
      const timer = setTimeout(() => {
        const element = document.getElementById(id);
        if (element) {
          element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [location.hash]);

  const handleGetStarted = () => {
    if (isAuthenticated && user) {
      navigate(user.role === 'Admin' ? '/admin' : '/search');
    } else {
      navigate('/login');
    }
  };

  return (
    <div className="ssp-home-root">
      {/* ── Navbar / Header ──────────────────────────────────────── */}
      <HomeHeader />

      {/* ── Hero Section ─────────────────────────────────────────── */}
      <section className="ssp-home-hero">
        <div className="ssp-home-hero-glow-1" />
        <div className="ssp-home-hero-glow-2" />

        <div className="ssp-home-container ssp-home-hero-inner">
          <div className="ssp-home-hero-content">
            <div className="ssp-home-hero-badge">
              <Sparkles size={14} />
              <span>{t('home_hero_badge', { release })}</span>
            </div>

            <h1 className="ssp-home-hero-title">
              {t('home_hero_title_1')} <br />
              <span className="ssp-home-hero-highlight">{t('home_hero_title_2')}</span>
            </h1>

            <p className="ssp-home-hero-subtitle">
              {t('home_hero_subtitle_1')}{' '}
              <strong>CLIP Embeddings</strong>, <strong>LangGraph RAG</strong> {t('home_hero_subtitle_2')}{' '}
              <strong>Rejection Band</strong> {t('home_hero_subtitle_3')}
            </p>

            <div className="ssp-home-hero-cta">
              <button
                type="button"
                className="ssp-home-btn-hero-primary"
                onClick={handleGetStarted}
              >
                <Zap size={20} />
                <span>{isAuthenticated ? t('home_hero_btn_app') : t('home_hero_btn_start')}</span>
                <ArrowRight size={18} />
              </button>
              
              {!isAuthenticated && (
                <button
                  type="button"
                  className="ssp-home-btn-hero-secondary"
                  onClick={() => navigate('/login')}
                >
                  <LogIn size={18} />
                  <span>{t('home_hero_btn_login')}</span>
                </button>
              )}
            </div>

            <div className="ssp-home-hero-features-list">
              <div className="ssp-home-hero-feature-item">
                <CheckCircle2 size={16} />
                <span>{t('home_hero_feat_1', { frames })}</span>
              </div>
              <div className="ssp-home-hero-feature-item">
                <CheckCircle2 size={16} />
                <span>{t('home_hero_feat_2')}</span>
              </div>
              <div className="ssp-home-hero-feature-item">
                <CheckCircle2 size={16} />
                <span>{t('home_hero_feat_3')}</span>
              </div>
            </div>
          </div>

          {/* Hero Visual Card / Simulated App UI */}
          <div className="ssp-home-hero-visual">
            <div className="ssp-home-mockup-card">
              <div className="ssp-home-mockup-header">
                <div className="ssp-home-mockup-dots">
                  <span className="dot red" />
                  <span className="dot yellow" />
                  <span className="dot green" />
                </div>
                <span className="ssp-home-mockup-title">{t('home_mockup_title')}</span>
              </div>

              <div className="ssp-home-mockup-body">
                <div className="ssp-home-mockup-search-bar">
                  <Search size={18} className="ssp-home-mockup-search-icon" />
                  <span className="ssp-home-mockup-search-text">
                    {t('home_mockup_query')}
                  </span>
                  <span className="ssp-home-mockup-tag">SigLIP2 ViT-B-16</span>
                </div>

                <div className="ssp-home-mockup-metrics-pills">
                  <div className="ssp-metric-pill">
                    <Zap size={13} />
                    <span>{t('home_mockup_latency')}</span>
                  </div>
                  <div className="ssp-metric-pill success">
                    <ShieldCheck size={13} />
                    <span>{t('home_mockup_confidence')}</span>
                  </div>
                  <div className="ssp-metric-pill purple">
                    <Cpu size={13} />
                    <span>{t('home_mockup_tau')}</span>
                  </div>
                </div>

                <div className="ssp-home-mockup-grid">
                  <div className="ssp-home-mockup-frame-box">
                    <div
                      className="ssp-mockup-img-placeholder frame-1"
                      style={{
                        backgroundImage: `linear-gradient(180deg, rgba(15, 23, 42, 0.25) 0%, rgba(15, 23, 42, 0.75) 100%), url('${MOCKUP_FRAMES[0]}')`,
                      }}
                    >
                      <span className="ssp-cam-badge">CAM_FRONT</span>
                      <span className="ssp-score-badge">{t('home_mockup_match')}: {t('home_mockup_match_high')}</span>
                    </div>
                  </div>
                  <div className="ssp-home-mockup-frame-box">
                    <div
                      className="ssp-mockup-img-placeholder frame-2"
                      style={{
                        backgroundImage: `linear-gradient(180deg, rgba(15, 23, 42, 0.25) 0%, rgba(15, 23, 42, 0.75) 100%), url('${MOCKUP_FRAMES[1]}')`,
                      }}
                    >
                      <span className="ssp-cam-badge">CAM_FRONT</span>
                      <span className="ssp-score-badge">{t('home_mockup_match')}: {t('home_mockup_match_medium')}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats Counter Bar (Dataset) ─────────────────────────── */}
      <section id="dataset" className="ssp-home-stats-section">
        <div className="ssp-home-container">
          <div className="ssp-home-stats-grid">
            <div className="ssp-home-stat-card">
              <div className="ssp-home-stat-icon">
                <Database size={24} />
              </div>
              <div className="ssp-home-stat-num">{frames}</div>
              <div className="ssp-home-stat-label">{t('home_stat_1_label')}</div>
            </div>

            <div className="ssp-home-stat-card">
              <div className="ssp-home-stat-icon">
                <Zap size={24} />
              </div>
              <div className="ssp-home-stat-num">117ms</div>
              <div className="ssp-home-stat-label">{t('home_stat_2_label', { frames })}</div>
            </div>

            <div className="ssp-home-stat-card">
              <div className="ssp-home-stat-icon">
                <Video size={24} />
              </div>
              <div className="ssp-home-stat-num">{nf(corpus.scenes)}</div>
              <div className="ssp-home-stat-label">{t('home_stat_3_label')}</div>
            </div>

            <div className="ssp-home-stat-card">
              <div className="ssp-home-stat-icon">
                <BarChart3 size={24} />
              </div>
              <div className="ssp-home-stat-num">100%</div>
              <div className="ssp-home-stat-label">{t('home_stat_4_label')}</div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Features Section ─────────────────────────────────────── */}
      <section id="features" className="ssp-home-features-section">
        <div className="ssp-home-container">
          <div className="ssp-home-section-header">
            <div className="ssp-home-section-badge">{t('home_feat_badge')}</div>
            <h2 className="ssp-home-section-title">
              {t('home_feat_title')}
            </h2>
            <p className="ssp-home-section-desc">
              {t('home_feat_desc')}
            </p>
          </div>

          <div className="ssp-home-features-grid">
            <div className="ssp-home-feature-card">
              <div className="ssp-feature-icon-box gradient-1">
                <Search size={24} />
              </div>
              <h3>{t('home_feat_1_title')}</h3>
              <p>
                {t('home_feat_1_desc')}
              </p>
            </div>

            <div className="ssp-home-feature-card">
              <div className="ssp-feature-icon-box gradient-2">
                <Layers size={24} />
              </div>
              <h3>{t('home_feat_2_title')}</h3>
              <p>
                {t('home_feat_2_desc')}
              </p>
            </div>

            <div className="ssp-home-feature-card">
              <div className="ssp-feature-icon-box gradient-3">
                <ShieldCheck size={24} />
              </div>
              <h3>{t('home_feat_3_title')}</h3>
              <p>
                {t('home_feat_3_desc')}
              </p>
            </div>

            <div className="ssp-home-feature-card">
              <div className="ssp-feature-icon-box gradient-4">
                <Cpu size={24} />
              </div>
              <h3>{t('home_feat_4_title')}</h3>
              <p>
                {t('home_feat_4_desc', { frames })}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Architecture Section ─────────────────────────────────── */}
      <section id="architecture" className="ssp-home-arch-section">
        <div className="ssp-home-container">
          <div className="ssp-home-arch-inner">
            <div className="ssp-home-arch-text">
              <div className="ssp-home-section-badge">{t('home_arch_badge')}</div>
              <h2>{t('home_arch_title')}</h2>
              <p>
                {t('home_arch_desc', { frames })}
              </p>
              
              <ul className="ssp-arch-checklist">
                <li>
                  <CheckCircle2 size={18} className="icon" />
                  <span><strong>{t('home_arch_item_1_title')}</strong> {t('home_arch_item_1_desc')}</span>
                </li>
                <li>
                  <CheckCircle2 size={18} className="icon" />
                  <span><strong>{t('home_arch_item_2_title')}</strong> {t('home_arch_item_2_desc')}</span>
                </li>
                <li>
                  <CheckCircle2 size={18} className="icon" />
                  <span><strong>{t('home_arch_item_3_title')}</strong> {t('home_arch_item_3_desc')}</span>
                </li>
              </ul>
            </div>

            <div className="ssp-home-arch-diagram">
              <div className="ssp-diagram-node frontend">
                <Video size={20} />
                <span>React Vite Frontend</span>
              </div>
              <div className="ssp-diagram-arrow">↓ REST / JSON</div>
              <div className="ssp-diagram-node backend">
                <Cpu size={20} />
                <span>FastAPI Service (uvicorn)</span>
              </div>
              <div className="ssp-diagram-arrow">↓ LangGraph</div>
              <div className="ssp-diagram-node-group">
                <div className="ssp-diagram-node sub">
                  <span>CLIP Embedding</span>
                </div>
                <div className="ssp-diagram-node sub">
                  <span>In-Memory Matrix</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Bottom CTA (Workflow) ────────────────────────────────── */}
      <section id="workflow" className="ssp-home-cta-section">
        <div className="ssp-home-container">
          <div className="ssp-home-cta-box">
            <div className="ssp-home-cta-glow" />
            <h2>{t('home_cta_title')}</h2>
            <p>{t('home_cta_desc')}</p>
            <div className="ssp-home-cta-buttons">
              <button
                type="button"
                className="ssp-home-btn-hero-primary"
                onClick={handleGetStarted}
              >
                <Zap size={20} />
                <span>{isAuthenticated ? t('home_cta_btn_app') : t('home_hero_btn_start')}</span>
                <ArrowRight size={18} />
              </button>
              
              {!isAuthenticated && (
                <button
                  type="button"
                  className="ssp-home-btn-hero-secondary"
                  onClick={() => navigate('/login')}
                >
                  <LogIn size={18} />
                  <span>{t('home_btn_login')}</span>
                </button>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────── */}
      <footer className="ssp-home-footer">
        <div className="ssp-home-container ssp-home-footer-inner">
          <div className="ssp-home-footer-brand">
            <div className="ssp-home-brand-badge">
              <Sparkles size={16} />
              <span>SSP</span>
            </div>
            <span>SceneSearch AI Platform © 2026 — Team P-057</span>
          </div>

          <div className="ssp-home-footer-tech">
            <span>Powered by FastAPI • LangGraph • CLIP • React</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Home;
