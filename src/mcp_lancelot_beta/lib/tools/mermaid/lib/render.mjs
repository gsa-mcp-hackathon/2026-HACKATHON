// Mermaid -> PNG/SVG rendering with defensive validation.
//
// Threat model: the Mermaid source reaching this module may originate from
// an LLM that was itself steered by untrusted document content (prompt
// injection), so it is treated as fully untrusted input regardless of who
// calls this API.
//
// Rendering approach: two earlier versions tried running Chromium in this
// app's container - first via @mermaid-js/mermaid-cli's bundled (regular)
// Puppeteer, then via @sparticuz/chromium (a Chromium build packaged for
// restricted serverless/container runtimes) driven with puppeteer-core.
// BOTH failed to launch with a missing shared library error
// (libgobject-2.0.so.0) - there is no apt/root access in this container to
// install it, and @sparticuz/chromium's whole premise is bundling what a
// restrictive container is missing, so two independent Chromium builds
// failing the same way means this container cannot run Chromium at all.
//
// This version has zero browser dependency and zero native binaries beyond
// resvg's Rust rasterizer (see below).
//
// A first attempt used `svgdom`, a minimal pure-JS *SVG-only* DOM. That
// turned out to be too minimal for Mermaid's actual flowchart renderer, not
// just an initialization detail: even a trivial 2-node "A --> B" diagram
// crashed, and each fix (missing `document.body`/div-creation path, missing
// `CSSStyleSheet` global) uncovered a new, different crash one layer deeper
// - most recently inside Mermaid's own edge/marker-drawing code, where a
// plain d3 `.select(...).attr(...)` call returned a null node. That pattern
// (progressively deeper DOM-behavior mismatches on the simplest possible
// input) indicated svgdom does not behave enough like a real DOM for d3 to
// reliably select/query/manipulate elements the way Mermaid's code expects
// throughout rendering, not just at startup.
//
// `jsdom` is a much more complete, still pure-JS (no native binary) HTML+SVG
// DOM implementation - it was already a devDependency here for Vitest's
// `environment: 'jsdom'` - and is what most "render Mermaid in Node.js"
// write-ups actually use for this reason. Its one real gap is SVG layout
// measurement (`getBBox`/`getComputedTextLength` are not implemented), which
// Mermaid uses to size shapes around text labels - stubbed below with a
// character-count-based estimate so layout can proceed without crashing.
import { JSDOM } from 'jsdom';
import { spawn } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import opentype from 'opentype.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RASTERIZE_WORKER_PATH = path.join(__dirname, 'rasterizeWorker.mjs');
const require = createRequire(import.meta.url);

// Real font metrics for layout-time text measurement, closing most of the
// remaining gap with the Manual Editor's real-browser rendering (found
// 2026-09-25 comparing AI-Assistant-vs-Manual-Editor screenshots side by
// side, AFTER the group-aggregation and multi-line-height bugs below were
// already fixed - layout still visibly differed because AVG_CHAR_WIDTH_PX
// below is a flat per-character guess, not this font's actual glyph
// widths). Parses the SAME bundled DejaVu TTF that lib/rasterizeWorker.mjs
// feeds to resvg for the real PNG glyph shaping (see that file's own
// comments for why a font had to be bundled at all - this container ships
// no system fonts), via `opentype.js`, a pure-JS font parser with zero
// native/browser dependency - so layout-time sizing and render-time shaping
// now agree on the exact same font instead of one guessing at the other's
// metrics. Falls back to the old character-count/fixed-line-height estimate
// (further below) if the font can't be found/parsed for any reason - never
// a new crash/regression source.
//
// Deliberately a second copy of rasterizeWorker.mjs's own
// findBundledFontFiles() rather than a shared import - that worker runs as
// a separate CHILD PROCESS specifically for native-crash isolation (see its
// comments), so keeping the two module graphs independent is intentional;
// keep both copies in sync if either changes.
function findBundledFontFiles() {
  try {
    const pkgJsonPath = require.resolve('dejavu-fonts-ttf/package.json');
    const pkgDir = path.dirname(pkgJsonPath);
    const found = [];
    const stack = [pkgDir];
    while (stack.length) {
      const dir = stack.pop();
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          stack.push(full);
        } else if (entry.isFile() && entry.name.toLowerCase().endsWith('.ttf')) {
          found.push(full);
        }
      }
    }
    return found;
  } catch (err) {
    process.stderr.write(`findBundledFontFiles (render.mjs) failed: ${String(err && err.stack ? err.stack : err)}\n`);
    return [];
  }
}

const DEFAULT_FONT_SIZE_PX = 16; // Mermaid's default node/label font-size when no theme override sets one

let measurementFont; // undefined = not attempted yet; null = attempted and unavailable/failed
function getMeasurementFont() {
  if (measurementFont !== undefined) return measurementFont;
  try {
    const files = findBundledFontFiles();
    // Prefer the plain regular-weight file over Bold/Oblique/BoldOblique
    // variants when several are bundled, since that's the base family
    // rasterizeWorker.mjs's `defaultFontFamily: 'DejaVu Sans'` falls back to.
    const regular = files.find((f) => /DejaVuSans\.ttf$/i.test(f)) || files[0];
    measurementFont = regular ? opentype.loadSync(regular) : null;
  } catch (err) {
    process.stderr.write(
      `opentype.js failed to load the bundled font, falling back to the character-count estimate: ${String(err && err.stack ? err.stack : err)}\n`
    );
    measurementFont = null;
  }
  return measurementFont;
}

export class ValidationError extends Error {}

const MAX_MERMAID_LENGTH = 20_000;
const RENDER_TIMEOUT_MS = 20_000;
// jsdom's `window`/`document` are installed as one shared set of globals
// (there is no per-request "page" like a browser would give us), so renders
// are serialized rather than run concurrently to avoid two renders fighting
// over the same DOM.
const MAX_CONCURRENT_RENDERS = 1;
const FULL_SIZE_WIDTH = 1200;
const THUMBNAIL_WIDTH = 320;
const ALLOWED_FORMATS = ['png', 'svg', 'both'];

const MERMAID_RENDER_CONFIG = {
  startOnLoad: false,
  // 'strict' sanitizes HTML labels and disables click/JS callbacks
  // entirely - the key defense against a malicious or prompt-injected
  // diagram trying to embed script. (jsdom does not execute <script> tags
  // it did not itself parse/insert via normal document APIs in this usage,
  // but this is kept as defense in depth and for the SVG output's own sake
  // if it's opened directly in a real browser later.)
  securityLevel: 'strict',
  secure: ['securityLevel', 'theme', 'themeVariables', 'fontFamily'],
  maxTextSize: 50_000,
  maxEdges: 2_000,
  // Root cause of TWO separate-looking bugs at once, found 2026-09-22:
  // Mermaid's default `htmlLabels: true` renders node/edge labels as real
  // HTML (<span>/<p>/<br>) wrapped in an SVG <foreignObject>, not as plain
  // SVG <text>. That explains (1) "diagram renders but every label is
  // blank" independently of any font-bundling fix - @resvg/resvg-js is a
  // pure SVG rasterizer with no <foreignObject>/HTML rendering support at
  // all, so it silently skips that content regardless of whether a usable
  // font is available (fonts only matter for actual <text> elements) - and
  // (2) "Unexpected closing tag: ...p != ...br" when opening the SVG
  // directly in a browser - a bare `<br>` (valid, unclosed-void-element
  // HTML) is illegal inside a strict-XML SVG document, even though a
  // browser's lenient HTML parser tolerates the same markup fine when it's
  // embedded via an <img>/<iframe> rather than opened as a standalone XML
  // document. Forcing plain SVG <text>/<tspan> labels for every diagram
  // type fixes both: no HTML content for resvg to skip, and no HTML
  // markup for a strict XML parser to choke on.
  htmlLabels: false,
  flowchart: { htmlLabels: false },
};

// Installs the jsdom window/document as globals and imports mermaid only
// after they exist, since mermaid's d3 usage expects a browser-like
// `document` to already be present. Done once, lazily, and cached.
let mermaidPromise = null;
async function getMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = (async () => {
      const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', { pretendToBeVisual: true });
      const { window } = dom;
      const document = window.document;
      globalThis.window = window;
      globalThis.document = document;
      // Mermaid/d3's bundled code was written assuming it runs inside an
      // actual browser, so it references many Web APIs as bare global
      // identifiers (CSSStyleSheet, navigator, DOMParser, etc.), not via
      // `window.X`. Node's global scope has none of these (except a couple
      // Node itself defines, e.g. a read-only `navigator` since Node 21).
      // Rather than hand-polyfill each missing one as it's discovered by a
      // new crash (which is what happened with CSSStyleSheet - jsdom's
      // window has it, but it was never copied onto the real Node global,
      // so `new CSSStyleSheet()` still failed with "is not defined"), copy
      // every property jsdom's window exposes onto the real global object
      // in one pass, skipping anything Node already defines itself.
      for (const key of Object.getOwnPropertyNames(window)) {
        if (typeof globalThis[key] === 'undefined') {
          try {
            globalThis[key] = window[key];
          } catch {
            // A handful of window properties are getter-only even on
            // window itself; skip anything that can't be copied.
          }
        }
      }

      // jsdom does not implement real SVG layout - getBBox/
      // getComputedTextLength throw "not implemented" by default. Mermaid
      // calls these to size node/label boxes around text. There is no way
      // to get a real measurement without an actual layout engine (which is
      // exactly what we don't have headlessly), so this estimates width from
      // character count - close enough for dagre's layout to proceed without
      // crashing; shapes may be sized slightly differently than a real
      // browser would, but the diagram renders.
      const AVG_CHAR_WIDTH_PX = 7;
      const LINE_HEIGHT_PX = 16;
      // Reads this element's actual CSS font-size (Mermaid sets it per class,
      // e.g. smaller for subgraph cluster titles / edge labels than for node
      // labels), falling back to Mermaid's plain default when jsdom's CSS
      // cascade can't resolve one (e.g. an element not attached to the live
      // document, or a selector jsdom's engine doesn't fully support) -
      // never let this become a new crash source.
      function fontSizeOf(el) {
        try {
          const cs = window.getComputedStyle(el);
          const n = cs && cs.fontSize ? parseFloat(cs.fontSize) : NaN;
          if (Number.isFinite(n) && n > 0) return n;
        } catch {
          // fall through to the default below
        }
        return DEFAULT_FONT_SIZE_PX;
      }
      // Real glyph-advance-width measurement from the bundled font (see
      // getMeasurementFont() above), scaled to this element's actual
      // font-size - falls back to the flat character-count estimate if the
      // font failed to load or a specific glyph/text run can't be measured.
      function measureTextWidthPx(text, fontSizePx) {
        const font = getMeasurementFont();
        if (font) {
          try {
            return Math.max(1, font.getAdvanceWidth(text, fontSizePx));
          } catch {
            // fall through to the character-count estimate below
          }
        }
        return Math.max(1, text.length * AVG_CHAR_WIDTH_PX);
      }
      // Real per-line height from the font's own ascender/descender metrics,
      // scaled to font-size, instead of the flat LINE_HEIGHT_PX=16 constant -
      // this is what actually made the multi-line-height fix above accurate
      // for labels at a non-default font-size (e.g. smaller subgraph titles).
      function lineHeightPx(fontSizePx) {
        const font = getMeasurementFont();
        if (font && font.unitsPerEm) {
          const ascender = font.ascender ?? font.unitsPerEm * 0.8;
          const descender = font.descender ?? -font.unitsPerEm * 0.2;
          const raw = ((ascender - descender) / font.unitsPerEm) * fontSizePx;
          // A font's full ascender-to-descender span usually reads taller than
          // what a browser treats as one text line's effective box (typical
          // UA line-height is ~1.15-1.2x font-size, not the font's full
          // glyph-bounding-box span) - clamp to a sane multiple of font-size
          // so an unusual font's metrics can't blow layout back up the way
          // the group-aggregation bug once did.
          return Math.min(Math.max(raw, fontSizePx), fontSizePx * 1.6);
        }
        return LINE_HEIGHT_PX;
      }
      // getBBox()/getComputedTextLength() need to estimate ONE label's size,
      // not blow up on whatever element they're actually called on. Two
      // failed attempts before this (both confirmed via /api/selftest-render
      // producing a visibly wrong viewBox):
      // 1. Full `this.textContent` - explodes on a container/group element
      //    (e.g. a <g> wrapping many labels, common with subgraphs adding
      //    nesting depth), which concatenates EVERY descendant text node.
      //    Produced viewBox "-8 -8 55862 32" (55,862 units wide!) - almost
      //    certainly also the real cause of the repeated resvg-js crashes
      //    (rasterizing a ~56000-unit-wide vector).
      // 2. Restricting by tag name (only <text>/<tspan> get real text,
      //    everything else gets 0) - overcorrected. Mermaid apparently
      //    calls getBBox on wrapping <g> node/label groups too, not just
      //    <text>/<tspan> directly, so this produced viewBox "-8 -8 17 32"
      //    (an almost zero-width diagram) - nearly every meaningful call
      //    returned the minimum placeholder.
      // Fix: don't try to guess WHICH element deserves real text - instead
      // cap the measured length to a generous single-label bound. Any
      // individual label in a real diagram is well under ~120 characters;
      // aggregated text from a multi-label container will usually blow well
      // past that, so clamping caps the aggregation-explosion case at a
      // sane single-label-ish size while leaving legitimate single-label
      // measurements (whichever element they're actually read from)
      // essentially untouched.
      const MAX_MEASURED_LABEL_CHARS = 120;
      function measuredTextOf(el) {
        const text = el.textContent || '';
        return text.length > MAX_MEASURED_LABEL_CHARS ? text.slice(0, MAX_MEASURED_LABEL_CHARS) : text;
      }
      function isTextish(el) {
        const tag = (el.tagName || '').toLowerCase();
        return tag === 'text' || tag === 'tspan' || tag === 'textpath';
      }
      // Reads this element's own translate(x,y) offset, if any - needed to
      // correctly place a CHILD's bbox in the PARENT's coordinate space when
      // computing a container's union bbox below (per the SVG spec, getBBox()
      // returns coordinates in the queried element's own user space, which
      // includes children's transforms but not the queried element's own).
      function ownTranslate(el) {
        const t = el.getAttribute ? el.getAttribute('transform') : null;
        if (!t) return { x: 0, y: 0 };
        const m = /translate\(\s*([-\d.]+)[,\s]+([-\d.]+)\s*\)/.exec(t);
        return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : { x: 0, y: 0 };
      }
      // Mermaid draws non-rectangular node shapes (cylinder/database,
      // stadium, hexagon, subroutine, etc.) as a single <path>, then calls
      // its own updateNodeBounds() - which does getBBox() on the shape's
      // wrapping <g> (path + label) to set node.width/node.height, the
      // values DAGRE actually uses for layout spacing. Leaving <path>
      // uncounted (as shapeGeometryBBox below did until now) meant that
      // group's bbox collapsed to the label's bbox alone, ignoring the drawn
      // shape entirely - dagre then spaced e.g. cylinder nodes as if they
      // were smaller than actually drawn. Found 2026-09-26 comparing a
      // diagram with database/cylinder nodes against the Manual Editor:
      // spacing around cylinders was visibly wrong even after the font-
      // metrics fix (which only affects the label bbox, not the shape
      // outline). Fix: walk the path's `d` string as real path commands
      // (M/L/H/V/C/S/Q/T/A/Z, absolute vs. relative per the SVG spec - NOT
      // a naive "every two numbers is an (x,y) pair" regex, which breaks on
      // relative commands - deltas, not coordinates - and on arcs, which
      // take 7 numeric params, not a coordinate pair), marking every point
      // and control point seen. A cubic/quadratic Bezier curve is always
      // within the convex hull of its own control points, so marking them
      // (not evaluating the curve) is a safe bound - loose, never too
      // small - which is the right failure direction given this app's
      // history of viewBox-exploding bugs from overly generous estimates:
      // a MAX_PATH_BBOX_DIMENSION_PX sanity clamp below discards the result
      // entirely (falling back to no shape contribution, today's behavior)
      // if a parsing slip ever produces something implausibly large.
      const MAX_PATH_BBOX_DIMENSION_PX = 4000;
      function pathGeometryBBox(el) {
        const d = el.getAttribute ? el.getAttribute('d') : null;
        if (!d) return null;
        const tokens = d.match(/[a-zA-Z]|-?\d*\.?\d+(?:e-?\d+)?/g);
        if (!tokens) return null;
        let i = 0;
        let cx = 0;
        let cy = 0;
        let startX = 0;
        let startY = 0;
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        const mark = (x, y) => {
          if (!Number.isFinite(x) || !Number.isFinite(y)) return;
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        };
        const num = () => parseFloat(tokens[i++]);
        let cmd = null;
        while (i < tokens.length) {
          if (/^[a-zA-Z]$/.test(tokens[i])) {
            cmd = tokens[i];
            i += 1;
          }
          if (!cmd) break;
          const rel = cmd === cmd.toLowerCase();
          const upper = cmd.toUpperCase();
          if (upper === 'Z') {
            cx = startX;
            cy = startY;
            continue;
          }
          if (upper === 'M') {
            const x = num();
            const y = num();
            cx = rel ? cx + x : x;
            cy = rel ? cy + y : y;
            startX = cx;
            startY = cy;
            mark(cx, cy);
          } else if (upper === 'L') {
            const x = num();
            const y = num();
            cx = rel ? cx + x : x;
            cy = rel ? cy + y : y;
            mark(cx, cy);
          } else if (upper === 'H') {
            const x = num();
            cx = rel ? cx + x : x;
            mark(cx, cy);
          } else if (upper === 'V') {
            const y = num();
            cy = rel ? cy + y : y;
            mark(cx, cy);
          } else if (upper === 'C') {
            const x1 = num();
            const y1 = num();
            const x2 = num();
            const y2 = num();
            const x = num();
            const y = num();
            const ax1 = rel ? cx + x1 : x1;
            const ay1 = rel ? cy + y1 : y1;
            const ax2 = rel ? cx + x2 : x2;
            const ay2 = rel ? cy + y2 : y2;
            const ax = rel ? cx + x : x;
            const ay = rel ? cy + y : y;
            mark(ax1, ay1);
            mark(ax2, ay2);
            mark(ax, ay);
            cx = ax;
            cy = ay;
          } else if (upper === 'S' || upper === 'Q') {
            const x1 = num();
            const y1 = num();
            const x = num();
            const y = num();
            const ax1 = rel ? cx + x1 : x1;
            const ay1 = rel ? cy + y1 : y1;
            const ax = rel ? cx + x : x;
            const ay = rel ? cy + y : y;
            mark(ax1, ay1);
            mark(ax, ay);
            cx = ax;
            cy = ay;
          } else if (upper === 'T') {
            const x = num();
            const y = num();
            cx = rel ? cx + x : x;
            cy = rel ? cy + y : y;
            mark(cx, cy);
          } else if (upper === 'A') {
            const rx = num();
            const ry = num();
            num(); // x-axis-rotation - ignored for this safe-bound approximation
            num(); // large-arc-flag - ignored
            num(); // sweep-flag - ignored
            const x = num();
            const y = num();
            const startX = cx;
            const startY = cy;
            const ax = rel ? cx + x : x;
            const ay = rel ? cy + y : y;
            mark(startX, startY);
            mark(ax, ay);
            // CORRECTED 2026-09-26: the previous version padded by +/- rx AND
            // +/- ry around BOTH endpoints in every direction, including
            // ALONG the chord itself - but the chord's own direction is
            // already exactly bounded by the two endpoints just marked
            // above; an elliptical arc only bulges PERPENDICULAR to its
            // chord (by its semi-axis in that perpendicular direction, for
            // an axis-aligned - rotation ignored, matching Mermaid's own
            // unrotated cylinder/database rim arcs - half-ellipse). Padding
            // along the chord too roughly doubled the true width of
            // Mermaid's cylinder shape (whose rim arcs have a mostly-
            // horizontal chord spanning the full node width) - confirmed as
            // the cause of two visible bugs at once: extra outer margin
            // around the whole diagram (dagre allocating space for an
            // over-wide cylinder node) and off-center cylinder labels (the
            // label was centered against the correct, smaller drawn shape,
            // but the group's OWN reported bbox/width used for that
            // centering calculation was the inflated one). Only pad
            // perpendicular to the chord now, by the semi-axis in that
            // perpendicular direction (ry for a horizontal chord, rx for a
            // vertical one).
            const dx = Math.abs(ax - startX);
            const dy = Math.abs(ay - startY);
            if (dx >= dy) {
              const midX = (startX + ax) / 2;
              mark(midX, startY - ry);
              mark(midX, startY + ry);
            } else {
              const midY = (startY + ay) / 2;
              mark(startX - rx, midY);
              mark(startX + rx, midY);
            }
            cx = ax;
            cy = ay;
          } else {
            // Unrecognized command - stop rather than risk misreading the
            // rest of the token stream as this command's arguments.
            break;
          }
        }
        if (minX === Infinity) return null;
        const width = maxX - minX;
        const height = maxY - minY;
        if (width > MAX_PATH_BBOX_DIMENSION_PX || height > MAX_PATH_BBOX_DIMENSION_PX) {
          process.stderr.write(`pathGeometryBBox: discarding implausible bbox ${width}x${height} for d="${d.slice(0, 80)}"\n`);
          return null;
        }
        return { x: minX, y: minY, width: Math.max(0, width), height: Math.max(0, height) };
      }
      function shapeGeometryBBox(el) {
        const tag = (el.tagName || '').toLowerCase();
        const num = (name) => {
          const v = el.getAttribute ? el.getAttribute(name) : null;
          const n = v == null ? NaN : parseFloat(v);
          return Number.isFinite(n) ? n : null;
        };
        if (tag === 'rect') {
          const w = num('width');
          const h = num('height');
          if (w != null && h != null) return { x: num('x') ?? 0, y: num('y') ?? 0, width: w, height: h };
        } else if (tag === 'circle') {
          const r = num('r');
          if (r != null) return { x: (num('cx') ?? 0) - r, y: (num('cy') ?? 0) - r, width: r * 2, height: r * 2 };
        } else if (tag === 'ellipse') {
          const rx = num('rx');
          const ry = num('ry');
          if (rx != null && ry != null) return { x: (num('cx') ?? 0) - rx, y: (num('cy') ?? 0) - ry, width: rx * 2, height: ry * 2 };
        } else if (tag === 'line') {
          const x1 = num('x1') ?? 0, y1 = num('y1') ?? 0, x2 = num('x2') ?? 0, y2 = num('y2') ?? 0;
          return { x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) };
        } else if (tag === 'path') {
          return pathGeometryBBox(el);
        }
        return null;
      }
      // Real getBBox() semantics: the tight bounding box of an element's OWN
      // rendered content plus every descendant, each positioned by ITS OWN
      // transform. Three earlier attempts all guessed from `textContent`
      // alone and all failed differently (see /api/selftest-render history):
      // full textContent exploded to a 55,862-unit-wide viewBox by
      // aggregating every descendant label under one container; restricting
      // to <text>/<tspan> tags collapsed to a near-zero-width viewBox because
      // Mermaid also calls getBBox on wrapping <g> node/label groups, not
      // just <text>; capping textContent length fixed both extremes for
      // PER-NODE sizing (dagre's actual node positions came out correct and
      // well-spread - confirmed via /api/selftest-render's svgStructure
      // diagnostic) but the FINAL diagram-level getBBox call - determining
      // the overall SVG's viewBox/width/height after layout - still used the
      // same text-length guess, producing a viewBox far smaller than the
      // real content extent ("-8 -8 856 32" when nodes are actually
      // positioned out to x~1825, y~437) and silently clipping most of the
      // diagram. Fix: recursively union each child's real bbox (shape
      // geometry for rect/circle/ellipse/line, the character-count estimate
      // for text/tspan, or a further recursive union for any other
      // container), offsetting each child by its own translate(), instead of
      // reading textContent at all for container elements.
      function computeBBox(el) {
        // Mermaid (with htmlLabels:false) renders a multi-line label as ONE
        // <text> wrapping several <tspan> children (one per line, stacked via
        // each tspan's own `dy` - NOT a `transform`, which is the only offset
        // ownTranslate() below understands). Because isTextish() below treats
        // <text> itself as a leaf and returns textContent's length at a FIXED
        // single-LINE_HEIGHT_PX height, every multi-line label was measured as
        // if it were exactly one line tall regardless of how many lines it
        // actually has - undersizing the node box vertically and letting the
        // 2nd/3rd line render past the box's bottom edge. This is the real
        // cause of the AI-Assistant-vs-Manual-Editor visual mismatch (found
        // 2026-09-25 comparing screenshots) - NOT the group-aggregation bug
        // handled by the recursive union below, which only explained the
        // earlier giant-viewBox crash, not this overflow. Detect this case up
        // front: if `el` is a <text> with one or more <tspan> children, size
        // it from the LINE COUNT (number of tspans) and the WIDEST single
        // line, instead of textContent's full concatenated length.
        if ((el.tagName || '').toLowerCase() === 'text') {
          const tspanChildren = Array.from(el.children || []).filter(
            (c) => (c.tagName || '').toLowerCase() === 'tspan'
          );
          if (tspanChildren.length > 0) {
            const fontSizePx = fontSizeOf(el);
            let maxWidth = 1;
            for (const tspan of tspanChildren) {
              const w = measureTextWidthPx(measuredTextOf(tspan), fontSizeOf(tspan) || fontSizePx);
              if (w > maxWidth) maxWidth = w;
            }
            return { x: 0, y: 0, width: maxWidth, height: lineHeightPx(fontSizePx) * tspanChildren.length };
          }
        }
        if (isTextish(el)) {
          const fontSizePx = fontSizeOf(el);
          const text = measuredTextOf(el);
          return { x: 0, y: 0, width: measureTextWidthPx(text, fontSizePx), height: lineHeightPx(fontSizePx) };
        }
        const shapeBox = shapeGeometryBBox(el);
        let minX = shapeBox ? shapeBox.x : Infinity;
        let minY = shapeBox ? shapeBox.y : Infinity;
        let maxX = shapeBox ? shapeBox.x + shapeBox.width : -Infinity;
        let maxY = shapeBox ? shapeBox.y + shapeBox.height : -Infinity;
        let any = !!shapeBox;
        const children = el.children || [];
        for (let i = 0; i < children.length; i += 1) {
          const child = children[i];
          const cb = computeBBox(child);
          if (cb.width <= 0 && cb.height <= 0) continue;
          const { x: dx, y: dy } = ownTranslate(child);
          const x0 = dx + cb.x;
          const y0 = dy + cb.y;
          const x1 = x0 + cb.width;
          const y1 = y0 + cb.height;
          if (x0 < minX) minX = x0;
          if (y0 < minY) minY = y0;
          if (x1 > maxX) maxX = x1;
          if (y1 > maxY) maxY = y1;
          any = true;
        }
        if (!any) return { x: 0, y: 0, width: 1, height: LINE_HEIGHT_PX };
        return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
      }
      window.SVGElement.prototype.getBBox = function () {
        return computeBBox(this);
      };
      window.SVGElement.prototype.getComputedTextLength = function () {
        // Per the SVG spec this is only ever meaningfully called on
        // SVGTextContentElement (text/tspan/textPath), so the real-font-
        // metrics width estimate (not a bbox union) is always the right tool
        // here.
        const text = measuredTextOf(this);
        return measureTextWidthPx(text, fontSizeOf(this));
      };

      const mod = await import('mermaid');
      return mod.default ?? mod;
    })().catch((err) => {
      mermaidPromise = null;
      throw err;
    });
  }
  return mermaidPromise;
}

// The app crashed the whole Node process (not a catchable JS exception -
// process-level unhandledRejection/uncaughtException handlers were already
// live and did NOT prevent it) specifically on a complex diagram
// (subgraphs, many text labels) that a trivial "A --> B" diagram did not
// trigger. @resvg/resvg-js is a native Rust binary; two known crash-prone
// patterns for it are (1) rasterizing an SVG whose viewBox implies an
// extreme output size relative to `fitTo`, which can blow up memory, and
// (2) system font scanning in a container with no fonts installed. Both are
// far more likely to be exercised by many/irregularly-laid-out text labels
// than by two single-letter node labels, matching what we observed. Guard
// against both rather than continuing to poke around without crash logs.
const MAX_RASTER_DIMENSION_PX = 8000;

function extractSvgSize(svgText) {
  const viewBoxMatch = svgText.match(/viewBox=["']\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*["']/);
  if (viewBoxMatch) {
    const w = parseFloat(viewBoxMatch[3]);
    const h = parseFloat(viewBoxMatch[4]);
    if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) {
      return { width: w, height: h };
    }
  }
  const widthMatch = svgText.match(/\bwidth=["']([\d.]+)/);
  const heightMatch = svgText.match(/\bheight=["']([\d.]+)/);
  if (widthMatch && heightMatch) {
    const w = parseFloat(widthMatch[1]);
    const h = parseFloat(heightMatch[1]);
    if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) {
      return { width: w, height: h };
    }
  }
  return null;
}

// Mermaid injects a <style> block with CSS `@keyframes` animations (e.g.
// `edge-animation-frame`, `dash` for animated edge dashes) into every SVG it
// produces. @resvg/resvg-js is a STATIC rasterizer - it has no use for
// animations, and CSS at-rules like @keyframes are a plausible native-crash
// vector for its CSS parser (this app crashed the whole Node process
// multiple times specifically on the PNG/resvg path, surviving both a
// canvas-size guard and disabling system font loading, so the remaining
// candidate is something in the SVG's actual content resvg's parser chokes
// on). Strips any @keyframes blocks (brace-depth-aware, since keyframe
// bodies contain their own nested {ruleset} blocks) before rasterizing -
// harmless for a static PNG either way, since animations never render in a
// still image regardless.
function stripKeyframesBlocks(text) {
  let result = '';
  let i = 0;
  for (;;) {
    const idx = text.indexOf('@keyframes', i);
    if (idx === -1) {
      result += text.slice(i);
      return result;
    }
    result += text.slice(i, idx);
    const braceStart = text.indexOf('{', idx);
    if (braceStart === -1) {
      result += text.slice(idx);
      return result;
    }
    let depth = 1;
    let j = braceStart + 1;
    while (j < text.length && depth > 0) {
      if (text[j] === '{') depth += 1;
      else if (text[j] === '}') depth -= 1;
      j += 1;
    }
    i = j; // skip the whole @keyframes ... { ... } block, nested braces included
  }
}

// Runs lib/rasterizeWorker.mjs as a SEPARATE Node process, piping the SVG in
// via stdin and reading the PNG back via stdout. This app crashed the whole
// server multiple times specifically on this rasterization step, surviving
// every JS-level mitigation tried (size guard, disabling system font
// scanning, stripping CSS @keyframes) plus process-level
// unhandledRejection/uncaughtException handlers - meaning it is not a
// catchable JS exception, almost certainly a native crash (segfault/panic)
// inside @resvg/resvg-js's Rust binary. Running it out-of-process means a
// crash there kills only the child (surfaced here as a rejected promise -
// an ordinary, catchable per-request error), not the whole app.
function rasterizeInWorker(svgText, targetWidthPx) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [RASTERIZE_WORKER_PATH, String(targetWidthPx)], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const stdoutChunks = [];
    const stderrChunks = [];
    child.stdout.on('data', (chunk) => stdoutChunks.push(chunk));
    child.stderr.on('data', (chunk) => stderrChunks.push(chunk));
    child.on('error', (err) => reject(err));
    child.on('close', (code, signal) => {
      if (signal) {
        reject(new Error(`PNG rasterizer process was killed by signal ${signal} - almost certainly a native crash in the rasterizer for this diagram`));
        return;
      }
      if (code !== 0) {
        const stderrText = Buffer.concat(stderrChunks).toString('utf8').slice(0, 500);
        reject(new Error(`PNG rasterizer process exited with code ${code}: ${stderrText || '(no stderr output)'}`));
        return;
      }
      resolve(Buffer.concat(stdoutChunks));
    });
    child.stdin.write(svgText, 'utf8');
    child.stdin.end();
  });
}

async function svgToPng(svgText, width) {
  const targetWidthPx = width * 2; // 2x for a sharper raster
  const size = extractSvgSize(svgText);
  if (size) {
    const scale = targetWidthPx / size.width;
    const outputHeightPx = size.height * scale;
    if (targetWidthPx > MAX_RASTER_DIMENSION_PX || outputHeightPx > MAX_RASTER_DIMENSION_PX) {
      throw new Error(
        `rendered diagram would be too large to rasterize safely (~${Math.round(targetWidthPx)}x${Math.round(outputHeightPx)}px, max ${MAX_RASTER_DIMENSION_PX}px per side) - try a simpler diagram (fewer nodes/subgraphs)`
      );
    }
  }
  const staticSvgText = stripKeyframesBlocks(svgText);
  return rasterizeInWorker(staticSvgText, targetWidthPx);
}

// Two independent concurrency limits:
// - SVG rendering shares one jsdom `document` (see getMermaid above), so it
//   must stay serialized to MAX_CONCURRENT_RENDERS.
// - PNG rasterization now runs in its own child process per call (see
//   rasterizeInWorker below) with no shared state, so a little concurrency
//   there is safe and doesn't risk one hung/crashed rasterizer blocking
//   unrelated requests' SVG rendering.
function createSemaphore(maxConcurrent) {
  let active = 0;
  const waiters = [];
  return function acquire() {
    return new Promise((resolve) => {
      const tryAcquire = () => {
        if (active < maxConcurrent) {
          active += 1;
          resolve(() => {
            active -= 1;
            const next = waiters.shift();
            if (next) next();
          });
        } else {
          waiters.push(tryAcquire);
        }
      };
      tryAcquire();
    });
  };
}

const acquireSvgSlot = createSemaphore(MAX_CONCURRENT_RENDERS);
const acquireRasterSlot = createSemaphore(2);

// Strip inline directive/frontmatter blocks (e.g. "%%{init: {...}}%%") so a
// malicious diagram cannot override the security-relevant config we set
// below (securityLevel, theme, etc.). Defense in depth alongside the
// `secure` mermaidConfig key.
function stripDirectives(source) {
  return source.replace(/%%\{[\s\S]*?\}%%/g, '');
}

function validateInput({ mermaid, format, thumbnail }) {
  if (typeof mermaid !== 'string' || mermaid.trim().length === 0) {
    throw new ValidationError('"mermaid" (string) is required');
  }
  if (mermaid.length > MAX_MERMAID_LENGTH) {
    throw new ValidationError(`"mermaid" exceeds max length of ${MAX_MERMAID_LENGTH} characters`);
  }
  if (/<\s*script/i.test(mermaid)) {
    throw new ValidationError('script tags are not permitted in diagram source');
  }
  if (format !== undefined && !ALLOWED_FORMATS.includes(format)) {
    throw new ValidationError(`"format" must be one of: ${ALLOWED_FORMATS.join(', ')}`);
  }
  if (thumbnail !== undefined && typeof thumbnail !== 'boolean') {
    throw new ValidationError('"thumbnail" must be a boolean');
  }
}

// Found 2026-09-26 by inspecting a real rendered SVG's markup directly:
// every RECT-shaped node's <g class="label"> has transform="translate(0,
// ...)" - zero X offset, because the injected CSS rule `.node .label
// text{text-anchor:middle}` already self-centers each tspan (each has
// x="0") horizontally, and the rect itself is drawn at x=-width/2 so both
// already share the same local x=0 center. But PATH-shaped nodes (cylinder/
// database, at minimum) get a large NONZERO X offset instead - e.g.
// translate(-89.546875, ...) where the path itself is exactly
// width=194.09375 (translate(-97.046875, ...), i.e. correctly centered at
// local x=0) and 89.546875 is EXACTLY half of (194.09375 - 2*7.5 padding) =
// the label's OWN measured width, not 0. That's Mermaid's cylinder-shape
// code re-centering the label a SECOND time on top of text-anchor:middle's
// already-correct centering, shifting it a full half-label-width off
// center. This is a shape-specific quirk in Mermaid's own label placement
// for path-drawn shapes, not something driven by getBBox/getComputedTextLength
// accuracy (the shape's own path IS correctly centered) - so instead of
// trying to reverse-engineer and counteract it inside the layout-measurement
// stubs above, patch it directly in the rendered SVG string: for any node
// group whose shape is a <path> (not <rect>/<circle>/<ellipse> - all of
// which already come out correct), force its label group's transform X
// component to 0, matching every correctly-centered rect node's pattern.
// All of Mermaid's classic-look shapes are horizontally symmetric, so a
// zero X offset (relying entirely on text-anchor:middle) is always the
// right target, not just for cylinders specifically.
// Zeros a <g class="label">'s transform X component if it's nonzero,
// leaving the Y component untouched - shared by both cases below, since
// both are the same underlying double-centering bug (a translate applied
// on top of already-self-centering text-anchor:middle), just triggered by
// two different Mermaid code paths (shape-label vs. edge-label placement).
function zeroLabelX(labelGroup) {
  if (!labelGroup) return false;
  const transform = labelGroup.getAttribute('transform');
  if (!transform) return false;
  const m = /translate\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/.exec(transform);
  if (!m) return false;
  const x = parseFloat(m[1]);
  if (!Number.isFinite(x) || Math.abs(x) < 0.5) return false; // already centered
  labelGroup.setAttribute('transform', `translate(0, ${m[2]})`);
  return true;
}

function fixLabelCentering(svgText) {
  try {
    const dom = new window.DOMParser().parseFromString(svgText, 'image/svg+xml');
    let changed = false;
    // 1) Path-shaped node labels (cylinder/database, etc.) - see the long
    //    comment above for the original 2026-09-26 diagnosis.
    dom.querySelectorAll('g.node').forEach((nodeGroup) => {
      const hasPathShape = nodeGroup.querySelector(':scope > path.basic.label-container') !== null;
      if (!hasPathShape) return;
      if (zeroLabelX(nodeGroup.querySelector(':scope > g.label'))) changed = true;
    });
    // 2) Edge labels (the small background-boxed text along an edge, e.g.
    //    "Delivery Failure"/"Replay Re-ingest") - found 2026-09-26 from a
    //    screenshot: the faint gray background box sat in the right place
    //    along the edge, but the text rendered well to its LEFT of that
    //    box. Same root cause as the cylinder case: Mermaid sets
    //    text-anchor="middle" INLINE on the edge label's <text>/<tspan>
    //    (self-centering, just via an inline attribute here instead of the
    //    CSS class node labels use), then ALSO applies a translate to the
    //    wrapping <g class="label"> - double-centering it off to one side.
    //    Every g.edgeLabel > g.label gets the same zero-the-X-offset fix.
    dom.querySelectorAll('g.edgeLabel').forEach((edgeLabelGroup) => {
      if (zeroLabelX(edgeLabelGroup.querySelector(':scope > g.label'))) changed = true;
    });
    if (!changed) return svgText;
    return new window.XMLSerializer().serializeToString(dom);
  } catch (err) {
    process.stderr.write(
      `fixLabelCentering: post-process failed, returning original svg unchanged: ${String(err && err.stack ? err.stack : err)}\n`
    );
    return svgText;
  }
}

async function renderSvgOnce(mermaidSource) {
  const mermaid = await getMermaid();
  mermaid.initialize(MERMAID_RENDER_CONFIG);
  const id = `mmd-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  // mermaid.render(id, text) - with NO third argument - creates its own
  // temporary <div> under `document.body` internally. Passing an explicit
  // container element instead - an SVG node we create and own, appended
  // under jsdom's real <body> - skips that internal div-creation path and
  // gives Mermaid a container it can render directly into.
  const container = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  document.body.appendChild(container);
  try {
    const { svg } = await mermaid.render(id, mermaidSource, container);
    return fixLabelCentering(svg);
  } finally {
    container.remove();
  }
}

// If a race below is lost (timeout), the loser keeps running in the
// background and may still reject later. With nothing left awaiting it at
// that point, that later rejection becomes an "unhandled promise
// rejection" - which by default crashes the ENTIRE Node process, not just
// this one request. Attach a no-op catch immediately so a late failure on
// an already-abandoned attempt is swallowed instead of taking the app down
// for every in-flight request.
function withTimeout(promise, ms, timeoutMessage) {
  promise.catch(() => {});
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(timeoutMessage)), ms)),
  ]);
}

async function renderSvgWithSlot(mermaidSource) {
  const release = await acquireSvgSlot();
  try {
    return await withTimeout(renderSvgOnce(mermaidSource), RENDER_TIMEOUT_MS, 'render timed out');
  } finally {
    release();
  }
}

// Rasterization runs out-of-process (rasterizeInWorker/svgToPng), so a slot
// here only bounds how many child processes can be in flight at once - it
// does not protect any shared in-process state.
async function rasterizeWithSlot(svgText, width) {
  const release = await acquireRasterSlot();
  try {
    return await withTimeout(svgToPng(svgText, width), RENDER_TIMEOUT_MS, 'PNG rasterization timed out');
  } finally {
    release();
  }
}

// The rasterizer's SIGABRT has NOT proven deterministic - one deployment
// produced a working PNG on one request and a SIGABRT on a nearly-identical
// one shortly after. Each attempt spawns a fresh, independent child process
// (see rasterizeInWorker), so a retry costs a little time but carries no
// risk of compounding a bad state - worth trying before giving up and
// falling back to SVG.
const PNG_RASTERIZE_MAX_ATTEMPTS = 2;
async function rasterizeWithRetry(svgText, width) {
  let lastErr;
  for (let attempt = 1; attempt <= PNG_RASTERIZE_MAX_ATTEMPTS; attempt += 1) {
    try {
      return await rasterizeWithSlot(svgText, width);
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

/**
 * Validate and render Mermaid source to the requested format(s).
 * Returns { svg?, png?, thumbnailPng?, pngFailed?, pngError? } - svg is a
 * UTF-8 string, png/thumbnailPng are base64-encoded strings.
 *
 * PNG rasterization (lib/rasterizeWorker.mjs, run out-of-process) has
 * native-crashed (SIGABRT) on complex diagrams even after several JS-level
 * mitigations - that crash is now safely contained to its own child
 * process (see rasterizeInWorker), but it can still happen. When it does,
 * this function deliberately does NOT throw: the diagram source is not the
 * problem (unlike a real Mermaid syntax/layout error), so failing the
 * whole request would make a caller like the LLM tool-calling loop think
 * its Mermaid syntax needs fixing and burn retries on an unrelated native
 * fault. Instead it falls back to the SVG - which has proven reliable even
 * when PNG rasterization has not - and flags `pngFailed`/`pngError` so
 * callers can tell the difference and communicate it honestly.
 */
export async function renderMermaid(input) {
  validateInput(input);
  const { mermaid, format = 'png', thumbnail = false } = input;
  const cleanSource = stripDirectives(mermaid);

  const result = {};

  let svgText;
  try {
    svgText = await renderSvgWithSlot(cleanSource);
  } catch (err) {
    // A failure getting to SVG at all (parse error, layout error, timeout)
    // IS a genuine validation-style failure - the diagram source is
    // presumed to be the cause, not the server.
    const wrapped = new ValidationError(`failed to render diagram: ${err.message}`);
    // Preserve the ORIGINAL stack (from inside mermaid/d3/jsdom) as a
    // separate property, purely for diagnostics - err.message alone (e.g.
    // "Cannot read properties of null (reading 'firstChild')") does not say
    // which library/line threw. Not surfaced to end users; only read by the
    // /api/selftest-render diagnostic route.
    wrapped.rendererStack = err.stack;
    throw wrapped;
  }

  if (format === 'svg' || format === 'both') {
    result.svg = svgText;
  }

  let pngError = null;
  if (format === 'png' || format === 'both') {
    try {
      const pngBuf = await rasterizeWithRetry(svgText, FULL_SIZE_WIDTH);
      result.png = pngBuf.toString('base64');
    } catch (err) {
      pngError = err;
    }
  }

  if (thumbnail) {
    try {
      const thumbBuf = await rasterizeWithRetry(svgText, THUMBNAIL_WIDTH);
      result.thumbnailPng = thumbBuf.toString('base64');
    } catch {
      // Non-critical and there's no smaller fallback for a thumbnail - just
      // omit it rather than failing the whole request over it.
    }
  }

  if (pngError) {
    // Always leave the caller with something renderable.
    if (result.svg === undefined) {
      result.svg = svgText;
    }
    result.pngFailed = true;
    result.pngError = `PNG rasterization failed: ${pngError.message}`;
  }

  return result;
}
