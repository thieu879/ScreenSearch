import React from 'react';
import { Radar } from 'lucide-react';
import './AppHeader.css';

/**
 * Two things were removed here rather than restyled.
 *
 * The avatar was a stock portrait hotlinked from Google's mockup CDN. There is no sign-in, no user
 * and no account in this product, so it depicted a person who does not exist, and it would have
 * broken the first time that URL expired.
 *
 * Two of the three nav links pointed at `#`. The app has one page; links that go nowhere read as a
 * broken build rather than as planned work.
 */
export const AppHeader: React.FC = () => {
  return (
    <header className="app-header">
      <div className="app-header__brand">
        <Radar size={20} className="app-header__radar-icon" />
        <span className="app-header__logo">SCENE_SEARCH_AI</span>
      </div>

      <nav className="app-header__nav" aria-label="Main navigation">
        <span className="app-header__nav-link app-header__nav-link--active" aria-current="page">
          Kho Lưu trữ
        </span>
      </nav>

      <span className="app-header__corpus" title="nuScenes v1.0-mini">
        404 khung hình · 10 clip
      </span>
    </header>
  );
};

export default AppHeader;
