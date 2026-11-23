// lib/selection.mjs: catalog text from PROMPT 1, reply parsing, message shape.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { supportedTypeCatalogText, parseSelectionReply, buildSelectionMessages } from '../lib/tools/mermaid/lib/selection.mjs';

test('catalog offers exactly the 25 allowed types (28 supported minus 3 excluded, D29)', () => {
  assert.equal(supportedTypeCatalogText().count, 25);
});

test('catalog excludes the 4 known-unsupported types', () => {
  const { text } = supportedTypeCatalogText();
  for (const name of ['Architecture', 'Mindmap', 'Agentflow', 'Use case']) assert.ok(!text.includes(`- ${name} [`), name);
});

test('catalog lines carry PROMPT 1 descriptions', () => {
  assert.match(supportedTypeCatalogText().text, /- Flowchart \[Mermaid: Flowchart \(`flowchart`\)\]: General-purpose/);
});

test('parses plain JSON', () => {
  const r = parseSelectionReply('{"diagramType":"Sequence diagram","rationale":"x"}');
  assert.equal(r.outcome, 'parsed');
  assert.equal(r.entry.name, 'Sequence diagram');
  assert.equal(r.rationale, 'x');
});

test('parses fenced JSON and resolves a Mermaid keyword', () => {
  assert.equal(parseSelectionReply('```json\n{"diagramType":"erDiagram","rationale":"r"}\n```').entry.name, 'ERD');
});

test('an unsupported type defaults to Flowchart with a reason', () => {
  const r = parseSelectionReply('{"diagramType":"Mindmap"}');
  assert.equal(r.outcome, 'defaulted_to_flowchart');
  assert.equal(r.entry.name, 'Flowchart');
  assert.match(r.reason, /not a supported/);
});

test('a non-JSON reply defaults to Flowchart', () => {
  const r = parseSelectionReply('I think a flowchart');
  assert.equal(r.outcome, 'defaulted_to_flowchart');
  assert.match(r.reason, /no JSON/);
});

test('selection messages: system catalog + user hint and document', () => {
  const m = buildSelectionMessages('DOC', 'focus');
  assert.equal(m.length, 2);
  assert.equal(m[0].role, 'system');
  assert.ok(m[1].content.includes('focus') && m[1].content.endsWith('DOC'));
});
