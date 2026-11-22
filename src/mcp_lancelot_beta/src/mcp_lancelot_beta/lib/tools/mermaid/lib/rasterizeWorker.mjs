// Standalone worker process: rasterizes SVG (read from stdin) to PNG
// (written to stdout) using @resvg/resvg-js.
//
// Why this exists as a SEPARATE process rather than being called in-process
// from lib/render.mjs: the app crashed the whole Node server multiple times
// (confirmed via app_status going to CRASHED shortly after exercising the
// PNG render path, surviving several increasingly specific JS-level
// mitigations - an oversized-canvas guard, disabling system font scanning,
// stripping CSS @keyframes blocks) and NONE of those JS-level fixes
// prevented it, including process-level unhandledRejection/uncaughtException
// handlers. That combination means the crash is not a catchable JS
// exception at all - it is almost certainly a native crash (segfault/panic)
// inside @resvg/resvg-js's Rust binary on some as-yet-unidentified aspect of
// this diagram's generated SVG. Since we have no working log access in this
// workspace (`apps logs`: PAT/OAuth failure; getAppsLogs tool: hardcoded to
// reject non-*.databricksapps.com hosts, which excludes this gov-cloud
// app's *.databricksapps.us URL) to pin down which specific SVG feature
// triggers it, the pragmatic fix is process isolation: run the rasterizer in
// its own child process, so if IT crashes/segfaults, only this child dies -
// the parent Express server sees a non-zero exit code or a kill signal (a
// normal, catchable Node event on the ChildProcess object), not its own
// process dying, and can return a clean per-request error instead of taking
// down every in-flight request.
import { Resvg } from '@resvg/resvg-js';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

// Confirmed root cause of the "diagram renders but every label is blank"
// report: this container ships NO system fonts at all (same "no apt/root
// access to install missing packages" constraint hit earlier with
// Chromium's missing libgobject-2.0.so.0). Reverting to resvg's default
// (`loadSystemFonts` unset, i.e. true) stopped the earlier SIGABRT crash
// because it gave resvg *something* to scan instead of a guaranteed-empty
// font database, but the scan still finds zero fonts in this container -
// so text-shaping silently degrades to "draw no glyphs" instead of
// panicking. Neither state ever actually renders text. Fix: bundle a
// license-free TTF via the `dejavu-fonts-ttf` npm dependency and point
// resvg at it explicitly, so text rendering no longer depends on whatever
// fonts (if any) the container image happens to ship.
//
// Deliberately discovers the .ttf files by walking the installed package's
// directory rather than hardcoding an internal subpath - npm packages
// reorganize internal folder layouts across versions, and a wrong
// hardcoded path would fail exactly the same way a missing font does
// (silently blank text), which is much harder to notice than a loud
// "package has no .ttf files" warning at worker startup.
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
    // No worse than the pre-fix state (missing text) - never let font
    // discovery itself be a new crash/failure source for rendering.
    process.stderr.write(`findBundledFontFiles failed: ${String(err && err.stack ? err.stack : err)}\n`);
    return [];
  }
}

const BUNDLED_FONT_FILES = findBundledFontFiles();

const targetWidthPx = Number(process.argv[2]);

const chunks = [];
process.stdin.on('data', (chunk) => chunks.push(chunk));
process.stdin.on('end', () => {
  try {
    const svgText = Buffer.concat(chunks).toString('utf8');
    // The parent app (via process isolation) confirmed the earlier crash
    // was SIGABRT - the signature of a Rust panic converted to an abort
    // (typical for native Node bindings, since unwinding across an FFI
    // boundary is unsafe) - traced at the time to `loadSystemFonts: false`
    // with no fontFiles leaving resvg's font database entirely EMPTY, a
    // plausible `unwrap()`/`expect()` panic trigger. Simply re-enabling
    // system font scanning avoided that crash but did NOT fix rendering:
    // this container ships no system fonts either, so the scan still finds
    // nothing and text silently comes out blank (see findBundledFontFiles
    // above for the full story). Supplying our own bundled font file(s)
    // fixes both problems at once - the font database is non-empty (no
    // panic risk) AND actually has a font to shape glyphs with (no more
    // blank text). `loadSystemFonts: false` is safe again here specifically
    // BECAUSE fontFiles is non-empty when found; falls back to leaving
    // resvg's font config untouched (today's behavior) if bundling the font
    // ever fails, so this change can only make text rendering better or
    // leave it exactly as-is - never worse/crashier.
    const resvg = new Resvg(svgText, {
      fitTo: { mode: 'width', value: targetWidthPx },
      background: 'white',
      ...(BUNDLED_FONT_FILES.length > 0
        ? { font: { fontFiles: BUNDLED_FONT_FILES, loadSystemFonts: false, defaultFontFamily: 'DejaVu Sans' } }
        : {}),
    });
    const png = resvg.render().asPng();
    process.stdout.write(png, (err) => {
      process.exit(err ? 1 : 0);
    });
  } catch (err) {
    process.stderr.write(String(err && err.stack ? err.stack : err));
    process.exit(1);
  }
});
