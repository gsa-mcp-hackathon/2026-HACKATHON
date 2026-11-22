// Single self-contained HTML report for a startup self-test run
// (BUILD_PLAN.md section 8b, decisions D14-D16).
//
// Rules: inline CSS only, PNGs embedded as data: URIs, no JavaScript, no
// external URLs. Every piece of untrusted content (document text, Mermaid,
// LLM replies, error messages) goes through esc() and is shown in <pre>.

const PASS = '\u2705';
const FAIL = '\u274c';

export function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function icon(ok) {
  return ok ? PASS : FAIL;
}

function pre(value) {
  return `<pre>${esc(value)}</pre>`;
}

function details(summary, body, open = false) {
  return `<details${open ? ' open' : ''}><summary>${summary}</summary><div class="body">${body}</div></details>`;
}

function json(value) {
  return pre(JSON.stringify(value, null, 2));
}

function img(buf, alt, cls = '') {
  if (!buf) return `<div class="noimg">${FAIL} no image</div>`;
  return `<img class="${cls}" alt="${esc(alt)}" src="data:image/png;base64,${buf.toString('base64')}">`;
}

function kv(rows) {
  return `<table class="kv">${rows
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v === null ? '—' : v)}</td></tr>`)
    .join('')}</table>`;
}

const CSS = `
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;color:#1b1b1b;background:#fff;max-width:1400px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px;border-bottom:2px solid #005288;padding-bottom:4px;color:#005288}
.sub{color:#5a5b5d;font-size:13px;margin-bottom:16px}
.main{border:2px solid #005288;border-radius:6px;padding:16px;background:#f5f8fa}
.main img{width:100%;height:auto;border:1px solid #c0c2c4;background:#fff}
.bigfail{font-size:28px;color:#c41230;font-weight:600}
table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #dedfe0;padding:4px 8px;text-align:left;vertical-align:top}
table.kv th{background:#f5f5f6;width:220px;font-weight:600}
table.list th{background:#edeeee}
details{border:1px solid #dedfe0;border-radius:4px;margin:6px 0;background:#fff}
summary{cursor:pointer;padding:6px 10px;font-weight:600;background:#f5f5f6}
details .body{padding:8px 12px}
pre{white-space:pre-wrap;word-break:break-word;background:#f8f8f9;border:1px solid #edeeee;padding:8px;font-size:12px;max-height:600px;overflow:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.card{border:1px solid #dedfe0;border-radius:4px;padding:8px;font-size:12px}
.card.fail{border-color:#e08493;background:#fdf6f7}
.card .name{font-weight:600;font-size:13px;margin-bottom:4px}
.card img{width:100%;height:auto;max-height:220px;object-fit:contain;background:#fff;border:1px solid #edeeee}
.noimg{color:#c41230;font-size:12px;padding:8px 0}
.muted{color:#5a5b5d}
`;

function mainResult(tracer, pdf) {
  const png = tracer.getArtifact('sample.pdf/output.png');
  if (pdf && pdf.ok && png) {
    const r = pdf.result || {};
    return `<div class="main">${kv([
      ['Source file', 'selftest/sample.pdf'],
      ['Diagram type', r.diagramType],
      ['PNG size', `${r.width} x ${r.height} px, ${r.pngBytes} bytes`],
      ['Repair attempt used', r.repaired ? 'yes' : 'no'],
      ['Resized to fit', r.resized ? `yes (first version ~${r.resize?.originalWidth}x${r.resize?.originalHeight}px)` : 'no'],
      ['Endpoint used', r.endpointUsed],
      ['Total time', `${pdf.totalMs} ms`],
    ])}<p class="muted">Rendered on the server by render.mjs from the Mermaid code the LLM wrote. Check that it renders and matches the document.</p>${img(png, 'sample.pdf diagram')}</div>`;
  }
  if (!pdf) {
    return `<div class="main"><div class="bigfail">${FAIL} The sample.pdf end-to-end run did not execute</div><p>STARTUP_SELFTEST mode: ${esc(tracer.trace.selftest?.mode)}</p></div>`;
  }
  return `<div class="main"><div class="bigfail">${FAIL} No PNG was produced for sample.pdf</div>${kv([
    ['Failing stage', pdf.errorStage],
    ['Error code', pdf.errorCode],
    ['Total time', pdf.totalMs != null ? `${pdf.totalMs} ms` : null],
  ])}${pre(pdf.error)}</div>`;
}

function summary(tracer, st) {
  const s = st.stages || {};
  const rows = [];
  const add = (name, ok, note) => rows.push(`<tr><td>${icon(ok)}</td><td>${esc(name)}</td><td>${esc(note ?? '')}</td></tr>`);
  if (s.volume) add('Volume write/read check', s.volume.ok, s.volume.ok ? `${s.volume.ms} ms` : s.volume.error);
  for (const p of s.pings || []) add(`LLM ping: ${p.endpoint}`, p.ok, p.ok ? `${p.ms} ms` : p.error);
  for (const e of s.extraction || []) add(`Extraction: ${e.file}`, e.ok, e.ok ? `${e.branch}, ${e.chars} chars, ${e.ms} ms${e.truncated ? ', truncated' : ''}` : `${e.errorCode}: ${e.error}`);
  if (s.renderSmoke) add('Render smoke test (2-node flowchart)', s.renderSmoke.ok, s.renderSmoke.ok ? `${s.renderSmoke.ms} ms` : s.renderSmoke.error);
  if (s.pdf) add('sample.pdf end to end', s.pdf.ok, s.pdf.ok ? `${s.pdf.result?.diagramType}, ${s.pdf.totalMs} ms` : `${s.pdf.errorCode} at ${s.pdf.errorStage}`);
  if (s.gallery) add(`Gallery (${s.gallery.total} types, non-blocking)`, s.gallery.supportedFailed === 0, `${s.gallery.passed}/${s.gallery.total} rendered; ${s.gallery.supportedFailed} supported type(s) failed`);
  const run = tracer.trace.run;
  const v = tracer.trace.version;
  return `${kv([
    ['Run ID', run.runId],
    ['Overall (machine checks)', `${icon(run.outcome === 'OK')} ${run.outcome}`],
    ['Started', run.startedAt],
    ['Total duration', run.totalMs != null ? `${run.totalMs} ms` : null],
    ['Trace level', tracer.level],
    ['Self-test mode', st.mode],
    ['VERSION file', v.versionFile ? JSON.stringify(v.versionFile) : 'missing'],
    ['Source hash', v.sourceHash],
    ['Node', v.node],
    ['Packages', Object.entries(v.packages || {}).map(([k, val]) => `${k}@${val ?? '?'}`).join(', ')],
    ['LLM endpoints', `${tracer.trace.config.llmPrimary ?? '(unset)'} -> ${tracer.trace.config.llmFallback ?? '(unset)'}`],
    ['Trace volume', `${tracer.trace.config.resolvedVolumePath} (TRACE_VOLUME=${tracer.trace.config.traceVolumeEnv ?? 'unset'})`],
    ['V19 fault injection', tracer.trace.config.faultInjection?.tokens?.length ? (tracer.trace.config.faultInjection.active ? `ACTIVE until ${tracer.trace.config.faultInjection.until}: ${tracer.trace.config.faultInjection.tokens.join(', ')}` : `requested but ignored: ${tracer.trace.config.faultInjection.ignoredReason}`) : undefined],
  ])}<h3>Stages</h3><table class="list"><tr><th></th><th>Stage</th><th>Result</th></tr>${rows.join('')}</table>`;
}

function gallery(tracer, g) {
  if (!g) return '<p class="muted">Gallery did not run.</p>';
  const cards = g.items
    .map((it) => {
      const label = it.ok ? `${PASS}${it.knownUnsupported ? ' renders now (listed as unsupported)' : ''}` : `${FAIL}${it.knownUnsupported ? ' known unsupported' : ''}`;
      const body = it.ok
        ? img(tracer.getArtifact(`gallery/${it.slug}.png`), it.name)
        : `<div class="noimg">${esc(it.outcome)}</div>${pre(it.error)}`;
      return `<div class="card${it.ok ? '' : ' fail'}"><div class="name">${esc(it.name)}</div><div>${label} <span class="muted">${esc(it.ms)} ms${it.width ? `, ${it.width}x${it.height}` : ''}</span></div>${body}</div>`;
    })
    .join('');
  return `<p>${g.passed}/${g.total} rendered. ${g.supportedFailed} supported type(s) failed; ${g.knownUnsupportedFailed} of ${g.knownUnsupportedTotal} known-unsupported type(s) failed as expected.</p><div class="grid">${cards}</div>`;
}

function llmAttempt(rec) {
  const head = `${icon(!rec.errorClass)} #${rec.seq} ${esc(rec.step)} &middot; ${esc(rec.endpoint)}${rec.fallback ? ' (fallback)' : ''} &middot; ${rec.skipped ? 'skipped' : `HTTP ${esc(rec.status ?? '—')}, ${esc(rec.ms)} ms`}${rec.errorClass ? ` &middot; ${esc(rec.errorClass)}` : ''}`;
  const parts = [
    kv([
      ['Step', rec.step],
      ['Endpoint', rec.endpoint],
      ['Attempt / fallback', `${rec.attemptIndex} / ${rec.fallback ? 'yes' : 'no'}`],
      ['Timeout', rec.timeoutMs != null ? `${rec.timeoutMs} ms` : null],
      ['Finish reason', rec.finishReason],
      ['Usage', rec.usage ? JSON.stringify(rec.usage) : null],
      ['Skip reason', rec.skipReason ?? undefined],
    ]),
  ];
  if (rec.request?.messages) {
    parts.push(
      details(
        'Request messages',
        rec.request.messages.map((m) => `<p><b>${esc(m.role)}</b> <span class="muted">(${esc(String(m.content ?? '').length)} chars)</span></p>${pre(m.content)}`).join('')
      )
    );
  }
  if (rec.replyText) parts.push(details('Reply text', pre(rec.replyText)));
  if (rec.errorBody) parts.push(details('Error body', pre(rec.errorBody), true));
  if (rec.response) parts.push(details('Raw response JSON', json(rec.response)));
  return details(head, parts.join(''));
}

function pdfSection(tracer, pdf) {
  if (!pdf) return '<p class="muted">The sample.pdf run did not execute.</p>';
  const p = pdf.pipeline || {};
  const parts = [];
  parts.push(kv([
    ['Outcome', pdf.ok ? `${PASS} OK` : `${FAIL} ${pdf.errorCode} at ${pdf.errorStage}`],
    ['Input', pdf.input ? `${pdf.input.fileName}, ${pdf.input.decodedBytes} bytes, sha256 ${pdf.input.sha256}` : null],
    ['Extraction', pdf.extract ? `${pdf.extract.branch}, ${pdf.extract.chars} chars, ${pdf.extract.ms} ms, truncated: ${pdf.extract.truncated}` : null],
    ['Selection', p.select ? (p.select.skipped ? `skipped (${p.select.chosen} given)` : `${p.select.outcome}: ${p.select.chosen} (model said ${p.select.modelSaid ?? '—'})${p.select.reason ? `; ${p.select.reason}` : ''}`) : null],
    ['Rationale', p.select?.rationale ?? null],
    ['Generation', p.generate ? `${p.generate.endpoint}, ${p.generate.ms} ms, fenced: ${p.generate.fenced}, ${p.generate.mermaidChars} chars` : null],
    ['Repair', p.repair ? `${p.repair.endpoint}, ${p.repair.ms} ms, ${p.repair.mermaidChars} chars` : 'not needed / not run'],
    ['Resize', p.resize ? `${p.resize.endpoint}, ${p.resize.ms} ms, ${p.resize.mermaidChars} chars (was ~${p.resize.originalWidth}x${p.resize.originalHeight}px)` : 'not needed / not run'],
    ['Budget used', pdf.totalMs != null ? `${pdf.totalMs} of ${pdf.budgetMs} ms` : null],
  ]));
  const extracted = tracer.getArtifact('sample.pdf/extracted.txt');
  if (extracted) parts.push(details('Extracted text', pre(extracted.toString('utf8'))));
  for (const r of p.render || []) {
    const mmd = tracer.getArtifact(`sample.pdf/attempt${r.attempt}.mmd`);
    parts.push(
      details(
        `Mermaid attempt ${r.attempt}: ${icon(r.outcome === 'ok')} ${esc(r.outcome)} (${esc(r.ms)} ms)`,
        `${kv([['Render outcome', r.outcome], ['PNG', r.pngBytes ? `${r.width} x ${r.height} px, ${r.pngBytes} bytes` : null], ['Error', r.error]])}${mmd ? pre(mmd.toString('utf8')) : ''}`,
        r.outcome !== 'ok'
      )
    );
  }
  parts.push(`<p class="muted">The final PNG is shown in section 0 at the top of this report.</p>`);
  const llm = tracer.llmRecords.filter((rec) => rec.label === 'sample.pdf');
  parts.push(`<h3>LLM attempts (${llm.length})</h3>${llm.map(llmAttempt).join('') || '<p class="muted">none</p>'}`);
  if (!pdf.ok) parts.push(details('Error', pre(pdf.error), true));
  return parts.join('');
}

function extractionSection(tracer, list) {
  if (!list || !list.length) return '<p class="muted">Extraction checks did not run.</p>';
  return list
    .map((e) =>
      details(
        `${icon(e.ok)} ${esc(e.file)} &middot; ${esc(e.branch)} &middot; ${e.ok ? `${esc(e.chars)} chars, ${esc(e.ms)} ms` : esc(e.errorCode)}`,
        `${kv([['File', e.file], ['Bytes', e.bytes], ['Extractor', e.branch], ['Characters', e.chars], ['Truncated', e.truncated], ['Time', e.ms != null ? `${e.ms} ms` : null], ['Error', e.error]])}${e.preview ? `<p class="muted">First 1,000 characters</p>${pre(e.preview)}` : ''}`
      )
    )
    .join('');
}

function pingsSection(tracer, st) {
  const s = st.stages || {};
  const parts = [];
  if (s.volume) parts.push(kv([['Volume write/read', `${icon(s.volume.ok)} ${s.volume.ok ? `${s.volume.ms} ms` : s.volume.error}`], ['Path', s.volume.path]]));
  for (const p of s.pings || []) {
    parts.push(kv([['Endpoint', p.endpoint], ['Result', `${icon(p.ok)} ${p.ok ? `${p.ms} ms` : p.error}`], ['Reply', p.reply ?? undefined]]));
  }
  const ping = tracer.llmRecords.filter((rec) => rec.step === 'ping');
  if (ping.length) parts.push(`<h3>Ping attempts</h3>${ping.map(llmAttempt).join('')}`);
  return parts.join('') || '<p class="muted">Did not run.</p>';
}

export function buildStartupReport(tracer) {
  const st = tracer.trace.selftest || { stages: {} };
  const stages = st.stages || {};
  const writeErrors = tracer.writeErrors || [];
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>mcp-lancelot-beta startup report ${esc(tracer.runId)}</title><style>${CSS}</style></head>
<body>
<h1>mcp-lancelot-beta startup self-test</h1>
<div class="sub">${esc(tracer.runId)} &middot; ${esc(tracer.trace.run.startedAt)} &middot; generated by lib/report.mjs</div>
<h2>0. Main result: sample.pdf</h2>
${mainResult(tracer, stages.pdf)}
<h2>1. Summary</h2>
${summary(tracer, st)}
<h2>2. Diagram type gallery</h2>
${gallery(tracer, stages.gallery)}
<h2>3. sample.pdf end-to-end run</h2>
${pdfSection(tracer, stages.pdf)}
<h2>4. Extraction-only checks</h2>
${extractionSection(tracer, stages.extraction)}
<h2>5. Endpoint pings and volume check</h2>
${pingsSection(tracer, st)}
<h2>6. Trace-write errors</h2>
${writeErrors.length ? json(writeErrors) : `<p>${PASS} none recorded before the report was built</p>`}
</body></html>
`;
}
