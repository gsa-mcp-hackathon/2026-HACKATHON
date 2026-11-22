// Reads the Choropleth data the load job exports to a Unity Catalog volume
// (BUILD_PLAN D41) and the county shapes (D42), with the app's service
// principal through the Files API. `readFile(path) -> Buffer` is injectable
// for tests; a missing file must throw an error with status 404.
import { getFile, resolveVolumePath } from '../../../core/tracer.mjs';
import { ChoroplethError } from './inputs.mjs';

export const DEFAULT_DATA_VOLUME = 'users.tom_jacobson.choropleth_data';
export const EXPORT_SCHEMA_VERSION = 1;
export const GEO_SCHEMA_VERSION = 1;
export const DECLARATION_SCHEMA_VERSION = 1;

export function dataRoot(env = process.env) {
  return resolveVolumePath(env.CHOROPLETH_DATA_VOLUME || DEFAULT_DATA_VOLUME);
}

function isNotFound(err) {
  return Boolean(err && (err.status === 404 || err.code === 'ENOENT'));
}

async function readJson(readFile, path) {
  return JSON.parse((await readFile(path)).toString('utf8'));
}

function unavailable(message) {
  return new ChoroplethError('DATA_UNAVAILABLE', message, 'data');
}

// -> { manifest, snapshot, doc }
export async function loadDisaster({ disasterNumber, asOf = null, readFile = getFile, root = dataRoot() }) {
  if (!root) throw unavailable('the Choropleth data volume is not configured (CHOROPLETH_DATA_VOLUME)');
  let manifest;
  try {
    manifest = await readJson(readFile, `${root}/manifest.json`);
  } catch (err) {
    throw unavailable(`cannot read the data manifest: ${String(err && err.message ? err.message : err).slice(0, 200)}`);
  }
  const snapshots = Array.isArray(manifest && manifest.snapshots) ? manifest.snapshots : null;
  if (!snapshots || manifest.schemaVersion !== EXPORT_SCHEMA_VERSION) throw unavailable('the data manifest has an unknown format');
  const dates = snapshots.map((s) => s.date);
  const wanted = asOf || manifest.latest;
  const snapshot = snapshots.find((s) => s.date === wanted);
  if (!snapshot) {
    if (asOf) {
      throw new ChoroplethError('SNAPSHOT_NOT_FOUND', `no snapshot for ${asOf}; available: ${dates.join(', ') || 'none'}`, 'data', { available: dates });
    }
    throw unavailable('the data manifest lists no latest snapshot');
  }
  let doc;
  try {
    doc = await readJson(readFile, `${root}/snapshots/${snapshot.date}/disasters/${disasterNumber}.json`);
  } catch (err) {
    if (isNotFound(err)) {
      throw new ChoroplethError('DISASTER_NOT_LOADED',
        `disaster ${disasterNumber} has no Public Assistance projects in the ${snapshot.date} snapshot (declarations since ${manifest.declarationsSince || 'unknown'})`, 'data');
    }
    throw unavailable(`cannot read disaster ${disasterNumber}: ${String(err && err.message ? err.message : err).slice(0, 200)}`);
  }
  if (!doc || doc.schemaVersion !== EXPORT_SCHEMA_VERSION || doc.disasterNumber !== disasterNumber
      || doc.loadId !== snapshot.loadId || !Array.isArray(doc.projects) || !Array.isArray(doc.categories)) {
    throw unavailable(`the file for disaster ${disasterNumber} does not match the manifest's load ${snapshot.loadId}`);
  }
  return {
    manifest: { latest: manifest.latest, snapshots: dates, declarationsSince: manifest.declarationsSince ?? null },
    snapshot,
    doc,
  };
}

// FEMA declaration areas for the square image (D44), written by
// ops/declarations_load.py. -> { decl, error }; never throws: a missing or
// unreadable file means the fallback image, not a failed call.
export async function loadDeclaration({ disasterNumber, readFile = getFile, root = dataRoot() }) {
  if (!root) return { decl: null, error: 'data volume not configured' };
  try {
    const decl = await readJson(readFile, `${root}/declarations/v${DECLARATION_SCHEMA_VERSION}/disasters/${disasterNumber}.json`);
    if (!decl || decl.schemaVersion !== DECLARATION_SCHEMA_VERSION || decl.disasterNumber !== disasterNumber || !Array.isArray(decl.affectedFips)) {
      return { decl: null, error: 'unknown declaration file format' };
    }
    return { decl, error: null };
  } catch (err) {
    return { decl: null, error: isNotFound(err) ? 'not found' : String(err && err.message ? err.message : err).slice(0, 200) };
  }
}

// County shapes per state FIPS -> { states: {SS: geo}, missing: [SS], errors: [{state, error}] }.
// Never throws: missing shapes mean "no map", not a failed call (D42).
export async function loadGeometry({ stateFips, readFile = getFile, root = dataRoot() }) {
  const out = { states: {}, missing: [], errors: [] };
  for (const ss of stateFips) {
    if (!/^\d{2}$/.test(ss)) continue;
    try {
      const geo = await readJson(readFile, `${root}/geo/v${GEO_SCHEMA_VERSION}/states/${ss}.json`);
      if (!geo || geo.schemaVersion !== GEO_SCHEMA_VERSION || geo.stateFips !== ss || !Array.isArray(geo.counties)) {
        out.errors.push({ state: ss, error: 'unknown shape file format' });
      } else {
        out.states[ss] = geo;
      }
    } catch (err) {
      if (isNotFound(err)) out.missing.push(ss);
      else out.errors.push({ state: ss, error: String(err && err.message ? err.message : err).slice(0, 200) });
    }
  }
  return out;
}
