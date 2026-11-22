// Auth helper for calling other Databricks APIs (e.g. Model Serving) as the
// app's own service principal. Databricks Apps automatically inject
// DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET / DATABRICKS_HOST for the
// app's identity - no secrets are hardcoded here.
//
// If your app runtime does not inject these (older runtime, or running
// locally for testing), set them manually via `databricks apps update`'s
// resources/env wiring, or export them in your local shell for `npm run dev`.

let cachedToken = null; // { accessToken, expiresAtMs }

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`missing required environment variable: ${name}`);
  }
  return value;
}

// DATABRICKS_HOST, as injected into this app's environment, is sometimes
// just a bare hostname (e.g. "dhs-hq-prod.cloud.databricks.us") with no
// scheme. Node's fetch requires an absolute URL and throws "Failed to
// parse URL" on a schemeless host, so add https:// when it's missing.
function normalizeHost(rawHost) {
  const trimmed = rawHost.trim().replace(/\/+$/, '');
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

function resolveHost() {
  return normalizeHost(requireEnv('DATABRICKS_HOST'));
}

async function fetchToken() {
  const host = resolveHost();
  const clientId = requireEnv('DATABRICKS_CLIENT_ID');
  const clientSecret = requireEnv('DATABRICKS_CLIENT_SECRET');

  const res = await fetch(`${host}/oidc/v1/token`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString('base64')}`,
    },
    body: new URLSearchParams({
      grant_type: 'client_credentials',
      scope: 'all-apis',
    }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`failed to obtain Databricks OAuth token (${res.status}): ${text.slice(0, 300)}`);
  }

  const json = await res.json();
  return {
    accessToken: json.access_token,
    // Refresh a little before actual expiry.
    expiresAtMs: Date.now() + Math.max((json.expires_in ?? 300) - 30, 30) * 1000,
  };
}

export async function getAccessToken() {
  if (cachedToken && cachedToken.expiresAtMs > Date.now()) {
    return cachedToken.accessToken;
  }
  cachedToken = await fetchToken();
  return cachedToken.accessToken;
}

export function getWorkspaceHost() {
  return resolveHost();
}
