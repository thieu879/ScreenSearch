import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Sidebar } from '../../components/layout/Sidebar/Sidebar';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import { SearchHero } from '../../components/sceneSearch/SearchHero/SearchHero';
import { FilterInfoBar } from '../../components/sceneSearch/FilterInfoBar/FilterInfoBar';
import { ResultCard, type SceneItemData } from '../../components/sceneSearch/ResultCard/ResultCard';
import { frameHitToSceneData } from '../../components/sceneSearch/ResultCard/frameHit';
import { ReviewBar } from '../../components/sceneSearch/ReviewBar/ReviewBar';
import { SceneDetailPanel } from '../../components/sceneSearch/SceneDetailPanel/SceneDetailPanel';
import { ConstraintChips } from '../../components/sceneSearch/ConstraintChips/ConstraintChips';
import { SearchNotice } from '../../components/sceneSearch/SearchNotice/SearchNotice';
import { StartState } from '../../components/sceneSearch/StartState/StartState';
import { ResultsSkeleton } from '../../components/sceneSearch/ResultsSkeleton/ResultsSkeleton';
import { ToastContainer } from '../../components/base/Toast/Toast';
import { useToast } from '../../components/base/Toast/useToast';
import { useReviews } from '../../hooks/useReviews';

import { EXAMPLE_QUERIES } from '../../constants/sceneSearch';
import type { SearchResponse } from '../../types/api';
import { rememberSearch, SearchError, searchScenes } from '../../api/client';
import { loadLastSearch, saveLastSearch } from '../../lib/lastSearch';
import { noticeFor } from '../../lib/searchNotice';

import './SceneSearchAI.css';

type SearchStatusState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'done'; query: string; response: SearchResponse };

export const SceneSearchAI: React.FC = () => {
  const { t, i18n } = useTranslation();
  const [activeTab, setActiveTab] = useState('search');
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  // Read once, lazily, and shared by the two initialisers below — opening a frame and coming back
  // must restore both the query in the box and the results under it, on the first paint.
  const [restored] = useState(loadLastSearch);
  // Seeded from ?q= rather than set from an effect: the box should already hold the query on the
  // first paint when arriving from a link, and setState inside an effect renders twice to get there.
  // An explicit ?q= wins over the restored session — a shared link means that query, not this tab's.
  const [searchQuery, setSearchQuery] = useState(
    () => new URLSearchParams(window.location.search).get('q') ?? restored?.query ?? ''
  );
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [sortBy, setSortBy] = useState('similarity_desc');
  const [selectedDate, setSelectedDate] = useState('');
  // 10, not 20. This is DEFAULT_TOP_K and what every published eval/results figure was measured at,
  // and it is now the number of results actually fetched — the old default of 20 named a page size
  // the server never filled.
  const [pageSize, setPageSize] = useState('10');
  const [selectedScene, setSelectedScene] = useState<SceneItemData | null>(null);
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  // Restoring the stored response rather than re-running it: back from a frame must show the same
  // ten results the reviewer was judging, without spending another parse to get them.
  const [search, setSearch] = useState<SearchStatusState>(() =>
    restored ? { status: 'done', query: restored.query, response: restored.response } : { status: 'idle' }
  );

  const { messages, addToast, dismiss } = useToast();
  const inFlight = useRef<AbortController | null>(null);

  const navigate = useNavigate();

  const reviewError = useCallback(
    (message: string) => addToast('error', t('toast_review_save_failed'), message),
    [addToast, t],
  );
  const { decisions, summary, decide } = useReviews(
    search.status === 'done' ? search.query : null,
    reviewError,
  );
  const handleDecide = useCallback(
    (frameId: string, decision: Parameters<typeof decide>[1]) => void decide(frameId, decision),
    [decide],
  );

  const openSceneDetail = (scene: SceneItemData) => {
    setSelectedScene(scene);
    const currentIndex = currentSceneList.findIndex((item) => item.id === scene.id);
    navigate(`/scene/${scene.id}`, {
      state: {
        scene,
        searchResults: currentSceneList,
        currentIndex: currentIndex >= 0 ? currentIndex : 0,
        // The detail page records verdicts against the same (query, frame) pair the cards use.
        // Without the query it has nothing to key them on and hides the controls rather than
        // pretending to save.
        query: search.status === 'done' ? search.query : undefined,
        initialDecision: decisions[String(scene.id)],
      },
    });
  };

  const closeSceneDetail = () => {
    setIsPanelOpen(false);
  };

  // Read through a ref, not a dependency. `runSearch` is a dependency of the `?q=` auto-search
  // effect below, so letting its identity change whenever the dropdown moves would re-run that
  // effect and fire a second search nobody asked for. The ref gives the current value without
  // touching identity.
  const pageSizeRef = useRef(pageSize);
  // Written in an effect, not during render: `react-hooks/refs` rejects the assignment-in-render
  // form, and it is right to — a ref mutated while rendering is a value React cannot see change.
  // The one-render lag is harmless here, because the only caller that reads this ref instead of
  // passing `topK` explicitly is a *newly typed* search, which happens long after the dropdown's
  // own re-run has committed.
  useEffect(() => {
    pageSizeRef.current = pageSize;
  }, [pageSize]);

  const runSearch = useCallback(
    async (text: string, topK?: number) => {
      const requested = topK ?? (parseInt(pageSizeRef.current, 10) || undefined);
      const trimmed = text.trim();
      if (!trimmed) {
        addToast('info', i18n.t('toast_no_query_title'), i18n.t('toast_no_query_desc'));
        return;
      }

      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      setSearch({ status: 'loading' });

      try {
        const response = await searchScenes(trimmed, requested, controller.signal);
        setSearch({ status: 'done', query: trimmed, response });
        saveLastSearch(trimmed, response);
        // Fire-and-forget: the search has already succeeded, and a history row that fails to
        // save must cost the row and nothing else. `rememberSearch` never throws.
        rememberSearch(trimmed, response.results?.length || 0);
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        const message = error instanceof SearchError ? error.message : i18n.t('toast_search_failed');
        setSearch({ status: 'error', message });
      }
    },
    // `i18n`, not `t`. `runSearch` is a dependency of the `?q=` auto-search effect below, and the
    // hook's `t` gets a new identity every time the language changes — which would re-fire the
    // search, and each one buys two `gpt-4o-mini` calls. The `i18n` instance is stable across a
    // language change and `i18n.t` always reads the current one, so the toasts stay translated
    // without putting a second search on the bill.
    [addToast, i18n]
  );

  // Auto-search when navigated with ?q=. Deferred to a timeout rather than called straight from the
  // effect body: `runSearch` sets loading state synchronously, so invoking it here would cascade a
  // second render before the first has painted. Deferring also gives the effect a real cleanup, so a
  // re-run cancels the pending search instead of racing it.
  React.useEffect(() => {
    const queryParam = new URLSearchParams(window.location.search).get('q');
    if (!queryParam) return;
    const timer = setTimeout(() => void runSearch(queryParam), 0);
    return () => clearTimeout(timer);
  }, [runSearch]);

  const handleSubmit = useCallback(() => {
    void runSearch(searchQuery);
  }, [runSearch, searchQuery]);

  const handleSelectExample = useCallback(
    (query: string) => {
      setSearchQuery(query);
      void runSearch(query);
    },
    [runSearch]
  );

  // Computed results list with full sorting and date filtering.
  const currentSceneList: SceneItemData[] =
    search.status === 'done'
      ? (() => {
          const lang = i18n.language === 'en' ? 'en' : 'vi';
          let list = search.response.results?.map((hit) => frameHitToSceneData(hit, lang)) ?? [];

          // Filter by date if a date is selected
          if (selectedDate) {
            list = list.filter((item) => {
              if (!item.rawHit?.timestamp_s) return false;
              // Converts timestamp_s to ISO date string (YYYY-MM-DD)
              const itemDate = new Date(item.rawHit.timestamp_s * 1000).toISOString().split('T')[0];
              return itemDate === selectedDate;
            });
          }

          // Sorting logic: Similarity (High/Low) and Time (Newest/Oldest)
          if (sortBy === 'similarity_asc') {
            return list.toSorted((a, b) => a.similarityVal - b.similarityVal);
          }
          if (sortBy === 'time_desc' || sortBy === 'newest') {
            return list.toSorted((a, b) => (b.rawHit?.timestamp_s ?? 0) - (a.rawHit?.timestamp_s ?? 0));
          }
          if (sortBy === 'time_asc' || sortBy === 'oldest') {
            return list.toSorted((a, b) => (a.rawHit?.timestamp_s ?? 0) - (b.rawHit?.timestamp_s ?? 0));
          }
          // Default: similarity_desc
          return list.toSorted((a, b) => b.similarityVal - a.similarityVal);
        })()
      : [];

  // No slicing, and no page numbers below: the server returns exactly `top_k` results and this
  // renders all of them. `schemas.py` explains why that is not a viewport — `top_k` is *also* the
  // diversity window, and M2_DESIGN §7 measured widening it to fill pages at a third of the ranking
  // lift (+0.254 -> +0.168 at window 50) for zero additional diversity (5.50 groups either way).
  const totalItems = currentSceneList.length;

  return (
    <div className="ssp-app-container">
      {/* Sidebar */}
      <Sidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Wrapper */}
      <div className="ssp-main-wrapper">
        <TopBar
          pageTitle={t('page_title_search')}
          roleBadge={t('role_badge_engineer')}
          // No `userName`/`userRole`: they were `"Engineer A"` / `"Engineer"`, a placeholder
          // identity that outlived the mock auth it was written for. `TopBar` reads the session.
          onToggleMenu={() => setIsMobileMenuOpen((prev) => !prev)}
        />

        <main className="ssp-main-canvas">
          {/* Search Hero Section */}
          <SearchHero
            value={searchQuery}
            onChange={setSearchQuery}
            onSubmit={handleSubmit}
            isLoading={search.status === 'loading'}
            exampleQueries={EXAMPLE_QUERIES}
            onSelectExample={handleSelectExample}
          />

          {/* Search Notice / Constraints output */}
          {search.status === 'done' && (
            <>
              <ConstraintChips constraint={search.response.constraint} />
              {/* One decision, in `lib/searchNotice.ts`, where it is tested. It used to be three
                * independent conditions here, two of which could fire at once — and the first read
                * `out_of_scope` as a refusal, which stopped being true when Tier 1 made a motion
                * query answerable on a corpus with footage.
                *
                * Titles come from #174, which translated them in the old structure while this branch
                * was replacing the structure. Both halves are kept: its keys, this branch's logic. */}
              {(() => {
                const notice = noticeFor(search.response);
                if (notice.variant === 'none') return null;
                if (notice.variant === 'caveat') {
                  return (
                    <SearchNotice
                      variant="caveat"
                      title={notice.lowConfidence ? t('notice_caveat_title') : t('notice_caveat_warning_title')}
                      message={notice.message}
                    />
                  );
                }
                return (
                  <SearchNotice
                    variant={notice.variant}
                    message={notice.message ?? t('no_matched_frames_fallback')}
                  />
                );
              })()}
            </>
          )}

          {search.status === 'error' && (
            <SearchNotice variant="error" message={search.message} />
          )}

          {/* Nothing has been asked yet, so there is nothing to count, sort or paginate. */}
          {search.status === 'idle' && <StartState />}

          {/* `loading` used to match no branch at all, so the canvas went blank for the length of a
              search — which is ~1s and up, because the query passes through two LLM calls before
              retrieval begins. The placeholder holds the grid's shape so results land in place. */}
          {search.status === 'loading' && (
            <ResultsSkeleton count={parseInt(pageSize, 10) || 10} />
          )}

          {/* Filter & Controls Bar */}
          {search.status === 'done' && (
            <FilterInfoBar
              totalResults={totalItems}
              distinctScenes={search.response.distinct_scenes}
              sortBy={sortBy}
              onSortChange={(sort) => {
                setSortBy(sort);
              }}
              selectedDate={selectedDate}
              onDateChange={(date) => {
                setSelectedDate(date);
              }}
              pageSize={pageSize}
              onPageSizeChange={(sz) => {
                setPageSize(sz);
                // Re-fetch, because this dropdown now decides how many results the server returns
                // rather than how many of an already-fetched list to show. Without this the control
                // is inert until the next search, which is the defect it used to have permanently.
                if (search.status === 'done' && search.query) void runSearch(search.query, parseInt(sz, 10));
              }}
              viewMode={viewMode}
              onViewModeChange={setViewMode}
            />
          )}

          {/* Review Bar */}
          <ReviewBar
            summary={summary}
            judgedHere={currentSceneList.filter((item) => decisions[String(item.id)]).length}
            shownHere={currentSceneList.length}
          />

          {/* Cards Grid */}
          {currentSceneList.length > 0 && (
            <section className={`ssp-results-grid ssp-results-grid--${viewMode}`}>
              {currentSceneList.map((scene) => (
                <ResultCard
                  key={scene.id}
                  scene={scene}
                  viewMode={viewMode}
                  onClick={openSceneDetail}
                  decision={decisions[String(scene.id)]}
                  onDecide={(decision) => handleDecide(String(scene.id), decision)}
                />
              ))}
            </section>
          )}

        </main>
      </div>

      {/* Slide-over Detail Panel */}
      <SceneDetailPanel
        scene={selectedScene}
        isOpen={isPanelOpen}
        onClose={closeSceneDetail}
        decision={selectedScene ? decisions[String(selectedScene.id)] : undefined}
        onDecide={handleDecide}
        onDownloadError={() => addToast('error', t('download_btn'), t('download_failed'))}
      />

      <ToastContainer messages={messages} onDismiss={dismiss} />
    </div>
  );
};

export default SceneSearchAI;
