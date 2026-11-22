// Child process for the Choropleth square image (BUILD_PLAN D44): SVG on stdin ->
// PNG on stdout, with @resvg/resvg-js. Own copy, not the Mermaid worker (tool
// code is never shared, invariant 2). A separate process because resvg has
// crashed the whole server natively before (see the Mermaid rasterizeWorker
// history): a crash here kills only this child.
//
// Fonts: the container has no system fonts, so the bundled DejaVu TTFs
// (dejavu-fonts-ttf) are loaded explicitly; the title uses DejaVu Sans Bold.
import { Resvg } from '@resvg/resvg-js';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

function fontFiles() {
  try {
    const dir = path.dirname(require.resolve('dejavu-fonts-ttf/package.json'));
    const found = [];
    const stack = [dir];
    while (stack.length) {
      const d = stack.pop();
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const full = path.join(d, e.name);
        if (e.isDirectory()) stack.push(full);
        else if (e.isFile() && /^DejaVuSans(-Bold)?\.ttf$/i.test(e.name)) found.push(full);
      }
    }
    return found;
  } catch (err) {
    process.stderr.write(`font discovery failed: ${String(err && err.message ? err.message : err)}\n`);
    return [];
  }
}

const width = Number(process.argv[2]) || 1000;
const chunks = [];
process.stdin.on('data', (c) => chunks.push(c));
process.stdin.on('end', () => {
  try {
    const files = fontFiles();
    if (!files.length) throw new Error('no bundled DejaVu font found; the title would be blank');
    const resvg = new Resvg(Buffer.concat(chunks).toString('utf8'), {
      fitTo: { mode: 'width', value: width },
      background: 'white',
      font: { fontFiles: files, loadSystemFonts: false, defaultFontFamily: 'DejaVu Sans' },
    });
    const png = resvg.render().asPng();
    process.stdout.write(png, (err) => process.exit(err ? 1 : 0));
  } catch (err) {
    process.stderr.write(String(err && err.stack ? err.stack : err));
    process.exit(1);
  }
});
