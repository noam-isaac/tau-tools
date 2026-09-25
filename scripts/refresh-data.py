"""Refresh public feeds and scrape the newest TAU academic year.

Only the workflow publishes changes, after this command and the static build
succeed. HTTP/parse failures therefore leave the deployed snapshot untouched.
"""

import hashlib
import json
import os
import re
import runpy
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from bs4 import BeautifulSoup
from tau_tools.courses import get_school_courses, get_schools
from tau_tools.collect import main as collect
from tau_tools.annual import refresh as refresh_annual
from tau_tools.plans import main as refresh_plans
from tau_tools.prerequisites import get_prerequisites
from tau_tools.utilities import new_session
from tau_tools.validation import validate_calendar

ROOT = Path(__file__).resolve().parents[1]
TAU = "https://www.ims.tau.ac.il/Tal/KR/Search_P.aspx"
download = runpy.run_path(str(ROOT / "scripts/import-published-data.py"))["download"]
build = runpy.run_path(str(ROOT / "scripts/build-static.py"))["build"]


def catalog(groups, semester, previous):
    labels = {"a": "א'", "b": "ב'"}
    label = labels[semester]
    relevant = [g for g in groups if any(l.semester in (label, "שנתי") for l in g.lessons)]

    def record(course_id, values):
        entries = list(values)
        exams = [e for g in entries for key in (label, "שנתי") for e in g.exams_by_semester.get(key, [])]
        return {
            **previous.get(course_id, {}),
            "name": entries[0].name,
            "faculty": entries[0].faculty,
            "exams": list({json.dumps(e, sort_keys=True): e for e in exams}.values()),
            "groups": [{
                "group": g.group,
                "lecturer": g.lecturer,
                "lessons": [{k: v for k, v in vars(l).items() if k != "semester"}
                            for l in g.lessons if l.semester in (label, "שנתי")],
            } for g in entries],
        }

    return {course_id: record(course_id, values)
            for course_id, values in groupby(sorted(relevant, key=lambda g: g.id), key=lambda g: g.id)}


def refresh():
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with new_session() as session:
        response = session.get(TAU, timeout=60)
    response.raise_for_status()
    options = BeautifulSoup(response.text, "html.parser").select('select[name="lstYear"] option')
    years = sorted({int(o["value"]) + 1 for o in options if re.fullmatch(r"\d{4}", o.get("value", ""))})[-1:]
    if not years:
        raise ValueError("Cannot discover the newest TAU academic year")
    _, info_bytes = download("info.json")
    info = json.loads(info_bytes)
    semesters = info["semesters"]
    if not isinstance(semesters, dict) or not semesters or any(not re.fullmatch(r"\d{4}[ab]", s) for s in semesters):
        raise ValueError("Invalid public semester index")
    previous_snapshot = json.loads((ROOT / "snapshot.json").read_text()) if (ROOT / "snapshot.json").exists() else {}
    previous_info = json.loads((ROOT / "data/info.json").read_text()) if (ROOT / "data/info.json").exists() else {}
    info = {**info, "semesters": {
        **previous_info.get("semesters", {}),
        **{semester: {**previous_info.get("semesters", {}).get(semester, {}), **dates} for semester, dates in semesters.items()},
    }}
    # Do not advertise or scrape a new semester until its source calendar is complete.
    validate_calendar(info, [f"{year}{s}" for year in years for s in ("a", "b")])
    names = ["grades.json", "bidding.json",
             *[f"courses-{s}.json" for s in semesters
               if s[:4] in {str(year) for year in years} or not (ROOT / "data" / f"courses-{s}.json").exists()],
             *[f"plans-{y}.json" for y in sorted({s[:4] for s in semesters})
               if int(y) not in years and not (ROOT / "data" / f"plans-{y}.json").exists()]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        downloads = [("info.json", info_bytes), *pool.map(download, names)]
    with TemporaryDirectory() as directory:
        staging = Path(directory)
        data = staging / "data"
        shutil.copytree(ROOT / "data", data)
        for name, content in downloads:
            if content is not None:
                (data / name).write_bytes(content)
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
                refresh_annual([year], data / "annual-groups.json", feed=True, prefetched={
                    (g.id, g.group): g.exams_by_semester["שנתי"]
                    for g in groups if "שנתי" in g.exams_by_semester
                })
            (data / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
            os.chdir(data)
            collect()
        finally:
            os.chdir(previous_directory)
        completed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        plan_files = {f"plans-{y}.json" for y in years}
        direct_files = {"annual-groups.json", *{f"courses-{y}{s}.json" for y in years for s in ("a", "b")}}
        snapshot = {
            "source": "https://arazim-project.com/data/",
            "downloadedAt": started,
            "automaticRefresh": True,
            "schedule": "Weekly, Saturday at 22:23 UTC; scraping stops by 04:00 UTC",
            "lastSuccessfulRefresh": completed,
            "tauAcademicYears": years,
            "retainedCourseFields": ["exam_links"],
            "files": {p.name: {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "source": "https://tochniot.tau.ac.il/graphql" if p.name in plan_files else TAU if p.name in direct_files else ("derived" if p.name in ("courses.json", "info.json") else previous_snapshot.get("files", {}).get(p.name, {}).get("source", "https://arazim-project.com/data/")),
            } for p in sorted(data.glob("*.json"))},
            "unavailablePlans": [name for name, content in downloads if content is None],
        }
        (staging / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        build(staging)
        shutil.copytree(data, ROOT / "data", dirs_exist_ok=True)
        shutil.copyfile(staging / "snapshot.json", ROOT / "snapshot.json")
        print(f"Refresh complete: {completed}", flush=True)


if __name__ == "__main__":
    refresh()
