// lib/pipeline.mjs: fallback chain, retry rules, repair, render outcomes, tracing.
// render.mjs, databricksAuth.mjs, and fetch are mocked (no npm packages needed).
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { LIB, installFetchQueue, selectReply, mermaidReply } from './helpers.mjs';

class ValidationError extends Error {}
// Exact message from startup run startup-20261105T211435Z-5fd823 (Claude Haiku 4.5, sample.pdf).
const TOO_LARGE_MSG =
  'PNG rasterization failed: rendered diagram would be too large to rasterize safely (~2400x10464px, max 8000px per side) - try a simpler diagram (fewer nodes/subgraphs)';
const renderQueue = [];
mock.module(LIB('render.mjs'), {
  namedExports: {
    ValidationError,
    renderMermaid: async () => {
      const next = renderQueue.shift();
      if (next === 'bad') throw new ValidationError('failed to render diagram: Parse error on line 2');
      if (next === 'pngfail') return { svg: '<svg/>', pngFailed: true, pngError: 'PNG rasterization failed: SIGABRT' };
      if (next === 'toolarge') return { svg: '<svg/>', pngFailed: true, pngError: TOO_LARGE_MSG };
      if (next === 'toolarge-slow') {
        await new Promise((resolve) => setTimeout(resolve, 11_000));
        return { svg: '<svg/>', pngFailed: true, pngError: TOO_LARGE_MSG };
      }
      // 100 x 50 PNG header is enough for pngInfo
      return { png: Buffer.from('89504e470d0a1a0a0000000d49484452000000640000003208020000', 'hex').toString('base64') };
    },
  },
});
mock.module(LIB('databricksAuth.mjs'), { namedExports: { getAccessToken: async () => 'tok', getWorkspaceHost: () => 'https://example.invalid' } });
process.env.LLM_ENDPOINT_PRIMARY = 'gemini';
process.env.LLM_ENDPOINT_FALLBACK = 'grok';
process.env.TRACE_VOLUME = 'users.tom_jacobson.lancelot_traces';
process.env.APP_TRACE_LEVEL = 'debug';
const net = installFetchQueue();
const { runPipeline, extractMermaid, replyText, parseTooLarge, resizeInstruction, countContentLines, fixKnownSyntax, diagramKeyword } = await import(LIB('pipeline.mjs'));
const { Tracer } = await import(LIB('tracer.mjs'));

const start = (fetchItems, renders) => {
  net.queue.length = 0;
  net.queue.push(...fetchItems);
  renderQueue.length = 0;
  renderQueue.push(...renders);
  return new Tracer('call');
};
const budget = (ms = 70_000) => Date.now() + ms;

test('fixKnownSyntax: the V9 journey (2026-11-06 attempt 1) and what it must not touch', () => {
  // Verbatim model output from call-20261106T220755Z-8f4663/artifacts/attempt1.mmd (first two sections).
  const v9 = [
    'journey',
    "    title\u2800Pokemon Trainer's First Week",
    '    section Day 1: Getting Started',
    '      Choose Starter Pokemon: 5: Trainer',
    '      Receive Pokedex: 4: Trainer',
    '    section Days 6-7: Mt. Moon & Gym Challenge',
    '      Defeat Brock - Boulder Badge: 5: Trainer',
  ].join('\n');
  const { source, fixes } = fixKnownSyntax(v9);
  assert.deepEqual(source.split('\n'), [
    'journey',
    "    title Pokemon Trainer's First Week",
    '    section Day 1 - Getting Started',
    '      Choose Starter Pokemon: 5: Trainer',
    '      Receive Pokedex: 4: Trainer',
    '    section Days 6-7 - Mt. Moon & Gym Challenge',
    '      Defeat Brock - Boulder Badge: 5: Trainer',
  ]);
  assert.deepEqual(fixes, [{ rule: 'blank-like-to-space', count: 1 }, { rule: 'journey-section-punctuation', count: 2 }]);
  // every section line is now free of the characters the journey lexer refuses
  for (const l of source.split('\n').filter((x) => /^\s*section\s/.test(x))) assert.doesNotMatch(l.replace(/^\s*section\s+/, ''), /[:;#]/);
  assert.equal(fixKnownSyntax(source).fixes.length, 0, 'idempotent');

  // other punctuation and trailing colons
  assert.equal(fixKnownSyntax('journey\n  title Week #1; draft\n  section Step 2:\n    A: 5: Me').source,
    'journey\n  title Week 1, draft\n  section Step 2\n    A: 5: Me');
  // sections in other diagram types are not changed (gantt and timeline have their own rules)
  const gantt = 'gantt\n  dateFormat YYYY-MM-DD\n  section Phase 1: Plan\n    Task A :a1, 2026-01-01, 3d';
  assert.deepEqual(fixKnownSyntax(gantt), { source: gantt, fixes: [] });
  const flow = 'flowchart TD\n  A["section a: b"] --> B';
  assert.deepEqual(fixKnownSyntax(flow), { source: flow, fixes: [] });
  // front matter and directives before the keyword
  assert.equal(diagramKeyword('---\nconfig:\n  theme: base\n---\n%%{init: {}}%%\njourney\n  title x'), 'journey');
  assert.equal(diagramKeyword('%% c\nflowchart LR\nA-->B'), 'flowchart');
  assert.equal(fixKnownSyntax('---\ntitle: a: b\n---\njourney\n  section S: 1\n    A: 5: Me').source, '---\ntitle: a: b\n---\njourney\n  section S - 1\n    A: 5: Me');
  // zero-width characters are removed
  assert.deepEqual(fixKnownSyntax('flowchart TD\n  A\u200B-->B\uFEFF'), { source: 'flowchart TD\n  A-->B', fixes: [{ rule: 'zero-width-removed', count: 2 }] });
});

test('extractMermaid and replyText', () => {
  assert.deepEqual(extractMermaid('blah\n```mermaid\nflowchart TD\nA-->B\n```\nmore'), { source: 'flowchart TD\nA-->B', fenced: true });
  assert.equal(extractMermaid('flowchart TD\nA-->B').fenced, false);
  assert.equal(replyText([{ type: 'reasoning', summary: [] }, { type: 'text', text: 'hi' }]), 'hi');
});

test('requests never send temperature', async () => {
  const tr = start([selectReply('Flowchart'), mermaidReply('flowchart TD\nA-->B')], ['ok']);
  await runPipeline({ text: 'doc', deadlineAt: budget(), tracer: tr });
  for (const rec of tr.llmRecords) assert.ok(!('temperature' in rec.request), rec.step);
});

test('happy path: select, generate, render; every step traced', async () => {
  const tr = start([selectReply('Flowchart'), mermaidReply('flowchart TD\nA-->B')], ['ok']);
  const rec = {};
  const r = await runPipeline({ text: 'doc', deadlineAt: budget(), tracer: tr, record: rec, artifactPrefix: 'sample.pdf/', label: 'sample.pdf' });
  assert.equal(r.diagramType, 'Flowchart');
  assert.equal(r.repaired, false);
  assert.equal(r.width, 100);
  assert.equal(r.height, 50);
  assert.deepEqual(tr.trace.llm.map((l) => l.step), ['select', 'generate']);
  assert.ok(tr.artifacts.has('sample.pdf/attempt1.mmd') && tr.artifacts.has('sample.pdf/output.png'));
  assert.equal(rec.render[0].outcome, 'ok');
});

test('primary 503 falls back to the fallback; both attempts traced', async () => {
  const tr = start([{ status: 503, body: 'overloaded' }, selectReply('Sequence diagram'), mermaidReply('sequenceDiagram\nA->>B: hi')], ['ok']);
  const r = await runPipeline({ text: 'doc', deadlineAt: budget(), tracer: tr });
  assert.equal(r.diagramType, 'Sequence diagram');
  const [first, second] = tr.trace.llm;
  assert.equal(first.endpoint, 'gemini');
  assert.equal(first.errorClass, 'http_503');
  assert.equal(second.endpoint, 'grok');
  assert.equal(second.fallback, true);
  assert.equal(tr.llmRecords[0].errorBody, 'overloaded');
});

test('a 400 is a configuration error: LLM_ERROR, no fallback', async () => {
  const tr = start([{ status: 400, body: 'bad param' }], []);
  await assert.rejects(runPipeline({ text: 'doc', deadlineAt: budget(), tracer: tr }), (e) => e.code === 'LLM_ERROR' && e.stage === 'select');
  assert.equal(tr.trace.llm.length, 1);
  assert.equal(net.queue.length, 0);
});

test('primary timeout with too little budget left: fallback skipped, LLM_TIMEOUT', async () => {
  const tr = start([{ hang: true }], []);
  await assert.rejects(runPipeline({ text: 'doc', deadlineAt: budget(3_000), tracer: tr }), (e) => e.code === 'LLM_TIMEOUT');
  assert.equal(tr.trace.llm[0].errorClass, 'timeout');
  assert.equal(tr.trace.llm[1].skipped, true);
});

test('syntax error: one repair, then OK', async () => {
  const tr = start([mermaidReply('flowchart TD\nA-->'), mermaidReply('flowchart TD\nA-->B')], ['bad', 'ok']);
  const rec = {};
  const r = await runPipeline({ text: 'doc', diagramType: 'Flowchart', deadlineAt: budget(), tracer: tr, record: rec, artifactPrefix: 'p/' });
  assert.equal(r.repaired, true);
  assert.equal(rec.select.skipped, true);
  assert.deepEqual(tr.trace.llm.map((l) => l.step), ['generate', 'repair']);
  assert.deepEqual(rec.render.map((x) => x.outcome), ['validation_error', 'ok']);
  assert.ok(tr.artifacts.has('p/attempt2.mmd'));
  assert.match(tr.llmRecords[1].request.messages.at(-1).content, /Parse error on line 2/);
});

test('still invalid after the repair: RENDER_FAILED at render', async () => {
  const tr = start([mermaidReply('x'), mermaidReply('y')], ['bad', 'bad']);
  await assert.rejects(runPipeline({ text: 'doc', diagramType: 'Flowchart', deadlineAt: budget(), tracer: tr }), (e) => e.code === 'RENDER_FAILED' && e.stage === 'render');
});

test('PNG rasterizer failure (not size): RENDER_FAILED at rasterize, no repair or resize (Q2)', async () => {
  const tr = start([mermaidReply('flowchart TD\nA-->B')], ['pngfail']);
  await assert.rejects(runPipeline({ text: 'doc', diagramType: 'Flowchart', deadlineAt: budget(), tracer: tr }), (e) => e.code === 'RENDER_FAILED' && e.stage === 'rasterize');
  assert.deepEqual(tr.trace.llm.map((l) => l.step), ['generate']);
});

// --- D28: one resize retry when the PNG would exceed the renderer's size limit ---

test('parseTooLarge reads the renderer message; anything else is null', () => {
  assert.deepEqual(parseTooLarge(TOO_LARGE_MSG), { width: 2400, height: 10464, maxPx: 8000 });
  assert.equal(parseTooLarge('PNG rasterization failed: SIGABRT'), null);
  assert.equal(parseTooLarge(undefined), null);
});

test('countContentLines skips blanks, comments, front matter, and styling', () => {
  const src = ['---', 'config:', '  theme: base', '---', '%%{init: {}}%%', 'flowchart TD', '', '  A --> B', '  %% note', '  B --> C', '  classDef dhs fill:#005288', '  class A dhs', '  style C fill:#fff'].join('\n');
  assert.equal(countContentLines(src), 3); // flowchart TD, A --> B, B --> C
  assert.equal(countContentLines(''), 0);
});

test('resizeInstruction states the size, the cut, what reduces size, a line target, and keeps the type', () => {
  const source = ['flowchart TD', ...Array.from({ length: 99 }, (_, i) => `  N${i} --> N${i + 1}`)].join('\n'); // 100 content lines
  const text = resizeInstruction('Flowchart', { width: 2400, height: 10464, maxPx: 8000 }, source);
  assert.match(text, /about 2400 x 10464 px, but the maximum is 8000 px per side/);
  assert.match(text, /reduce its height by at least 32%, but not much more than that/); // 8000/10464*0.9 = 0.688 -> 32%
  assert.match(text, /Shortening labels or text alone will NOT make it fit: show fewer items/);
  assert.doesNotMatch(text, /may .*shorten labels/);
  assert.match(text, /about 100 content lines; aim for about 68\. The rendered size is what counts\./);
  assert.match(text, /Keep the Flowchart diagram type/);
  assert.match(text, /change the layout direction|Changing the layout direction/);
  // Short sources get no line target (too rough to help).
  assert.doesNotMatch(resizeInstruction('Flowchart', { width: 2400, height: 9000, maxPx: 8000 }, 'flowchart TD\n A-->B'), /content lines/);
  assert.match(resizeInstruction('Gantt', { width: 9000, height: 2000, maxPx: 8000 }), /reduce its width by at least 20%/);
});

test('too large: one resize, then OK; resized reported with sizes and note', async () => {
  const tr = start([selectReply('TreeView'), mermaidReply('treeView-beta\n  big'), mermaidReply('treeView-beta\n  small')], ['toolarge', 'ok']);
  const rec = {};
  const r = await runPipeline({ text: 'doc', deadlineAt: budget(), tracer: tr, record: rec, artifactPrefix: 'p/' });
  assert.equal(r.resized, true);
  assert.equal(r.repaired, false);
  assert.equal(r.mermaidSource, 'treeView-beta\n  small');
  assert.deepEqual(tr.trace.llm.map((l) => l.step), ['select', 'generate', 'resize']);
  assert.deepEqual(rec.render.map((x) => x.outcome), ['png_failed', 'ok']);
  assert.equal(rec.resize.originalHeight, 10464);
  assert.deepEqual([r.resize.originalWidth, r.resize.originalHeight, r.resize.maxPx, r.resize.finalWidth, r.resize.finalHeight], [2400, 10464, 8000, 100, 50]);
  assert.match(r.resize.note, /simplified to fit/);
  assert.ok(tr.artifacts.has('p/attempt2.mmd'));
  const last = tr.llmRecords[2].request.messages;
  assert.equal(last.at(-2).role, 'assistant');
  assert.match(last.at(-2).content, /big/);
  assert.match(last.at(-1).content, /2400 x 10464 px/);
  assert.deepEqual([rec.resize.contentLinesBefore, rec.resize.contentLinesAfter], [2, 2]);
});

test('still too large after the resize: RENDER_FAILED at rasterize, no second resize', async () => {
  const tr = start([mermaidReply('flowchart TD\nA-->B'), mermaidReply('flowchart TD\nA-->C')], ['toolarge', 'toolarge']);
  await assert.rejects(
    runPipeline({ text: 'doc', diagramType: 'Flowchart', deadlineAt: budget(), tracer: tr }),
    (e) => e.code === 'RENDER_FAILED' && e.stage === 'rasterize' && /after one resize attempt/.test(e.message) && e.resize?.originalHeight === 10464
  );
  assert.deepEqual(tr.trace.llm.map((l) => l.step), ['generate', 'resize']);
});

test('invalid Mermaid, repaired, then too large: both retries used, then OK', async () => {
  const tr = start([mermaidReply('x'), mermaidReply('flowchart TD\nA-->B'), mermaidReply('flowchart LR\nA-->B')], ['bad', 'toolarge', 'ok']);
  const rec = {};
  const r = await runPipeline({ text: 'doc', diagramType: 'Flowchart', deadlineAt: budget(), tracer: tr, record: rec, artifactPrefix: 'p/' });
  assert.equal(r.repaired, true);
  assert.equal(r.resized, true);
  assert.deepEqual(tr.trace.llm.map((l) => l.step), ['generate', 'repair', 'resize']);
  assert.deepEqual(rec.render.map((x) => x.outcome), ['validation_error', 'png_failed', 'ok']);
  assert.ok(tr.artifacts.has('p/attempt3.mmd'));
});

test('too large with too little time left: RENDER_FAILED without calling the LLM', async () => {
  // 30.5 s budget: enough to generate (needs 30 s), then a slow 11 s render leaves < 20 s.
  const tr = start([mermaidReply('flowchart TD\nA-->B')], ['toolarge-slow']);
  await assert.rejects(
    runPipeline({ text: 'doc', diagramType: 'Flowchart', deadlineAt: budget(30_500), tracer: tr }),
    (e) => e.code === 'RENDER_FAILED' && e.stage === 'rasterize' && /only \d+ ms remain for a resize attempt/.test(e.message)
  );
  assert.deepEqual(tr.trace.llm.map((l) => l.step), ['generate']);
});

test('an excluded diagramType (D29) is ignored: selection runs and the trace says why', async () => {
  const tr = start([selectReply('Flowchart'), mermaidReply('flowchart TD\nA-->B')], ['ok']);
  const rec = {};
  const r = await runPipeline({ text: 'doc', diagramType: 'Treemap', deadlineAt: budget(), tracer: tr, record: rec });
  assert.equal(rec.select.skipped, false);
  assert.equal(rec.select.requestedRejected, 'excluded');
  assert.equal(r.diagramType, 'Flowchart');
  assert.doesNotMatch(tr.llmRecords[0].request.messages[0].content, /treeview|treemap|cynefin/i);
});

test('an unsupported diagramType falls back to selection', async () => {
  const tr = start([selectReply('Timeline'), mermaidReply('timeline\n title T')], ['ok']);
  const rec = {};
  const r = await runPipeline({ text: 'doc', diagramType: 'Mindmap', deadlineAt: budget(), tracer: tr, record: rec });
  assert.equal(rec.select.skipped, false);
  assert.equal(rec.select.requestedRejected, 'unsupported');
  assert.equal(r.diagramType, 'Timeline');
});
