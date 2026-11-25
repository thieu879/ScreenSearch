import React, { useState } from 'react';
import { Plus } from 'lucide-react';
import { Checkbox } from '../../base/Checkbox/Checkbox';
import type { FilterItem, FilterSectionDef } from '../../../types/sceneSearch';
import './FilterSection.css';

interface FilterSectionProps {
  section: FilterSectionDef;
  items: FilterItem[];
  onToggle: (id: string) => void;
  onAddItem: (label: string) => void;
}

export const FilterSection: React.FC<FilterSectionProps> = ({
  section,
  items,
  onToggle,
  onAddItem,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [newValue, setNewValue] = useState('');
  const Icon = section.icon;

  const handleAdd = () => {
    const v = newValue.trim();
    if (!v) return;
    onAddItem(v);
    setNewValue('');
  };

  const visibleItems = expanded ? items : items.slice(0, 4);

  // A disabled section still shows its options — greyed out, with the reason. Hiding them would
  // leave an engineer who wants these queries assuming nobody considered them, rather than
  // understanding that single-frame retrieval cannot answer them.
  if (section.disabled) {
    return (
      <div className="filter-section filter-section--disabled">
        <div className="filter-section__header">
          <Icon size={15} className="filter-section__icon" />
          <span className="filter-section__title">{section.title}</span>
        </div>

        <ul className="filter-section__disabled-list">
          {items.map((item) => (
            <li key={item.id} className="filter-section__disabled-item">
              {item.label}
            </li>
          ))}
        </ul>

        {section.disabledNote && <p className="filter-section__disabled-note">{section.disabledNote}</p>}
      </div>
    );
  }

  return (
    <div className="filter-section">
      {/* Section title */}
      <div className="filter-section__header">
        <Icon size={15} className="filter-section__icon" />
        <span className="filter-section__title">{section.title}</span>
      </div>

      {/* Add custom filter */}
      <div className="filter-section__add">
        <input
          className="filter-section__add-input"
          type="text"
          placeholder="Thêm tùy chọn..."
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleAdd();
          }}
        />
        <button
          className="filter-section__add-btn"
          onClick={handleAdd}
          title="Thêm"
        >
          <Plus size={15} />
        </button>
      </div>

      {/* Checkbox list */}
      <div className="filter-section__list">
        {visibleItems.map((item) => (
          <Checkbox
            key={item.id}
            id={`${section.key}-${item.id}`}
            label={item.label}
            checked={item.checked}
            onChange={() => onToggle(item.id)}
          />
        ))}
      </div>

      {/* Expand/collapse */}
      {items.length > 4 && (
        <button
          className="filter-section__expand-btn"
          onClick={() => setExpanded((p) => !p)}
        >
          {expanded ? 'Thu gọn ↑' : `Xem thêm (${items.length - 4}) ↓`}
        </button>
      )}
    </div>
  );
};

export default FilterSection;
