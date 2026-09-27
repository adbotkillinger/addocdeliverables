# Cloud session brief: Adamic site toolkit

Date: 2026-09-27. Budget: one cloud session, spent from a one-time $100 credit. Work in order and stop at each checkpoint if something is unclear. Do not branch into parallel sessions.

## Bottom line

Turn `tools/` into a small, tested toolkit that checks addocdeliverables.ca against its house rules every week. One checker already works (`adamic_evidence_lint.py`). This session repairs the claims-register generator, adds a navigation checker, hardens the Theme Explorer data checks, and puts everything under offline tests and CI.

## Ground rules

- **The live site is the source of truth.** Read it through the public WordPress REST API (`/wp-json/wp/v2/pages`). Never write to the site.
- **Standard library only.** Python 3.11 or later, no third-party packages, so the scripts run on a stock GitHub runner.
- **This repo is public.** Commit code and test fixtures only: no drafts, no unpublished canon, no credentials.
- **Leave the logo files alone** (`ad-doc-*` at the root).
- **Work on a branch** and open one pull request at the end. Do not push to `main`.
- Canadian spelling in comments and docs (colour, organize).

## Current state (verified 2026-09-27)

| File | State |
|---|---|
| `tools/adamic_evidence_lint.py` | Working. 0 errors across 36 strips and 28 mapped works. It skips struck-through strips (superseded apparatus) and busts the edge cache. |
| `tools/adamic_claims_register.py` | Committed as found in Drive (v2, 2026-09-14). **Broken against current markup**: it finds 2 claims of about 29. See task 2. |
| `.github/workflows/adamic-evidence-lint.yml` | Runs the evidence lint every Monday and on changes to itself. |

## Task 1: shared module

Create `tools/adamic_site.py` and move the duplicated plumbing there:

- `fetch_pages(site, timeout)`: paginates with `X-WP-TotalPages`, sends a cache-busting query parameter plus `Cache-Control: no-cache`, and raises on failure. It must never quietly return a partial list; the old generator's bare `except: break` does exactly that.
- `plain_text`, `anchors`, `normalize_path`, `link_parts`.
- `evidence_strips(markup)`, including `is_struck`.

Both existing scripts import from it. Behaviour of the evidence lint must not change: re-run it and confirm it still reports 0 errors.

## Task 2: repair the claims-register generator

**The failure.** Claims are now published as list items:

```html
<li><strong>UR-DOM-001</strong> (Inferred). <strong>Claim:</strong> …</li>
```

The generator only matches `<p>` blocks that end in `</p>`, with the grade inside `<em>(…)</em>`.

**Required behaviour**

1. Recognize a claim in `<p>` or `<li>`, with the grade in `<em>(Grade)</em>`, plain `(Grade)`, or taken from the surrounding context as before. Grades: Measured, Modelled, Inferred, Asserted, Heuristic; a grade beginning with "Revised" sets status `revised`.
2. Claim ID prefixes are layer-prefixed: `UR-XXX-nnn` today, plus `COS-` (reserved for TΩ). Accept any `[A-Z]{2,5}(-[A-Z]{2,5})?-\d{3}` rather than hard-coding `UR-`.
3. **MOC mapping.** On The Machinery of Cooperation, printed `MOC-nnn` registers as `UR-COOP-nnn`, one for one, with `printed_id` kept. The page prints both forms, so each claim must appear **once**.
4. **Withdrawal.** A claim inside `<s>` or `<del>` is withdrawn. "UR-X is replaced by UR-Y" sets the replacement. UR-MON-001 is withdrawn and replaced by UR-MON-002.
5. Inbound dependents are derived, never typed.
6. Outputs `claims-register.json` and `claims-register.md` as before.
7. Remove the generator's own strip lint. It duplicates the evidence lint and has two bugs: it misses absolute URLs, and it counts struck strips. The generator's exit code covers claims only.

**Lint rules (fail the run):** dangling reference; duplicate ID across pages; active claim that depends on a withdrawn claim; withdrawn claim with no replacement.

**Acceptance**

- Run against the live site, the register contains every distinct claim ID on the site after MOC→COOP mapping. Compute that expected set independently in the test, with a plain regex over all page text, and assert equality. On 2026-09-27 the site carried UR-DOM-001–011, UR-COOP-001–012 (printed MOC-001–012), UR-EVV-001–004 and UR-MON-001/002.
- UR-MON-001 is `withdrawn`, with `replacement: UR-MON-002`.
- No claim appears twice.

**Checkpoint.** If the live count differs from the independent count, stop and report the missing IDs with a markup sample. Do not loosen the parser until it "passes".

## Task 3: navigation checker (report-only)

New script `tools/adamic_nav_check.py`. It checks the house navigation standard (set 2026-09-19):

| Page group | Required opening |
|---|---|
| Radical Reason, Urrepublika, Anastomotic Kino-Materialism | "In this section" line listing all eight Adamic Theory sections, then "In this branch" listing the branch's pages. Current item bolded in each line. |
| The Fascomachy guide and its sub-pages | As above, plus a third line, "In this guide". |
| Strategic Bricolage | Keeps its own nav block (breadcrumb, previous/next, all-documents list), with the "In this section" line added at the top. |
| Apparatus pages: The Evidence Protocol, Canon Lines & Forcing Phrases, Theme Explorer | "In this section" line plus an "Apparatus" line listing the three. |
| Palimpsest | **Exempt**: it keeps its own "Path / Explore" style. |

Derive the eight sections and each branch's membership from the live page tree (parent IDs and `menu_order`), not a hard-coded list. Print the derived tree in the report so it can be checked by eye.

Checks: each line is present, in the right order, and lists the right items; the current page is bolded; no link in the lines is broken (compare against published paths).

**This script warns; it does not fail CI yet.** Compliance across the site is unknown, and the first run is an audit. Write findings to the job summary.

## Task 4: Theme Explorer data checks

Extend the evidence lint's `ate-data` handling (it already flags duplicate IDs, unknown tiers and missing URLs):

- Every work has `id`, `title`, `tier`, `url`, and `id` matches `^[a-z0-9]+$`.
- Any positions or cross-references inside `ate-data` point to work IDs that exist. Inspect the live JSON first and document its schema in a comment before writing checks.
- **Pending nodes.** List, as a warning, pages whose strip links to the bare Theme Explorer with no `?work=`. As of today that includes TΩ, whose `tomega` node is not yet seeded. The report tells the user which nodes are waiting to be added.

## Task 5: offline tests

Use `unittest` with small HTML fixtures in `tests/fixtures/`. There is no network access in tests. Cover at least:

- a struck strip (`<del>`) skipped, and a live strip beside it counted
- a "Test status: …" banner not counted as a strip
- a strip with absolute URLs to the Protocol and Explorer
- claims in `<li>` and `<p>` form, with each grade style
- MOC-nnn and UR-COOP-nnn on one page registering once
- withdrawal via `<s>`, and the "is replaced by" rule
- pagination stopping on `X-WP-TotalPages` and raising on HTTP errors (use a stub opener)

## Task 6: CI

Rename the workflow to `adamic-site-checks.yml`, keeping the Monday schedule and manual trigger, and add pull-request triggers on `tools/**` and `tests/**`. Steps:

1. `python -m unittest discover tests`
2. evidence lint (fails the build)
3. claims register (fails the build), with the two output files uploaded as a workflow artifact
4. navigation check (warnings only)

Write a combined job summary.

## Deliverables

- One pull request titled "Site toolkit: shared module, claims register repair, nav audit, tests". Its description gives the before and after (claims found: 2 → N), the first nav audit summary, and a list of the pending Explorer nodes.
- `tools/README.md`: what each script checks, how to run it locally, and what a failure means in plain terms.

## Out of scope

Editing site content; migrating off WordPress; the Astro or Next.js rebuild; SEO or performance work.
