/**
 * Fold the sidebar's checkboxes into the one thing the API accepts: a natural-language string.
 *
 * `POST /api/v1/search` takes free text and an LLM parses it into a structured constraint. That
 * keeps the frozen contract intact and means the user sees, in the returned `constraint`, exactly
 * how their filters were understood — which is the point of showing the parse at all.
 *
 * Terms are emitted in **English** even though the UI is Vietnamese: the parser's prompt, its closed
 * category vocabulary and the entire 29-query benchmark it was measured on are English. Sending
 * Vietnamese would be an untested path on the one call in the system that costs money.
 */
import type { FilterItem } from '../types/sceneSearch';
import { MAX_QUERY_LENGTH } from '../api/client';

/** Filter id → the English noun phrase the parser expects. Ids are stable; labels are display-only. */
const OBJECT_TERM: Record<string, string> = {
  pedestrian: 'a pedestrian',
  car: 'a car',
  bike: 'a bicycle',
  truck: 'a truck',
  moto: 'a motorcycle',
};

/** Scene conditions become a trailing clause rather than a noun. */
const WEATHER_TERM: Record<string, string> = {
  night: 'at night',
  rain: 'in the rain',
  sun: 'in bright sunshine',
  fog: 'in fog',
  snow: 'on a snow-covered road',
};

function checkedIn(filters: Record<string, FilterItem[]>, section: string): FilterItem[] {
  return (filters[section] ?? []).filter((item) => item.checked);
}

/**
 * Build the query actually sent.
 *
 * The typed text leads, because it is what the user is thinking about; filters refine it. A filter
 * the map does not know — one the user added themselves via the section's "add" box — contributes
 * its label verbatim, so custom entries still do something rather than being silently ignored.
 *
 * `actions` is not read: those options describe motion across frames, which single-frame retrieval
 * classifies as out of scope by design. The UI disables that section for the same reason.
 */
export function composeQuery(text: string, filters: Record<string, FilterItem[]>): string {
  const typed = text.trim();

  const objects = checkedIn(filters, 'objects').map((item) => OBJECT_TERM[item.id] ?? item.label);
  const weather = checkedIn(filters, 'weather').map((item) => WEATHER_TERM[item.id] ?? item.label);

  const parts: string[] = [];
  if (typed) parts.push(typed);
  if (objects.length) parts.push(`${typed ? 'with ' : ''}${objects.join(' and ')}`);
  if (weather.length) parts.push(weather.join(' and '));

  return parts.join(' ').trim().slice(0, MAX_QUERY_LENGTH);
}

/** Nothing typed and nothing ticked — there is no query to send. */
export function isEmptyQuery(text: string, filters: Record<string, FilterItem[]>): boolean {
  return composeQuery(text, filters).length === 0;
}
