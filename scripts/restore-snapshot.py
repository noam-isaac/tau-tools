"""Restore generated inputs from Vercel, never from Git or TAU."""

import hashlib
import json
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://tau-tools.vercel.app"


def download(path):
    with urlopen(SOURCE + path, timeout=60) as response:
        return response.read()


def restore(root=ROOT):
    if (root / "data").exists() or (root / "snapshot.json").exists():
        raise ValueError("Restore requires a checkout without generated data")
    manifest = download("/snapshot.json")
    files = json.loads(manifest)["files"]
    if not isinstance(files, dict) or "info.json" not in files:
        raise ValueError("Invalid snapshot manifest")
    with TemporaryDirectory(dir=root) as directory:
        staging = Path(directory)
        for name, metadata in files.items():
            if not re.fullmatch(r"(?:info|courses|grades|bidding|courses-\d{4}[ab]|plans-\d{4})\.json", name):
                raise ValueError(f"Unexpected dataset: {name}")
            content = download("/data/" + name)
            if len(content) != metadata["bytes"] or hashlib.sha256(content).hexdigest() != metadata["sha256"]:
                raise ValueError(f"Snapshot changed or file is damaged: {name}")
            if not isinstance(json.loads(content), dict):
                raise ValueError(f"Expected a JSON object: {name}")
            (staging / name).write_bytes(content)
        shutil.move(str(staging), root / "data")
    (root / "snapshot.json").write_bytes(manifest)
    print(f"Restored {len(files)} verified datasets from Vercel; no TAU requests")


if __name__ == "__main__":
    restore()
