"""Refresh the newest TAU academic year using our saved snapshot.

Only the workflow publishes changes, after this command and the static build
succeed. HTTP/parse failures therefore leave the deployed snapshot untouched.
"""

import hashlib
import json
import os
import re
import runpy
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from bs4 import BeautifulSoup
from tau_tools.courses import catalog, get_school_courses, get_schools
from tau_tools.collect import main as collect
from tau_tools.annual import refresh as refresh_annual
from tau_tools.plans import main as refresh_plans
from tau_tools.prerequisites import get_prerequisites
from tau_tools.utilities import new_session
from tau_tools.validation import validate_calendar

ROOT = Path(__file__).resolve().parents[1]
TAU = "https://www.ims.tau.ac.il/Tal/KR/Search_P.aspx"
validate = runpy.run_path(str(ROOT / "scripts/build-static.py"))["validate"]


def refresh():
    info = json.loads((ROOT / "data/info.json").read_text())
    with new_session() as session:
        response = session.get(TAU, timeout=60)
    response.raise_for_status()
    options = BeautifulSoup(response.text, "html.parser").select('select[name="lstYear"] option')
    years = sorted({int(o["value"]) + 1 for o in options if re.fullmatch(r"\d{4}", o.get("value", ""))})[-1:]
    if not years:
        raise ValueError("Cannot discover the newest TAU academic year")
    previous_snapshot = json.loads((ROOT / "snapshot.json").read_text())
    # Calendar metadata is maintained in our snapshot, not fetched from another feed.
    # ponytail: no calendar generator upstream; missing dates require a manual update.
    validate_calendar(info, [f"{year}{s}" for year in years for s in ("a", "b")])
    # Detect missing retained inputs before the expensive TAU course lookups.
    for name in ["grades.json", "bidding.json", *[
        f"courses-{semester}.json" for semester in info["semesters"]
        if semester[:4] not in {str(year) for year in years}
    ]]:
        if not (ROOT / "data" / name).is_file():
            raise ValueError(f"Missing saved dataset: {name}; restore our snapshot first")
    with TemporaryDirectory() as directory:
        staging = Path(directory)
        data = staging / "data"
        shutil.copytree(ROOT / "data", data)
        previous_directory = Path.cwd()
        try:
            os.chdir(staging)
            schools = get_schools()
            if not schools:
                raise ValueError("TAU returned no schools")
            searches = [(field, [option]) for field, options in schools for option in options]
            for year in years:
                print(f"Refreshing TAU academic year {year}: {len(searches)} searches", flush=True)
                def read_search(pair):
                    index, school = pair
                    try:
                        result = get_school_courses(index, school, str(year - 1))
                    except Exception as error:
                        print(f"{year} {school}: {error}", flush=True)
                        raise
                    print(f"{year} {school}: {len(result)} groups", flush=True)
                    return result
                # Sequential searches stop at the first failure. Fresh staging also lets
                # the existing HTTP cache reuse repeated exam requests within this run.
                groups = [g for school_groups in map(read_search, enumerate(searches)) for g in school_groups]
                if not groups or any(not re.fullmatch(r"\d{8}", g.id) or not re.fullmatch(r"\d{2}", g.group) for g in groups):
                    raise ValueError(f"Empty or invalid TAU course catalog for {year}")
                for semester in ("a", "b"):
                    target = data / f"courses-{year}{semester}.json"
                    previous = json.loads(target.read_text()) if target.exists() else {}
                    courses = catalog(groups, semester, previous)
                    courses = {course_id: {**course, "prerequisites": get_prerequisites(
                        course_id, course["groups"][0]["group"], str(year - 1), semester,
                    )} for course_id, course in courses.items()}
                    target.write_text(json.dumps(courses, ensure_ascii=False))
                refresh_plans(output_file_template=str(data / "plans-{year}.json"), year=year - 1, strict=True)
                if not any(json.loads((data / f"plans-{year}.json").read_text()).values()):
                    raise ValueError(f"Empty TAU study plans for {year}; retain the previous snapshot")
                refresh_annual([year], data / "annual-groups.json", prefetched={
                    (g.id, g.group): g.exams_by_semester["שנתי"]
                    for g in groups if "שנתי" in g.exams_by_semester
                })
            os.chdir(data)
            collect()
        finally:
            os.chdir(previous_directory)
        completed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        plan_files = {f"plans-{y}.json" for y in years}
        direct_files = {"annual-groups.json", *{f"courses-{y}{s}.json" for y in years for s in ("a", "b")}}
        refreshed_files = direct_files | plan_files | {"courses.json"}
        snapshot = {
            "source": TAU,
            "generatedAt": completed,
            "automaticRefresh": True,
            "schedule": "Weekly, Saturday at 22:23 UTC; scraping stops by 04:00 UTC",
            "lastSuccessfulRefresh": completed,
            "tauAcademicYears": years,
            "retainedCourseFields": ["exam_links"],
            "files": {p.name: {
                **previous_snapshot.get("files", {}).get(p.name, {}),
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "source": "https://tochniot.tau.ac.il/graphql" if p.name in plan_files else TAU if p.name in direct_files else ("derived" if p.name == "courses.json" else previous_snapshot.get("files", {}).get(p.name, {}).get("source", "saved snapshot")),
                "refreshStatus": "refreshed" if p.name in refreshed_files else "retained",
                **({"lastSuccessfulRefresh": completed} if p.name in refreshed_files else {}),
            } for p in sorted(data.glob("*.json"))},
            "unavailablePlans": [name for name in previous_snapshot.get("unavailablePlans", []) if name not in plan_files],
        }
        (staging / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        validate(staging)
        shutil.copytree(data, ROOT / "data", dirs_exist_ok=True)
        shutil.copyfile(staging / "snapshot.json", ROOT / "snapshot.json")
        print(f"Refresh complete: {completed}", flush=True)


if __name__ == "__main__":
    refresh()
