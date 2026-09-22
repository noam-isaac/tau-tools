"""Offline check that corrupt or unexpected downloads cannot become build inputs."""

import hashlib
import json
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

restore = runpy.run_path(str(Path(__file__).with_name("restore-snapshot.py")))["restore"]
content = b'{"semesters":{"2027a":{}}}'
metadata = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

for name, body, succeeds in [("info.json", content, True), ("info.json", b'{}', False), ("../escape.json", content, False)]:
    manifest = json.dumps({"files": {"info.json": metadata, name: metadata}}).encode()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.dict(restore.__globals__, {"download": lambda path: manifest if path == '/snapshot.json' else body}):
            try:
                restore(root)
            except ValueError:
                assert not succeeds
                assert not (root / "data").exists()
                assert not (root / "snapshot.json").exists()
            else:
                assert succeeds
                assert (root / "data/info.json").read_bytes() == content
                assert (root / "snapshot.json").read_bytes() == manifest
                try:
                    restore(root)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Restore must not overwrite existing inputs")

print("Snapshot restore checks passed")
