// Outlier selection and summary figures for one disaster (BUILD_PLAN D34-D36). Pure.
//
// sigma and the category statistics come precomputed from the gold tables
// (population stddev, each project judged against its own category, as 2026h);
// only the threshold is applied here, because it is a tool input. The LLM is
// never involved (D33).
import { ChoroplethError } from './inputs.mjs';

export const MAP_CATEGORIES = ['A', 'B', 'C', 'D', 'E', 'F', 'G'];
export const ALL = 'ALL';

export function isOutlier(p, threshold) {
  return typeof p.sigma === 'number' && Number.isFinite(p.sigma) && p.sigma >= threshold;
}

function projectKey(p) {
  return `${p.pw}|${p.applicantId ?? ''}|${p.category ?? ''}`;
}

function findHighlight(doc, pwNumber, applicantId) {
  if (pwNumber === null) return null;
  const matches = doc.projects.filter((p) => p.pw === pwNumber && (!applicantId || p.applicantId === applicantId));
  if (matches.length === 0) {
    const who = applicantId ? ` for applicant ${applicantId}` : '';
    throw new ChoroplethError('PW_NOT_FOUND', `PW ${pwNumber}${who} is not in disaster ${doc.disasterNumber}`, 'analysis');
  }
  const applicants = [...new Set(matches.map((p) => p.applicantId))];
  if (applicants.length > 1) {
    throw new ChoroplethError('INVALID_INPUT',
      `PW ${pwNumber} exists for ${applicants.length} applicants in disaster ${doc.disasterNumber}; add applicant_id (one of ${applicants.slice(0, 10).join(', ')}${applicants.length > 10 ? ', ...' : ''})`,
      'input');
  }
  return matches[0];
}

export function analyze(doc, { sigmaThreshold, pwNumber = null, applicantId = null }) {
  const stats = new Map(doc.categories.map((c) => [c.code, c]));
  const mapped = doc.projects
    .filter((p) => MAP_CATEGORIES.includes(p.category))
    .map((p) => ({ ...p, key: projectKey(p), outlier: isOutlier(p, sigmaThreshold) }));

  const present = MAP_CATEGORIES.filter((code) => mapped.some((p) => p.category === code));
  const views = [ALL, ...present];
  const inView = (view, p) => view === ALL || p.category === view;

  const countyOutliers = {};
  const statewideOutliers = {};
  for (const view of views) {
    const counties = {};
    let statewide = 0;
    for (const p of mapped) {
      if (!p.outlier || !inView(view, p)) continue;
      if (p.geo === 'COUNTY' && p.countyFips) counties[p.countyFips] = (counties[p.countyFips] || 0) + 1;
      else if (p.geo === 'STATEWIDE') statewide += 1;
    }
    countyOutliers[view] = counties;
    statewideOutliers[view] = statewide;
  }

  // PA projects (categories A-G) per county, all views together: the square image's shade (D44 rev).
  const countyProjects = {};
  let statewideProjects = 0;
  for (const p of mapped) {
    if (p.geo === 'COUNTY' && p.countyFips) countyProjects[p.countyFips] = (countyProjects[p.countyFips] || 0) + 1;
    else if (p.geo === 'STATEWIDE') statewideProjects += 1;
  }

  const categories = present.map((code) => {
    const s = stats.get(code) || {};
    const inCat = mapped.filter((p) => p.category === code);
    return {
      code,
      description: s.description ?? inCat.find((p) => p.categoryDescription)?.categoryDescription ?? null,
      recordCount: s.recordCount ?? null,
      mean: s.mean ?? null,
      stddev: s.stddev ?? null,
      totalAmount: s.totalAmount ?? null,
      projects: inCat.length,
      outliers: inCat.filter((p) => p.outlier).length,
    };
  });

  const outliers = mapped.filter((p) => p.outlier).sort((a, b) => b.sigma - a.sigma || a.pw - b.pw);
  const unmappable = mapped.filter((p) => p.geo !== 'COUNTY' && p.geo !== 'STATEWIDE');

  const h = findHighlight(doc, pwNumber, applicantId);
  let highlight = null;
  if (h) {
    const onMap = MAP_CATEGORIES.includes(h.category);
    const s = stats.get(h.category) || {};
    highlight = {
      key: projectKey(h),
      pw: h.pw,
      applicantId: h.applicantId ?? null,
      title: h.title ?? null,
      category: h.category ?? null,
      categoryDescription: s.description ?? null,
      amount: h.amount ?? null,
      sigma: h.sigma ?? null,
      multipleOfMean: h.multipleOfMean ?? null,
      flagged: isOutlier(h, sigmaThreshold),
      onMap,
      geo: h.geo ?? null,
      county: h.county ?? null,
      countyFips: h.countyFips ?? null,
      state: h.state ?? null,
      note: onMap ? null : `PW ${h.pw} is Category ${h.category}${s.description ? ` (${s.description})` : ''}, not shown on this map`,
    };
  }

  return {
    sigmaThreshold,
    views,
    initialView: highlight && highlight.onMap ? highlight.category : ALL,
    categories,
    mapped,
    outliers,
    countyOutliers,
    statewideOutliers,
    countyProjects,
    statewideProjects,
    highlight,
    totals: {
      projectsAll: doc.projects.length,
      projectsMapped: mapped.length,
      outliers: outliers.length,
      outlierCounties: Object.keys(countyOutliers[ALL]).length,
      statewideOutliers: statewideOutliers[ALL],
      unmappable: unmappable.length,
      unmappableOutliers: unmappable.filter((p) => p.outlier).length,
    },
  };
}
