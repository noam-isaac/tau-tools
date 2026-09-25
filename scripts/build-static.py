"""Validate generated public datasets and build a static Vercel site."""

import json
import re
import shutil
from pathlib import Path

from tau_tools.validation import validate_calendar, validate_dataset


def validate(root):
    data = root / "data"
    files = sorted(data.glob("*.json"))
    for path in files:
        if not re.fullmatch(r"(?:info|courses|grades|bidding|annual-groups|courses-\d{4}[ab]|plans-\d{4})\.json", path.name):
            raise ValueError(f"Unexpected public dataset: {path.name}")
        validate_dataset(path.stem, json.loads(path.read_text()))
    info = json.loads((data / "info.json").read_text())
    semesters = info["semesters"]
    for name in ["courses.json", "annual-groups.json", "grades.json", "bidding.json", *[f"courses-{semester}.json" for semester in semesters]]:
        if not (data / name).is_file():
            raise ValueError(f"Missing indexed dataset: {name}")
    snapshot = json.loads((root / "snapshot.json").read_text())
    validate_calendar(info, [f"{year}{semester}" for year in snapshot.get("tauAcademicYears", []) for semester in ("a", "b")])
    return files


def build(root):
    files = validate(root)
    prebuilt = root / ".vercel" / "output"
    if prebuilt.exists():
        shutil.rmtree(prebuilt)
    output = prebuilt / "static"
    (output / "data").mkdir(parents=True)
    for path in files:
        shutil.copyfile(path, output / "data" / path.name)
    shutil.copyfile(root / "snapshot.json", output / "snapshot.json")
    (prebuilt / "config.json").write_text(json.dumps({
        "version": 3,
        "routes": [{"src": "/data/(.*)", "headers": {
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=0, must-revalidate",
        }, "continue": True}, {"handle": "filesystem"}],
    }) + "\n")
    print(f"Built {len(files)} JSON datasets in {prebuilt}")


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
