// Extracts plain text from an uploaded document so it can be handed to the
// LLM as context for diagram suggestions. Supports PDF, DOCX, XLSX, HTML,
// CSV, JSON, YAML, and plain text; anything else is rejected.
import mammoth from 'mammoth';
// Reuses the jsdom dependency already bundled for lib/render.mjs's Mermaid
// rendering pipeline - no new dependency added just for HTML text extraction.
import { JSDOM } from 'jsdom';
// exceljs was chosen over the `xlsx` (SheetJS) package for supply-chain
// reasons: SheetJS stopped publishing patched versions of known CVEs
// (prototype pollution / ReDoS) to the npm registry, requiring an
// off-registry CDN install to get fixes - which bypasses normal npm
// audit/Dependabot/SBOM tooling. exceljs ships all its releases (including
// security fixes) through the standard npm registry. NOTE: exceljs only
// reads the modern OOXML .xlsx format, NOT the legacy binary .xls format -
// .xls is intentionally not supported here.
import ExcelJS from 'exceljs';

const MAX_EXTRACTED_CHARS = 60_000;

export class UnsupportedFileError extends Error {}

function truncate(text) {
  if (text.length <= MAX_EXTRACTED_CHARS) return text;
  return `${text.slice(0, MAX_EXTRACTED_CHARS)}\n\n[... truncated ...]`;
}

// exceljs cell.value is not always a plain string/number - it can be a Date,
// a rich-text object ({ richText: [{ text }, ...] }), or a formula object
// ({ formula, result }). Normalize all of those down to a plain string so
// the sheet reads like a CSV dump for the LLM.
function formatCellValue(value) {
  if (value === null || value === undefined) return '';
  if (value instanceof Date) return value.toISOString();
  if (typeof value === 'object') {
    if (Array.isArray(value.richText)) return value.richText.map((run) => run.text ?? '').join('');
    if ('result' in value) return value.result === null || value.result === undefined ? '' : String(value.result);
    if ('text' in value) return String(value.text);
    return JSON.stringify(value);
  }
  return String(value);
}

export async function extractText({ buffer, originalName, mimeType }) {
  const lowerName = (originalName || '').toLowerCase();

  if (mimeType === 'application/pdf' || lowerName.endsWith('.pdf')) {
    // Lazy-imported because pdf-parse touches the filesystem at module load
    // time in some versions; keeping it out of the top-level import list
    // avoids that running for requests that don't need it.
    //
    // IMPORTANT: import the internal `lib/pdf-parse.js` module, NOT the
    // package's main `index.js`. pdf-parse@1.1.1's index.js has a
    // long-standing bug: it runs `let isDebugMode = !module.parent;` and,
    // when true, tries to synchronously read a nonexistent test fixture
    // (`./test/data/05-versions-space.pdf`) relative to the current working
    // directory - throwing ENOENT before the real `pdfParse(buffer)` call
    // below ever runs. That check misfires specifically when a CJS package
    // like this is loaded via a dynamic `import()` from ESM code (this
    // file's usage pattern) - Node's CJS/ESM interop can leave the
    // resulting module's `module.parent` undefined even though it's not
    // actually the entry point. Importing the internal implementation
    // module directly skips index.js (and its debug block) entirely.
    const pdfParse = (await import('pdf-parse/lib/pdf-parse.js')).default;
    const result = await pdfParse(buffer);
    return truncate(result.text || '');
  }

  if (
    mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
    lowerName.endsWith('.docx')
  ) {
    const result = await mammoth.extractRawText({ buffer });
    return truncate(result.value || '');
  }

  if (
    mimeType === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
    lowerName.endsWith('.xlsx')
  ) {
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(buffer);
    const sheetTexts = [];
    workbook.eachSheet((worksheet) => {
      const rows = [];
      worksheet.eachRow({ includeEmpty: false }, (row) => {
        const cells = [];
        row.eachCell({ includeEmpty: true }, (cell) => {
          cells.push(formatCellValue(cell.value));
        });
        rows.push(cells.join(', '));
      });
      sheetTexts.push(`--- Sheet: ${worksheet.name} ---\n${rows.join('\n')}`);
    });
    return truncate(sheetTexts.join('\n\n'));
  }

  if (mimeType === 'text/html' || lowerName.endsWith('.html') || lowerName.endsWith('.htm')) {
    // Parse into a real DOM (via jsdom) and pull textContent so markup,
    // <script>, and <style> content is stripped rather than handed to the
    // LLM as raw tag soup. This intentionally checked BEFORE the generic
    // text/* branch below, since 'text/html' would otherwise match there
    // first and skip tag-stripping entirely.
    const dom = new JSDOM(buffer.toString('utf8'));
    const doc = dom.window.document;
    doc.querySelectorAll('script, style').forEach((el) => el.remove());
    const text = doc.body?.textContent ?? doc.documentElement?.textContent ?? '';
    return truncate(text.replace(/\n{3,}/g, '\n\n').trim());
  }

  if (
    mimeType?.startsWith('text/') ||
    lowerName.endsWith('.txt') ||
    lowerName.endsWith('.md') ||
    lowerName.endsWith('.csv') ||
    lowerName.endsWith('.json') ||
    lowerName.endsWith('.yaml') ||
    lowerName.endsWith('.yml')
  ) {
    // .csv is also usually covered by the mimeType?.startsWith('text/')
    // check above (browsers commonly send 'text/csv'), but the extension
    // check is kept as a fallback since some browsers/OSes send
    // 'application/vnd.ms-excel' for .csv. .json/.yaml/.yml mimetypes
    // ('application/json', 'application/x-yaml', etc.) do NOT start with
    // 'text/', and browsers frequently leave file.type empty for .yaml/.yml
    // entirely (unrecognized extension) - so these rely on the extension
    // check, not the mimetype check.
    return truncate(buffer.toString('utf8'));
  }

  throw new UnsupportedFileError(
    `unsupported file type for "${originalName}" - please upload a PDF, DOCX, XLSX, HTML, CSV, JSON, YAML, or plain text file`
  );
}
