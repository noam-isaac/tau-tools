<h1 align="center">
    🎓 TAU Tools
    <br />
    <img src="https://img.shields.io/badge/updated-2024-purple.svg">
    <img src="https://img.shields.io/pypi/v/tau-tools">
    <img src="https://img.shields.io/badge/license-MIT-blue.svg">
    <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg">
    <img src="https://img.shields.io/badge/tau-unofficial-red.svg">
</h1>

<p align="center">
    <b>A python library to retrieve information about the various plans and courses at Tel Aviv University, and interact with the various servers.</b>
</p>

<p align="center">
    🛠️ <a href="#installation">Installation</a>
    &nbsp;&middot&nbsp;
    💡 <a href="#features">Features</a>
    &nbsp;&middot&nbsp;
    🚗 <a href="#roadmap">Roadmap</a>
</p>

# Installation

## This fork's static dataset deployment

Generated JSON is **not stored in Git**. Git contains the library, refresh and
validation scripts, and deployment configuration. Vercel stores the published
static snapshot. GitHub Actions builds and deploys it directly, without uploading
a separate Actions artifact. There is no scraper API and browsing Dib It does not run TAU requests.

The configured weekly job (Saturday, 22:23 UTC) discovers the newest academic
year from TAU and fetches its schedules, exams, prerequisites and study plans,
including annual courses. The job reuses the original prerequisite/plan scrapers.
There are no runtime downloads from Arazim. Saved historical catalogs/plans,
grades, bidding and archived exam links are retained from our own snapshot.
`info.json` is also retained and must be maintained locally. The generated
`/snapshot.json` marks each file as refreshed or retained and preserves the
source and any recorded refresh timestamp of retained files. A successful run
is evidence of a course/plan refresh, not fresh grades, bidding or exam links.

| Dataset | Source and remaining limitation |
| --- | --- |
| Schedules, exam dates, prerequisites, study plans | Original TAU generators, newest year only; historical years stay saved. |
| Calendar and default semester | Our saved `data/info.json`; no generator exists here. Update dates and `currentSemester` explicitly. Missing new-year dates stop publication before course scraping. |
| Public grade statistics | Saved `grades.json`; no generator exists here. The IMS/Moodle grade APIs retrieve a logged-in student's grades, not this public aggregate. |
| Bidding statistics | Saved `bidding.json`. The upstream standalone scraper exists, but its scheduled workflow does not run it. It queries nine semester/round combinations per supported course with no year filter; enabling it would add a separate, substantial scrape. |
| Archived exam links | Saved course `exam_links`; the upstream generator requires an interactive Moodle login. New courses have no saved links. This does not affect fresh exam dates. |
| Missing historical files | No Arazim backfill. Missing indexed course catalogs stop publication; historically unavailable optional study plans remain unavailable. |

This removes dependence on Arazim's availability, but it does **not** make all
supplementary data independently regenerable. Grade/bidding displays and archived
links can become outdated. The saved semester default does not advance itself.
A clean checkout must restore our snapshot; losing every saved copy loses data
that these scheduled generators cannot rebuild. No extra backup service is added.

The schedule is once weekly, below Arazim's published Sunday/Thursday cadence.
Saturday 22:23 UTC is Sunday 00:23 in Israel in winter or 01:23 in summer.
Source refreshes may start only between 22:00 and 04:00 UTC and are terminated
at 04:00 UTC (06:00/07:00 Israel). This guard also applies to manual source
refreshes and delayed scheduled jobs. A timeout leaves the previous deployment
intact. Manual reuse-only publication does not scrape and is not time-restricted.

TAU school searches run sequentially and stop at the first failure. A fresh
per-run cache reuses repeated exam requests. The pipeline requires complete,
valid calendar dates for the refreshed year and our saved current semester
before scraping course data. A missing calendar blocks publication rather than
creating empty dates; our `info.json` determines the app default.
Schema validation checks the fields consumed by Dib It, including nested exam,
plan, grade and bidding records. Historical optional/missing fields remain valid.

Publication restores the last snapshot from Vercel, refreshes in a temporary
directory, validates the result and deploys the prebuilt output directly to Vercel. Failed restore, refresh, validation or deployment
leaves the existing production deployment live. Restored files must match the
manifest's size and checksum; a concurrent source publication fails safely.
Neither publication nor weekly refresh creates a Git commit.

The workflow requires repository variables `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
and secret `VERCEL_TOKEN` (scoped to the TAU Tools Vercel project). Git integration
is disconnected, and `git.deploymentEnabled: false` prevents accidental Git builds
if it is reconnected. The workflow has only `contents: read` permission and checkout
does not persist Git credentials.

The offline-check workflow runs fixture-based tests only. It has no schedule,
source downloads, artifact uploads or deployment credentials.

Refresh-workflow manual dispatch defaults to **reusing the published snapshot**, with no TAU requests. Branch runs create previews; `main` runs publish to production.
Fetching fresh data requires selecting `refresh_sources`, or a scheduled run.
The refresh workflow is paused for review of this migration; merging the PR alone
does not re-enable it. The existing production snapshot remains available meanwhile.

Offline checks (after installing this library):

```sh
python3 scripts/test-static.py
python3 scripts/test-refresh.py
python3 -m tau_tools.annual --self-test
python3 scripts/test-restore.py
```

To build an existing snapshot in a clean checkout without scraping:

```sh
python3 -m pip install .
python3 scripts/restore-snapshot.py
python3 scripts/build-static.py
```

`data/`, `snapshot.json`, `dist/` and `.vercel/` are ignored. The restore command
refuses to overwrite existing inputs. `scripts/refresh-data.py` contacts TAU; do not run it merely to test deployment.
The Arazim bootstrap importer has been removed. Retained files may still name
Arazim in provenance because that is where the original saved copy came from;
that attribution does not cause a network request.

See [CHANGES.md](CHANGES.md) for the upstream comparison, history cleanup,
validation and remaining scraper-load limitations.

### Annual data ownership

`/data/annual-groups.json` is part of the same validated snapshot. The
`tau_tools.annual` module was moved from Dib It, with its offline checks. It uses
TAU's explicit annual-only search (`ckSem=0`), refreshes the newest year in
the weekly pipeline and retains historical years. It reuses exam results already
fetched by the course scraper; any missing annual exam pages are fetched
sequentially, with a one-second delay. Both paths share the exam-table parser.

Classification and exam verification timestamps are independent. Partial source
failures retain the old values/timestamps and record failure metadata. Unknown
first-time years are not fabricated. The build requires a valid versioned annual
feed. A failed full catalog refresh still prevents publication of the whole snapshot.
Dib It only consumes/validates/caches this feed; it no longer bundles the dataset
or owns its generator. Initial migration reuses already verified data without
claiming a new scrape or advancing source verification dates.

## Python library

You can get the latest version of TAU Tools by running `pip install tau-tools`!

# Features

### Moodle API

Here's an example of using the TAU Tools moodle package:

```python
from tau_tools.moodle import Moodle

m = Moodle("username", "123456789", "password", "session.json")
courses = m.get_courses()
print(courses)
print(m.get_recordings(courses[0]))
```

Full documentation will be available soon!

### IMS API

Here's an example of using the TAU Tools ims package:

```python
from tau_tools.ims import IMS

ims = IMS("username", "123456789", "password")
grades = ims.get_all_grades([2023, 2024])
print(grades)
```

## Lobby Dashboard

You can get information about exams happening today by running `python3 -m tau_tools.lobby_dashboard`.

Example:

```python
[
    ExamInfo(
        course_id='03682162',
        course_name='מערכות הפעלה',
        group='08',
        semester=2,
        start_hour='09:00',
        end_hour='12:00',
        building="אודיטור' לב",
        room='009',
        surname_letters='א - ד'
    ),
    ...
]
```

## Scrapers

This fork publishes its snapshot at the following URLs. See the retention limits above:

- https://tau-tools.vercel.app/data/courses-2025a.json
- https://tau-tools.vercel.app/data/courses-2025b.json
- https://tau-tools.vercel.app/data/plans-2025.json

You can also get rolled-up information about all of the courses in https://tau-tools.vercel.app/data/courses.json, using the [collect](#collect-the-data-together) script.

### Get course details

You can get all details about a specific year's courses by running `python3 -m tau_tools.courses` or `python3 -m tau_tools.courses 2025`!

Example:

```json
{
    "03005031": {
        "name": "מבוא לביולוגיה לכימאים",
        "faculty": "מדעים מדויקים/פקולטה למדעים מדויקים",
        "exams": [
            {
                "moed": "א",
                "date": "08/02/2024",
                "hour": "",
                "type": "בחינה סופית"
            },
            ...
        ],
        "groups": [
            {
                "group": "01",
                "lecturer": "ד\"ר מאיו ליאור",
                "lessons": [
                    {
                        "day": "ה",
                        "time": "09:00-10:00",
                        "building": "קפלון",
                        "room": "118",
                        "type": "שיעור"
                    },
                    ...
                ]
            },
            ...
        ]
    },
    ...
}
```

### Get the available plans

You can get all details about the current (and past) study plans in Tel Aviv University by running `python3 -m tau_tools.plans` or `python3 -m tau_tools.plans 2025`!

Example:

```json
{
    "הפקולטה למדעי החברה ע\"ש גרשון גורדון": {
        "תוכנית לתואר שני בתקשורת במסלול מחקרי": {
            "קורסי תואר שני - קורסי ליבה": ["10854101", "10854102"],
            "קורסי תואר שני - קורסי מתודולוגיה": ["10854203", "10464101"],
            ...
        },
        ...
    },
    ...
}
```

### Get the Moodle exam bank

You can get links to all of the exams hosted on Moodle (copying the exams themselves is prohibited) by running `python3 -m tau_tools.moodle_exams`!

Example:

```json
{
    {
        "results": [
            [
                "0321-1100-אלגברה לינארית לפיז-מועד א.pdf",
                "https://moodle.tau.ac.il/pluginfile.php/421164/mod_folder/content/0/0321-1100-%D7%90%D7%9C%D7%92%D7%91%D7%A8%D7%94%20%D7%9C%D7%99%D7%A0%D7%90%D7%A8%D7%99%D7%AA%20%D7%9C%D7%A4%D7%99%D7%96-%D7%9E%D7%95%D7%A2%D7%93%20%D7%90.pdf"
            ],
            ...
        ],
        "year": 2024
    },
    ...
}
```

### Collect the data together

Running `python3 -m tau_tools.collect` will go over all courses and moodle exams JSONs in the current directory and place the moodle exam data into the courses jsons. It also creates a summary `courses.json` which contains rolled-up information from all of the courses jsons.

An optional `corrections.json` file is available to account for errors in the moodle exam bank.

The current corrections are:

```json
{
  "03514321": "03514312",
  "03662016": "03662106",
  "03211110": "03211100",
  "032121012": "03213101",
  "03683035": "03683058",
  "03664841": "03724841",
  "03724453": "03724553",
  "03513118": "03653118",
  "03664041": "03684041",
  "03651105": "03681105",
  "03684229": "03684429",
  "03214308": "03213804",
  "03664117": "03214117",
  "03664127": "03214127"
}
```

# Roadmap

- [x] Get courses
- [x] Get plans
- [x] Create a nicer interface to the IMS
- [x] Create a nicer interface to the Moodle
- [ ] Make the scripts accept command-line parameters
- [x] Add the package to PyPI for a simpler installation
- [x] Show progress bars during scraping

# Acknowledgements

This repository contains modified versions of the following tools:

- [CourseScrape](https://github.com/TAUHacks/CourseScrape)
- [CLIMS](https://github.com/TAUHacks/clims)
