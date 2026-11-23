# Security Policy

## Reporting a vulnerability

Please report security issues responsibly and avoid filing public issues with exploit details.

When reporting, please contact this repo's owner, Tom Jacobson: tom.jacobson@hq.dhs.gov

When reporting, include:

- A clear description of the impact (what an attacker can do).
- Reproduction steps or a proof-of-concept.
- Affected versions/commit(s) and environment details (browser, OS).

## Dependency and supply-chain notes

- This is a client-side app; treat any diagram input as untrusted.
- Mermaid output is inserted into the DOM via `dangerouslySetInnerHTML` (`src/App.tsx`), so Mermaid configuration is a primary XSS safety boundary.
- Mermaid is initialized with `securityLevel: 'strict'` and `htmlLabels: false` in `src/lib/mermaidClient.ts`. Keep these defaults unless you have a reviewed reason to change them.
- Diagram source may include Mermaid directives like `%%{init: ... }%%` (the app also appends an init directive for theme selection). Do not allow user-provided input to downgrade security-critical settings such as `securityLevel` or `htmlLabels`.

## CI security scanning

- GitLab CI runs OWASP Dependency-Check (configured via `.gitlab-ci.yml`) with `failOnCVSS: 8` and `suppression.xml`.
- CI disables `npm audit` (`NPM_CONFIG_AUDIT=false`); Dependency-Check is the primary automated dependency vulnerability signal for this repo.
- The artifacts for each dependency check run are available to download in the GitLab pipeline in the security stage.

## Updating Mermaid.js (library upgrade)

This repo pins Mermaid via `package.json` (`dependencies.mermaid`).

Suggested upgrade workflow:

1. Choose a target Mermaid version (prefer the latest stable release) and review Mermaid’s release notes/changelog for breaking changes.
2. Update the pinned dependency and lockfile:
   - `npm install --save-exact mermaid@<version>`
3. Run validation:
   - `npm test`
   - `npm run build`
   - Smoke test locally with `npm run dev` (render a few diagram types and try both PNG/SVG exports).

If a Mermaid upgrade changes supported syntax or diagram detection behavior, refresh the local docs snapshot and regenerate the in-app “Syntax help” content (next section).
If a Mermaid upgrade changes sanitization behavior, review the impact of `dangerouslySetInnerHTML` usage and re-verify that `securityLevel: 'strict'` and `htmlLabels: false` are still enforced.

## Refreshing Mermaid docs + regenerating “Syntax help”

The app’s “Syntax help” panel is generated from Mermaid’s Markdown docs:

- Generator script: `scripts/generateDiagramHelp.ts` (runs via `npm run generate:diagram-help`)
- Generated output: `src/lib/diagramHelp.generated.ts`
- Docs input: Mermaid’s `docs/syntax/` Markdown files
- Optional inputs:
  - `MERMAID_DOCS_DIR`: points to a Mermaid repo checkout or a `docs/syntax` directory (the generator will use `${MERMAID_DOCS_DIR}/docs/syntax` if it exists)
  - `DIAGRAM_HELP_VERBOSE=1`: prints full lists of missing syntaxes and unmapped docs files
- Generator output notes:
  - Prints `wrote ...` vs `no changes (skipped write) ...` depending on whether generated content changed (ignoring the `generatedAt` timestamp)
  - “missing syntaxes” are syntaxes expected by the app’s `DIAGRAM_TYPES` but not found in the docs
  - “unmapped docs files” are docs markdown files that were discovered but not associated with an expected syntax

### Get the latest docs from Mermaid (source of truth)

Mermaid’s website content is built from the `mermaid-js/mermaid` repository. To pull the latest syntax docs:

```bash
git clone https://github.com/mermaid-js/mermaid.git /tmp/mermaid
cd /tmp/mermaid
git checkout <mermaid-tag-or-commit>
```

Then point the generator at that checkout (it will read `docs/syntax/` automatically):

```bash
cd /path/to/this-repo
MERMAID_DOCS_DIR=/tmp/mermaid npm run generate:diagram-help
```

### Using the vendored `docs/mermaid_docs/` folder (optional)

If you maintain a snapshot of Mermaid docs inside this repo under `docs/mermaid_docs/`, update that folder (copy Mermaid’s `docs/syntax/*.md` into `docs/mermaid_docs/`) and regenerate using:

```bash
MERMAID_DOCS_DIR=./docs/mermaid_docs npm run generate:diagram-help
```

After regenerating, commit the updated `src/lib/diagramHelp.generated.ts` alongside any updated doc snapshots.

## Development server exposure

- `npm run dev` and `npm run preview` can bind to non-local interfaces (`0.0.0.0`). Do not expose these endpoints to untrusted networks.
- Prefer running locally, or ensure host allowlisting/firewalling is in place before allowing network access.
