/**
 * What the parser understood, shown back to the user.
 *
 * `api-contract.md` asks for this explicitly: an LLM turns the sentence into a structured filter and
 * it will sometimes be wrong. A visible interpretation makes a wrong parse recoverable — the user
 * sees "car" when they meant "truck" and rephrases. Hiding it means they silently get the wrong
 * search and have no way to tell.
 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '../../base/Badge/Badge';
import type { Attribute, Category, QueryConstraint, Relation } from '../../../types/api';
import { attributeLabel, satisfiedLabel, type SupportedLang } from '../../../lib/satisfied';
import './ConstraintChips.css';

interface ConstraintChipsProps {
  constraint: QueryConstraint;
}

export const ConstraintChips: React.FC<ConstraintChipsProps> = ({ constraint }) => {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'en' ? 'en' : 'vi') as SupportedLang;
  const chips: string[] = [];

  for (const object of constraint.objects) {
    chips.push(satisfiedLabel(`object:${object}`, lang));
  }
  for (const [category, relations] of Object.entries(constraint.relations) as [Category, Relation[]][]) {
    for (const relation of relations ?? []) {
      chips.push(satisfiedLabel(`rel:${category}:${relation}`, lang));
    }
  }
  for (const [category, attributes] of Object.entries(constraint.attributes) as [Category, Attribute[]][]) {
    for (const attribute of attributes ?? []) {
      chips.push(attributeLabel(category, attribute, lang));
    }
  }
  for (const [key, value] of Object.entries(constraint.scene)) {
    if (value) {
      const sceneToken = `scene:${key}=${value}`;
      const translated = satisfiedLabel(sceneToken, lang);
      chips.push(translated !== sceneToken ? translated : `${key}: ${value}`);
    }
  }

  const unique = [...new Set(chips)];
  if (unique.length === 0) return null;

  return (
    <div className="constraint-chips">
      <span className="constraint-chips__label">{t('parsed_query_as')}</span>
      <div className="constraint-chips__list">
        {unique.map((chip) => (
          <Badge key={chip} variant="info">
            {chip}
          </Badge>
        ))}
      </div>
    </div>
  );
};

export default ConstraintChips;
