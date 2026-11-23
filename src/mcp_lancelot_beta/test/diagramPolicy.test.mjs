// lib/diagramPolicy.mjs (D29): excluded diagram types are never offered to
// the model, never accepted from it, and never accepted from a caller.
// Uses the real prompts.mjs and PROMPTS/ files (no npm packages needed).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LIB } from './helpers.mjs';

const { EXCLUDED_DIAGRAM_TYPES, unknownExcludedNames, findAllowedDiagramType, rejectionReason } = await import(LIB('diagramPolicy.mjs'));
const { DIAGRAM_CATALOG, UNSUPPORTED_DIAGRAM_TYPES, findDiagramCatalogEntry, buildDiagramSyntaxPrompt } = await import(LIB('prompts.mjs'));
const { DEFAULT_DIAGRAM_TYPE, buildSelectionMessages, parseSelectionReply, supportedTypeCatalogText } = await import(LIB('selection.mjs'));

const EXCLUDED = EXCLUDED_DIAGRAM_TYPES.map((t) => t.name);
const MENTION = /treeview|treemap|cynefin/i;

test('the list is exactly TreeView, Treemap, Cynefin, all real catalog names', () => {
  assert.deepEqual(EXCLUDED, ['TreeView', 'Treemap', 'Cynefin']);
  assert.deepEqual(unknownExcludedNames(), []);
});

test('the default type is never excluded', () => {
  assert.ok(findAllowedDiagramType(DEFAULT_DIAGRAM_TYPE));
});

test('names and keywords of excluded types are refused; others behave as before', () => {
  for (const name of ['TreeView', 'treeview', 'tree', 'Treemap', 'treemap', 'Cynefin', 'cynefin']) {
    assert.ok(findDiagramCatalogEntry(name), `${name} is in the catalog`);
    assert.equal(findAllowedDiagramType(name), null, name);
    assert.equal(rejectionReason(name), 'excluded', name);
  }
  for (const kw of DIAGRAM_CATALOG.filter((e) => EXCLUDED.includes(e.name)).flatMap((e) => e.keywords)) {
    assert.equal(findAllowedDiagramType(kw), null, `keyword ${kw}`);
  }
  assert.equal(rejectionReason('Mindmap'), 'unsupported');
  assert.equal(rejectionReason('no such type'), 'unsupported');
  assert.equal(findAllowedDiagramType('Flowchart').name, 'Flowchart');
  assert.equal(rejectionReason('Flowchart'), null);
});

test('the type-selection prompt offers 25 types and never mentions an excluded one', () => {
  const { text, count } = supportedTypeCatalogText();
  const expected = DIAGRAM_CATALOG.length - UNSUPPORTED_DIAGRAM_TYPES.length - EXCLUDED.length;
  assert.equal(expected, 25);
  assert.equal(count, expected);
  assert.equal(text.split('\n').length, expected);
  const [system, user] = buildSelectionMessages('A small document.', 'focus');
  assert.doesNotMatch(system.content, MENTION);
  assert.doesNotMatch(user.content, MENTION);
  assert.match(system.content, /- Flowchart \[/);
});

test('no Mermaid-writing prompt for an allowed type mentions an excluded type', () => {
  const allowed = DIAGRAM_CATALOG.filter((e) => findAllowedDiagramType(e.name));
  assert.equal(allowed.length, 25);
  for (const e of allowed) assert.doesNotMatch(buildDiagramSyntaxPrompt(e.name), MENTION, e.name);
});

test('a model reply naming an excluded type is not accepted', () => {
  for (const name of ['TreeView', 'tree', 'Treemap', 'treemap', 'Cynefin']) {
    const r = parseSelectionReply(JSON.stringify({ diagramType: name, rationale: 'r' }));
    assert.equal(r.outcome, 'defaulted_to_flowchart', name);
    assert.equal(r.entry.name, 'Flowchart');
    assert.match(r.reason, /is an excluded diagram type/);
  }
  assert.match(parseSelectionReply('{"diagramType":"Mindmap"}').reason, /is not a supported diagram type/);
});
