"""Import the initial public Arazim snapshot into an empty data directory."""

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from tau_tools.utilities import new_session

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://arazim-project.com/data/"


def download(name):
    for attempt in range(3):
        try:
            with new_session() as session:
                response = session.get(SOURCE + name, timeout=60)
            break
        except requests.RequestException as error:
            if attempt == 2:
                raise RuntimeError(f"Cannot download {SOURCE + name}") from error
            time.sleep(2 ** attempt)
    if response.status_code == 404 and name.startswith("plans-"):
        return name, None
    response.raise_for_status()
    if not isinstance(response.json(), dict):
        raise ValueError(f"Expected JSON object: {name}")
    return name, response.content


if __name__ == "__main__":
    data = ROOT / "data"
    if data.exists():
        raise SystemExit("data/ already exists; refusing to overwrite generated datasets")
    _, info_bytes = download("info.json")
    semesters = json.loads(info_bytes)["semesters"]
    if not isinstance(semesters, dict) or not semesters or not all(re.fullmatch(r"\d{4}[ab]", s) for s in semesters):
        raise SystemExit("Invalid public semester index")
    names = ["courses.json", "grades.json", "bidding.json",
             *[f"courses-{semester}.json" for semester in semesters],
             *[f"plans-{year}.json" for year in sorted({s[:4] for s in semesters})]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        downloads = [("info.json", info_bytes), *pool.map(download, names)]
    data.mkdir()
    for name, content in downloads:
        if content is not None:
            (data / name).write_bytes(content)
    (ROOT / "snapshot.json").write_text(json.dumps({
        "source": SOURCE,
        "downloadedAt": datetime.now(timezone.utc).isoformat(),
        "automaticRefresh": False,
        "files": {name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                  for name, content in downloads if content is not None},
        "unavailablePlans": [name for name, content in downloads if content is None],
    }, indent=2) + "\n")
    print(f"Imported {len(list(data.glob('*.json')))} datasets")
