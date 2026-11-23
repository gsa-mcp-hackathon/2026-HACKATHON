// Shared helpers for the unit tests (not a test file itself).
import zlib from 'node:zlib';

// Module locations after the D32 folder move (D37): shared core vs. Mermaid tool.
const CORE_MODULES = new Set(['tracer.mjs', 'databricksAuth.mjs']);
export const LIB = (name) => new URL(
  CORE_MODULES.has(name) ? `../lib/core/${name}` : `../lib/tools/mermaid/lib/${name}`,
  import.meta.url,
).href;

// Builds a real, decodable RGB PNG of the given size (all black).
export function makePng(width, height) {
  const table = [];
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  const crc32 = (buf) => {
    let x = 0xffffffff;
    for (const byte of buf) x = table[(x ^ byte) & 0xff] ^ (x >>> 8);
    return (x ^ 0xffffffff) >>> 0;
  };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const typed = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(typed));
    return Buffer.concat([len, typed, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // RGB
  const raw = Buffer.alloc((1 + width * 3) * height);
  return Buffer.concat([
    Buffer.from('89504e470d0a1a0a', 'hex'),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// Records fetch calls and answers with a queue of canned responses.
// Queue items: { status, body } | { status: 200, content } (chat reply) | { hang: true }.
export function installFetchQueue() {
  const state = { queue: [], calls: [] };
  globalThis.fetch = async (url, opts = {}) => {
    state.calls.push({ url: String(url), method: opts.method || 'GET' });
    if (String(url).includes('/api/2.0/fs/')) return new Response('', { status: 200 });
    const step = state.queue.shift();
    if (!step) throw new Error(`unexpected fetch ${url}`);
    if (step.hang) {
      return new Promise((_, reject) =>
        opts.signal.addEventListener('abort', () => {
          const err = new Error('aborted');
          err.name = 'AbortError';
          reject(err);
        })
      );
    }
    if (step.status !== 200) return new Response(step.body ?? 'error', { status: step.status });
    return new Response(
      JSON.stringify({ choices: [{ message: { content: step.content }, finish_reason: 'stop' }], usage: { prompt_tokens: 10, completion_tokens: 5 } }),
      { status: 200 }
    );
  };
  return state;
}

export const selectReply = (diagramType) => ({ status: 200, content: JSON.stringify({ diagramType, rationale: 'because' }) });
export const mermaidReply = (source) => ({ status: 200, content: '```mermaid\n' + source + '\n```' });
