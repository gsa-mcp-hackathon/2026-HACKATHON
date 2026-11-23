// Diagram types this server never uses, by choice (decision D29).
//
// Different from UNSUPPORTED_DIAGRAM_TYPES in the verbatim lib/prompts.mjs,
// which lists types the renderer cannot draw. These types render fine; we
// just do not want them. Both lists have the same effect: the model is
// never offered the type, a model reply naming it is not accepted, and a
// caller's diagramType naming it is ignored (the type is chosen
// automatically instead).
//
// To exclude a type: add its exact DIAGRAM_CATALOG name below (the unit
// tests fail on a misspelled name). To allow it again: delete the entry.
import { DIAGRAM_CATALOG, findDiagramCatalogEntry } from './prompts.mjs';

export const EXCLUDED_DIAGRAM_TYPES = [
  { name: 'TreeView', reason: 'Not wanted (user, 2026-11-05). One row per item, so long lists exceed the 8,000 px render limit even after a resize (sample.pdf: 2400x19307, resized 2400x16768, startup-20261105T215006Z-d97997).', decidedAt: '2026-11-05' },
  { name: 'Treemap', reason: 'Not wanted (user, 2026-11-05).', decidedAt: '2026-11-05' },
  { name: 'Cynefin', reason: 'Not wanted (user, 2026-11-05).', decidedAt: '2026-11-05' },
];

const EXCLUDED_NAMES = new Set(EXCLUDED_DIAGRAM_TYPES.map((t) => t.name));

// Excluded names that are not catalog names (a typo would silently exclude nothing).
export function unknownExcludedNames() {
  const catalog = new Set(DIAGRAM_CATALOG.map((e) => e.name));
  return EXCLUDED_DIAGRAM_TYPES.map((t) => t.name).filter((n) => !catalog.has(n));
}

// Catalog entry for a type name or keyword, or null when it is unknown,
// unsupported by the renderer, or excluded here. Every type choice in the
// pipeline goes through this function.
export function findAllowedDiagramType(name) {
  const entry = findDiagramCatalogEntry(name);
  return entry && !EXCLUDED_NAMES.has(entry.name) ? entry : null;
}

// Why a name was not accepted: 'excluded', 'unsupported' (renderer or
// unknown name), or null when it is allowed.
export function rejectionReason(name) {
  if (findAllowedDiagramType(name)) return null;
  const entry = findDiagramCatalogEntry(name);
  return entry && EXCLUDED_NAMES.has(entry.name) ? 'excluded' : 'unsupported';
}
