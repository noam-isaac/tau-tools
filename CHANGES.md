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
GitHub Actions uploads the validated Vercel Build Output API artifact, retains it
for **one day**, and deploys it with `vercel deploy --prebuilt`. There is no new
Blob store, database, Git LFS storage or permanent GitHub release archive.
The workflow has `contents: read`, does not persist checkout credentials, and
contains no `git add`, `git commit` or `git push` publication step.

The existing production snapshot remains available while the code is reviewed.
Git integration for the TAU Tools Vercel project was disconnected before changing
GitHub history. The weekly workflow is disabled during review. Manual dispatch
normally republishes existing data; `artifact_only` saves the build without a
deployment, and `refresh_sources` explicitly requests new TAU/Arazim traffic.
Scheduled runs refresh sources. Non-main publication runs create previews.

A fresh checkout restores the last snapshot from Vercel. The restore validates
filenames, JSON objects, byte lengths and SHA-256, and refuses to overwrite
existing inputs. Failed source refreshes or builds do not replace the live site.
The Python build emits both `dist/` and `.vercel/output/`; the latter is the
portable deployment artifact. Only public datasets, provenance and an index
are included. No scraped HTML cache is uploaded.

## Differences from original Arazim code

- `.github/workflows/scrape.yml`: replaces the original scraper/artifact job with
  weekly latest-two-year refresh, validation, short-lived artifacts and Vercel
  publication. Adds offline PR checks in `check.yml`.
- `src/tau_tools/courses.py`: supports annual and multi-semester exam lookups;
  validates regular and take-home exam tables (including mixed row lengths);
  rejects unknown empty/error pages; finishes stateful search pagination before
  exam lookups; guards against repeated pages; reuses HTTP sessions.
- `src/tau_tools/utilities.py`: adds a 60-second timeout, HTTP error checking,
  GET retries with backoff, and reusable sessions.
- `scripts/import-published-data.py`: imports Arazim public JSON, validates JSON
  objects, retries interrupted downloads, records provenance and absent plans.
- `scripts/refresh-data.py`: discovers the newest two academic years from TAU,
  imports supplementary/history data from Arazim, refreshes TAU schedules/exams,
  preserves supplementary course fields and validates in a temporary directory.
- Build, restore and offline test scripts implement static publication and
  regression checks. No new Python package dependency was added.
- README, ignore files and Vercel configuration document and support deployment.
  Generated JSON remains ignored; only the configuration `vercel.json` is tracked.

This reproduces Arazim's separation of generated artifacts from Git. Their public
workflow uploads artifacts and their repository ignores JSON. Their public source
does not establish how their production website publishes those artifacts.

## History cleanup

The previous fork tip was `4940a430fe48208fb853de0e1c71ac00468a6399`.
All 11 commits after the upstream base belonged to this session. To expose the
whole implementation as one reviewable change, `main` is restored to that exact
upstream base and this branch is a clean code-only commit on top. No upstream
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

The scraper still uses four parallel TAU workers and a per-exam delay of 0.2s;
it has no global request limiter, global deduplication or request/byte accounting.
These are pre-existing changes from this session, visible in this PR, and are
not described as solved by the storage migration. The schedule remains paused.

The prior audit counted 21,890 completed group records in the successful run and
32,374 across logged completed batches in all attempts. These are **not HTTP
request counts**. The rough estimate of 30,000–60,000 TAU requests across the prior
attempts is not a measured total or guaranteed range. TAU transferred bytes were
not recorded. No new TAU requests are made to verify this storage migration.

## Verification and activation

Offline parser, failed-publication, build-output and restore checks are run locally
and in PR CI. The existing 65-file snapshot is used for artifact/preview verification;
byte lengths and SHA-256 values must match its manifest.

Automatic deployment needs the repository secret `VERCEL_TOKEN` and variables
`VERCEL_ORG_ID` and `VERCEL_PROJECT_ID`. The variables are configured. The logged-in
Vercel CLI can deploy, but Vercel rejected creating a project-scoped token with
"Cannot create tokens for this app". No token was created or private auth files read.
A project-authorized token must be added as the Actions secret before automatic
publication can run. The credential check happens before source requests.

Review/merge and workflow re-enablement remain pending. The existing production
feed stays live. The PR description records exact validation runs and preview links.
