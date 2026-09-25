# Review of the TAU Tools fork

This branch compares against the original Arazim commit
`ab3097894e0cca37b63214bfcb58369fa411b47c`. It contains the final code changes
from this session, with generated datasets excluded from the entire branch history.

## Storage and publication

The initial implementation mistakenly committed 65 generated JSON files
(138,119,750 bytes in the last snapshot), plus `snapshot.json`. The initial import
was 137,188,871 bytes. These are uncompressed file sizes, not Git pack sizes,
network traffic measurements or billed storage totals.

The replacement keeps code in Git and static files in Vercel deployments.
GitHub Actions builds the validated Vercel Build Output API files and deploys
them directly with `vercel deploy --prebuilt`. It uploads no Actions artifact. There is no new
Blob store, database, Git LFS storage or permanent GitHub release archive.
The workflow has `contents: read`, does not persist checkout credentials, and
contains no `git add`, `git commit` or `git push` publication step.

The existing production snapshot remains available while the code is reviewed.
Git integration for the TAU Tools Vercel project was disconnected before changing
GitHub history. The weekly workflow is disabled during review. Manual dispatch
normally republishes existing data; `refresh_sources` explicitly requests new
TAU traffic. The separate offline-check workflow runs fixture-based tests only, including on
manual dispatch; it does not download or upload production data.
Scheduled runs refresh sources. Non-main publication runs create previews.

A fresh checkout restores the last snapshot from Vercel. The restore validates
filenames, JSON objects, byte lengths and SHA-256, and refuses to overwrite
existing inputs. Failed source refreshes or builds do not replace the live site.
Prebuilt uploads use gzip archives (about 12 MiB for this snapshot). The Python build emits only `.vercel/output/`, the prebuilt deployment artifact.
Only public datasets and provenance are included. No scraped HTML cache is uploaded.

## Differences from original Arazim code

- `.github/workflows/scrape.yml`: replaces the original scraper/artifact job with
  weekly latest-year refresh, validation and Vercel publication. Adds offline PR checks in `check.yml`.
- `src/tau_tools/courses.py`: supports annual and multi-semester exam lookups;
  validates regular and take-home exam tables (including mixed row lengths);
  rejects unknown empty/error pages; finishes stateful search pagination before
  exam lookups; guards against repeated pages; reuses HTTP sessions.
- `src/tau_tools/utilities.py`: adds a 60-second timeout, HTTP error checking,
  GET retries with backoff, and reusable sessions.
- `scripts/refresh-data.py`: discovers the newest academic year from TAU,
  refreshes TAU schedules/exams/prerequisites/plans, preserves saved supplementary
  data and validates in a temporary directory. No Arazim feed downloads remain.
- Build, restore and offline test scripts implement static publication and
  regression checks. `jsonschema` is the one new direct Python dependency, used to
  validate the data contracts consumed by Dib It before publication.
- README, ignore files and Vercel configuration document and support deployment.
  Generated JSON remains ignored; only the configuration `vercel.json` is tracked.

This reproduces Arazim's separation of generated artifacts from Git. Their public
workflow uploads artifacts and their repository ignores JSON. Their public source
does not establish how their production website publishes those artifacts.

## History cleanup

The previous fork tip was `4940a430fe48208fb853de0e1c71ac00468a6399`.
All 11 commits after the upstream base belonged to this session. To expose the
whole implementation as one reviewable change, `main` is restored to that exact
upstream base and this branch contains clean code-only commits on top. No upstream
commit is rewritten, so the GitHub fork relationship and shared Git ancestry remain.
The old generated-data commits are not ancestors of any new branch or tag.

Verification includes a fresh clone from GitHub and an all-ref object/path audit.
GitHub controls garbage collection of unreachable objects; branch cleanup does
not itself prove when GitHub physically reclaims server storage. This migration
is about repository growth and storage, not data confidentiality.

Dib It stores a submodule commit reference, not the child repository's JSON blobs.
Its pointer must move to this clean branch before fetching the rewritten history.
The application feed integration is reviewed separately so unrelated annual-course
work in the existing local workspace remains untouched.

## Existing scraper load limitation

TAU school searches now run sequentially; a failure stops subsequent searches.
A fresh staging directory enables the existing HTTP cache within each run,
reusing repeated exam requests. The normal per-exam delay remains 0.2s; missing
annual exam lookups remain sequential with a one-second delay. There is still
no global request limiter or measured request/byte accounting. The schedule remains paused.

The prior audit counted 21,890 completed group records in the successful run and
32,374 across logged completed batches in all attempts. These are **not HTTP
request counts**. The rough estimate of 30,000–60,000 TAU requests across the prior
attempts is not a measured total or guaranteed range. TAU transferred bytes were
not recorded. No new TAU requests are made to verify this storage migration.

## Verification and activation

Offline parser, failed-publication, build-output and restore checks are run locally
and in PR CI. The current 66-file snapshot includes annual classification/exams alongside the
65 existing datasets; byte lengths and SHA-256 values must match its manifest.

Automatic deployment needs the repository secret `VERCEL_TOKEN` and variables
`VERCEL_ORG_ID` and `VERCEL_PROJECT_ID`. The variables are configured. The logged-in
Vercel CLI can deploy, but Vercel rejected creating a project-scoped token with
"Cannot create tokens for this app". No token was created or private auth files read.
A project-authorized token must be added as the Actions secret before automatic
publication can run. The credential check happens before source requests.

Review/merge and workflow re-enablement remain pending. The existing production
feed stays live. The PR description records exact validation runs and preview links.

Earlier 65-file artifact verification (22 September):
https://github.com/noam-isaac/tau-tools/actions/runs/35729105647
The compressed artifact is 12,404,195 bytes and expires after one day. All 65
files in the downloaded artifact match their manifest. The prebuilt preview
https://tau-tools-p4yp6wujn-noamisaacs-projects.vercel.app is Ready; catalog/info
responses match the manifest, JSON/cache headers are correct, and missing files
return 404. That verification left production on its previous deployment.

Dib It integration review: https://github.com/noam-isaac/dib-it/pull/29

Automatic approval review rejected re-enabling the scheduled refresh workflow
for verification because it would also restore recurring TAU traffic. The
scraper remains disabled; artifact verification succeeded through the separate
workflow that cannot run scrapers.

## Annual data migration (23 September 2026)

Moved the existing annual-classification/exam generator and self-tests out of
Dib It into `src/tau_tools/annual.py`. The weekly refresh writes
`data/annual-groups.json` into the same published snapshot as the catalogs.
Year discovery comes from the Tools pipeline, without reading Dib It source files.
The exam parser is shared with `courses.py`, and already-fetched annual exam
results are reused; missing results use sequential requests with a one-second delay.
Historical years and last-known timestamps survive partial failures.

Dib It's scraper, daily writer and bundled annual JSON are removed on its review
branch. The browser reads `/data/annual-groups.json`, preserves validated local
cache and leaves edits pending when a cold start cannot obtain classification.
Small test-only excerpts replace tests' implicit dependency on the production
fallback. The old deployed app's data branch is frozen during the release transition.
The new annual artifact was seeded from the existing verified snapshots, with no
new TAU requests and no artificial refresh timestamp.

The 66-file preview is
https://tau-tools-6f88aet6r-noamisaacs-projects.vercel.app. Its annual JSON matches
the saved migration input byte for byte (329,434 bytes). The data-only addition
was published to the existing feed; the Dib It application remains unchanged
pending PR review. Both scraper schedules remain disabled.

## Review fixes (24 September 2026)

- Preserve existing historical course files and their provenance at academic-year
  rollover. Only missing history is downloaded; `courses.json` is rebuilt locally.
- Stop TAU school searches at the first failure and reuse within-run HTTP cache.
- Validate consumed nested data shapes before replacing build output. Invalid
  records, including annual exam records, leave the prior snapshot intact.
- Require complete calendar dates for refreshed years and the source-selected
  current semester before school scraping. Preserve existing calendar fields
  when an upstream record omits them; do not invent dates or a default semester.
- Preserve classification failure markers across separate year refreshes; clear
  a marker only when that year succeeds.
- Remove the duplicate late credential check; retain the guard before traffic.

Offline regressions cover each case. All 66 existing saved datasets also pass the
new validation. No TAU requests were used for these checks. Dib It's corresponding
PR consumes per-group annual exams and uses a seven-day freshness threshold;
these are app-side corrections, not a new publication architecture.

## Remove redundant Actions storage (25 September 2026)

Removed the publication job's artifact upload and the separate artifact-only
verification job. Publication uses the local validated build directly; refreshes
still restore the previous Vercel snapshot. Offline checks remain. Historical
artifact evidence above records earlier verification, not the current workflow.
The two previously uploaded public-dataset artifacts were already expired when
checked. This change does not run scrapers, enable schedules or deploy anything.

## One academic year per refresh (25 September 2026)

The refresh now selects only the newest academic year offered by TAU, keeping
the existing newest-year selection policy and dropping the preceding year.
It refreshes both semesters and annual exams for that one year. Saved older
catalogs and annual data retain their bytes/timestamps without TAU re-scraping.
A mocked regression offers two years and verifies that course and annual searches
run only for the newest one, while previous-year files remain untouched.
No TAU requests, workflow activation or deployment were used for verification.

## Restore direct prerequisites/plans; overnight schedule (25 September 2026)

The current-year refresh now uses the original `get_prerequisites` function
(one lookup per course/semester, first group, as upstream does) and `plans.main`.
Current-year plans are no longer downloaded from Arazim; prerequisites from
supplementary catalog downloads are replaced by the direct result, including
confirmed empty results. Historical saved plans remain unchanged. Current plan
provenance records TAU's GraphQL source. Grades, bidding, calendar metadata,
exam links and missing historical files still use the public Arazim feed.

`plans.main` gains an optional strict flag, enabled only by publication, so a
failed plan lookup aborts instead of silently publishing an incomplete result.
Its default CLI behavior remains unchanged. Prerequisite failures also abort
publication, retaining the existing snapshot.

Arazim's live public workflow was checked: `8 6 * * SUN,THU` (twice weekly).
Our schedule remains once weekly and moves to `23 22 * * 6`: Sunday 00:23 Israel
winter / 01:23 summer. Source refreshes are restricted to 22:00-04:00 UTC and
subprocess timeout stops them by the end of that window, including delayed and
manual source runs. The timeout fails publication and preserves the live data.
The workflow remains paused for review; no live TAU scrape was used to test it.
Offline checks cover direct lookups, historical preservation, failed-source
atomicity, the strict plan path and the overnight guard boundaries.

## Remove Arazim feed dependence (25 September 2026)

Deleted the bootstrap importer and every refresh-time Arazim JSON download.
Refresh starts with our restored snapshot, uses direct TAU generators for the
newest year's courses/exams/prerequisites/plans, and rebuilds the aggregate index.
Missing retained inputs fail before course scraping; there is no public-feed
fallback. Historical catalogs/plans and supplementary data are retained.
The manifest distinguishes refreshed and retained files and preserves existing
provenance/timestamps. It no longer labels a new scrape as a feed download.
No change to storage, app runtime, schedule or source request frequency is added.

The independence has limits: this repository contains no public grade-statistics
or calendar generator. Its Moodle exam-link generator needs a login. Its bidding
scraper is not part of the original scheduled workflow and would add nine queries
per supported course with no year filter, so it remains a standalone tool.
Grades, bidding and archived links are therefore retained, not updated weekly.
New courses lack old exam links. Dates in `info.json` and `currentSemester` need
explicit maintenance: unknown new-year dates block the full refresh, and a stale
default can keep Dib It opening an old semester even after course refresh succeeds.
Missing historical courses block publication; optional missing plans stay missing.
Our saved publication is now required to recover supplementary/history inputs.

Local saved-data inspection found `currentSemester: 2026a` despite calendar
entries through 2027b, and bidding records only through 2024b. These are observations
of the saved input, not a new live-source freshness claim. We did not guess a new
default, replace dates or start a bidding scrape. Public grade semester keys even
include 2031a, so the greatest key cannot establish that file's freshness.

Offline regression checks cover a complete refresh with only TAU discovery,
retained data/links/provenance, missing saved inputs, calendar rollover guards,
source failures and historical preservation. No TAU or Arazim requests, workflow
activation or deployment were used for this change.

## Remove unused output support

Removed the HTML dataset landing page, the duplicate `dist/` build tree and
unused source-build settings/duplicate headers in `vercel.json`. Prebuilt output
still contains dataset files, the manifest and the existing cache/CORS routes.
Annual refresh now accepts/writes only the versioned public feed; removed the
unwrapped legacy output mode and adjusted its existing recovery tests.
The staging build followed by the workflow build, and the two separate catalog
assembly implementations, remain unchanged in this cleanup.
