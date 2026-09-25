"""Validate generated public datasets and build a static Vercel site."""

import html
import json
import re
import shutil
from pathlib import Path

from tau_tools.validation import validate_calendar, validate_dataset


def build(root):
    data = root / "data"
    files = sorted(data.glob("*.json"))
    for path in files:
        if not re.fullmatch(r"(?:info|courses|grades|bidding|annual-groups|courses-\d{4}[ab]|plans-\d{4})\.json", path.name):
            raise ValueError(f"Unexpected public dataset: {path.name}")
        validate_dataset(path.stem, json.loads(path.read_text()))
    info = json.loads((data / "info.json").read_text())
    semesters = info["semesters"]
    if not semesters or not all(re.fullmatch(r"\d{4}[ab]", semester) for semester in semesters):
        raise ValueError("Invalid semester index")
    for name in ["courses.json", "annual-groups.json", "grades.json", "bidding.json", *[f"courses-{semester}.json" for semester in semesters]]:
        if not (data / name).is_file():
            raise ValueError(f"Missing indexed dataset: {name}")
    snapshot = json.loads((root / "snapshot.json").read_text())
    validate_calendar(info, [f"{year}{semester}" for year in snapshot.get("tauAcademicYears", []) for semester in ("a", "b")])
    refresh_status = ("Last successful refresh: " + html.escape(snapshot["lastSuccessfulRefresh"])) if snapshot.get("lastSuccessfulRefresh") else "The first automatic refresh has not completed; the initial Arazim snapshot is still served."
    output = root / "dist"
    if output.exists():
        shutil.rmtree(output)
    (output / "data").mkdir(parents=True)
    for path in files:
        shutil.copyfile(path, output / "data" / path.name)
    shutil.copyfile(root / "snapshot.json", output / "snapshot.json")
    links = "\n".join(f'<li><a href="/data/{path.name}">{path.name}</a></li>' for path in files)
    (output / "index.html").write_text(f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TAU Tools datasets</title>
<style>body{{font:18px/1.6 system-ui;max-width:50rem;margin:3rem auto;padding:0 1rem}}a{{color:#164bb5}}</style>
<main><h1>TAU Tools datasets</h1>
<p>Public JSON datasets hosted by <a href="https://github.com/noam-isaac/tau-tools">the TAU Tools fork</a>.</p>
<p>Configured weekly refresh: Saturday 22:23 UTC, stopping by 04:00 UTC. {refresh_status}</p>
<p>The weekly job fetches course schedules, exams, prerequisites and study plans for the newest academic year directly from TAU.
Missing historical data, calendar metadata, grades, bidding and exam links use <a href="https://arazim-project.com">Arazim Project</a>'s published feeds.
Feed download time: {html.escape(snapshot["downloadedAt"])}.</p>
<p>Failed refreshes retain the last successful snapshot.
<a href="https://github.com/noam-isaac/tau-tools/actions/workflows/scrape.yml">Refresh history</a></p>
<p><a href="/snapshot.json">Snapshot provenance</a> · {len(files)} datasets</p>
<ul>{links}</ul></main></html>''')
    prebuilt = root / ".vercel" / "output"
    if prebuilt.exists():
        shutil.rmtree(prebuilt)
    shutil.copytree(output, prebuilt / "static")
    (prebuilt / "config.json").write_text(json.dumps({
        "version": 3,
        "routes": [{"src": "/data/(.*)", "headers": {
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=0, must-revalidate",
        }, "continue": True}, {"handle": "filesystem"}],
    }) + "\n")
    print(f"Built {len(files)} JSON datasets in {output} and {prebuilt}")


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
