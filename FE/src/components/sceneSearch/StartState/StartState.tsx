import React from 'react';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';
import './StartState.css';

export const StartState: React.FC = () => {
  const { t } = useTranslation();

  return (
    <div className="start-state" role="status">
      <div className="start-state__icon" aria-hidden="true">
        <Search size={28} />
      </div>
      <p className="start-state__heading">{t('no_search_yet_title')}</p>
      <p className="start-state__message">
        {t('no_search_yet_msg')}
      </p>
    </div>
  );
};

export default StartState;
