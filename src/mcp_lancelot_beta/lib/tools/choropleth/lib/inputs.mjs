// Inputs of the generate_choropleth tool (BUILD_PLAN D34, D36, D42). Pure.
//
// The zod schema in server.mjs accepts numbers or strings for every field and
// leaves them optional, so that every bad value reaches this module and gets
// the tool's own INVALID_INPUT error instead of a generic SDK error.

export const DEFAULT_SIGMA = 3;
export const SIGMA_MIN = 1;
export const SIGMA_MAX = 10;

// D50: the only map box shapes accepted, width:height.
export const MAP_ASPECT_RATIOS = Object.freeze(['1:1', '16:9', '4:3', '5:3', '9:16', '3:4', '3:5']);

export const CHOROPLETH_INPUT_FIELDS = {
  disaster_number: 'Required. FEMA disaster number, e.g. 4673 for DR-4673-FL.',
  pw_number: 'Optional project worksheet (PW) number to highlight, e.g. 4902. The map opens on that PW\'s damage category.',
  applicant_id: 'Optional applicant ID, e.g. 000-UDQ5V-00. Needed only when the PW number exists for more than one applicant in the disaster.',
  sigma_threshold: `Optional outlier threshold: standard deviations above the project's own category mean, ${SIGMA_MIN} to ${SIGMA_MAX}. Default ${DEFAULT_SIGMA}.`,
  as_of: 'Optional snapshot date YYYY-MM-DD (daily snapshots are kept 90 days). Default: the latest snapshot.',
  // Choropleth map display options (D46). Every default keeps the earlier page.
  initial_view: 'Optional choropleth map display: the category filter the map opens on. "pw_category" (default) opens on the pw_number\'s damage category (All when there is no PW); "all" always opens on All. The PW is highlighted on the map either way.',
  show_pause_button: 'Optional choropleth map display: true (default) shows the Pause/Play button for the outlier pulse; false hides it.',
  show_pw_card: 'Optional choropleth map display: true (default) shows the "PW <number>" summary card for pw_number; false hides the card (the PW stays highlighted on the map).',
  show_all_categories_card: 'Optional choropleth map display: true (default) shows the "All categories A-G" summary card in the All view; false hides it.',
  legend_position: 'Optional choropleth map display: "below_cards" (default) or "below_map" (directly under the map, above the summary cards).',
  click_details: 'Optional choropleth map display: "none" (default, hover tooltip only) or "modal": clicking an outlier dot, the highlighted PW or a county opens a details window inside the map area; its X, Escape or a click anywhere outside it closes it.',
  map_aspect_ratio: `Optional choropleth map display: shape of the map box, width:height, one of ${MAP_ASPECT_RATIOS.map((r) => `"${r}"`).join(', ')}. The whole state is fitted inside it, centred. Default: the box follows the state's own shape.`,
};

export const DISPLAY_DEFAULTS = Object.freeze({
  initialView: 'pw_category', pauseButton: true, pwCard: true, allCategoriesCard: true, legendPosition: 'below_cards', clickDetails: 'none', mapAspectRatio: null,
});

function aspectRatio(v) {
  const s = typeof v === 'string' ? v.trim() : null;
  if (s === null || !MAP_ASPECT_RATIOS.includes(s)) throw invalid(`map_aspect_ratio must be one of ${MAP_ASPECT_RATIOS.map((a) => `"${a}"`).join(', ')}, got ${JSON.stringify(v)}`);
  return s;
}

// "16:9" -> [16, 9]; null stays null (the box follows the state's shape).
export function aspectPair(ratio) {
  return ratio ? ratio.split(':').map(Number) : null;
}

function flag(name, v) {
  if (typeof v === 'boolean') return v;
  const s = typeof v === 'string' ? v.trim().toLowerCase() : null;
  if (s === 'true') return true;
  if (s === 'false') return false;
  throw invalid(`${name} must be true or false, got ${JSON.stringify(v)}`);
}

function choice(name, v, allowed) {
  const s = typeof v === 'string' ? v.trim().toLowerCase() : null;
  if (s === null || !allowed.includes(s)) throw invalid(`${name} must be one of ${allowed.map((a) => `"${a}"`).join(', ')}, got ${JSON.stringify(v)}`);
  return s;
}

export function parseDisplay(args = {}) {
  const d = { ...DISPLAY_DEFAULTS };
  if (present(args.initial_view)) d.initialView = choice('initial_view', args.initial_view, ['pw_category', 'all']);
  if (present(args.show_pause_button)) d.pauseButton = flag('show_pause_button', args.show_pause_button);
  if (present(args.show_pw_card)) d.pwCard = flag('show_pw_card', args.show_pw_card);
  if (present(args.show_all_categories_card)) d.allCategoriesCard = flag('show_all_categories_card', args.show_all_categories_card);
  if (present(args.legend_position)) d.legendPosition = choice('legend_position', args.legend_position, ['below_cards', 'below_map']);
  if (present(args.click_details)) d.clickDetails = choice('click_details', args.click_details, ['none', 'modal']);
  if (present(args.map_aspect_ratio)) d.mapAspectRatio = aspectRatio(args.map_aspect_ratio);
  return d;
}

export class ChoroplethError extends Error {
  constructor(code, message, stage, details = null) {
    super(message);
    this.code = code;
    this.stage = stage;
    if (details) this.details = details;
  }
}

function invalid(message) {
  return new ChoroplethError('INVALID_INPUT', message, 'input');
}

function present(v) {
  return v !== undefined && v !== null && !(typeof v === 'string' && v.trim() === '');
}

// Whole numbers given as a number or a digit string.
function wholeNumber(name, v, min, max) {
  const s = typeof v === 'number' ? String(v) : typeof v === 'string' ? v.trim() : null;
  if (s === null || !/^\d+$/.test(s)) throw invalid(`${name} must be a whole number, got ${JSON.stringify(v)}`);
  const n = Number(s);
  if (!Number.isSafeInteger(n) || n < min || n > max) throw invalid(`${name} must be between ${min} and ${max}, got ${s}`);
  return n;
}

export function parseInputs(args = {}) {
  if (!args || typeof args !== 'object' || Array.isArray(args)) throw invalid('arguments must be an object');
  if (!present(args.disaster_number)) throw invalid('disaster_number is required, e.g. 4673');
  const disasterNumber = wholeNumber('disaster_number', args.disaster_number, 1, 99999);

  const pwNumber = present(args.pw_number) ? wholeNumber('pw_number', args.pw_number, 0, 9_999_999) : null;

  let applicantId = null;
  if (present(args.applicant_id)) {
    if (typeof args.applicant_id !== 'string' || !/^[A-Za-z0-9-]{1,40}$/.test(args.applicant_id.trim())) {
      throw invalid('applicant_id must be letters, digits and hyphens, e.g. 000-UDQ5V-00');
    }
    if (pwNumber === null) throw invalid('applicant_id is only used together with pw_number');
    applicantId = args.applicant_id.trim();
  }

  let sigmaThreshold = DEFAULT_SIGMA;
  if (present(args.sigma_threshold)) {
    const n = typeof args.sigma_threshold === 'number' ? args.sigma_threshold
      : typeof args.sigma_threshold === 'string' && /^\d+(\.\d+)?$/.test(args.sigma_threshold.trim()) ? Number(args.sigma_threshold) : NaN;
    if (!Number.isFinite(n) || n < SIGMA_MIN || n > SIGMA_MAX) {
      throw invalid(`sigma_threshold must be a number from ${SIGMA_MIN} to ${SIGMA_MAX}, got ${JSON.stringify(args.sigma_threshold)}`);
    }
    sigmaThreshold = n;
  }

  let asOf = null;
  if (present(args.as_of)) {
    const s = typeof args.as_of === 'string' ? args.as_of.trim() : '';
    const d = /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(`${s}T00:00:00Z`) : null;
    if (!d || Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== s) throw invalid(`as_of must be a date YYYY-MM-DD, got ${JSON.stringify(args.as_of)}`);
    asOf = s;
  }
  return { disasterNumber, pwNumber, applicantId, sigmaThreshold, asOf, display: parseDisplay(args) };
}
