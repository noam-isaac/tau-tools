"""Run with python3 scripts/test-static.py; no network or dependencies."""

import json
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

build = runpy.run_path(str(Path(__file__).with_name("build-static.py")))["build"]
with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "data").mkdir()
    for name, value in {"info": {"semesters": {"2027a": {}}}, "courses": {}, "courses-2027a": {}}.items():
        (root / "data" / f"{name}.json").write_text(json.dumps(value))
    (root / "snapshot.json").write_text(json.dumps({"downloadedAt": "<test>"}))
    (root / "data/annual-groups.json").write_text(json.dumps({"version": 1, "years": {"2027": {
        "source": "https://www.ims.tau.ac.il/Tal/KR/Search_P.aspx", "filter": "ckSem=0",
        "verifiedAt": "2026-09-18", "groups": {"12345678": ["01"]},
    }}}))
    build(root)
    assert (root / "dist/data/info.json").read_bytes() == (root / "data/info.json").read_bytes()
    assert "&lt;test&gt;" in (root / "dist/index.html").read_text()
    assert (root / ".vercel/output/static/data/info.json").read_bytes() == (root / "data/info.json").read_bytes()
    config = json.loads((root / ".vercel/output/config.json").read_text())
    assert config["version"] == 3
    assert config["routes"][0]["headers"]["Cache-Control"] == "public, max-age=0, must-revalidate"
    (root / "data/courses-2027a.json").unlink()
    try:
        build(root)
    except ValueError as error:
        assert "Missing indexed dataset" in str(error)
    else:
        raise AssertionError("Missing indexed datasets must fail the build")
    (root / "data/session.json").write_text("{}")
    try:
        build(root)
    except ValueError as error:
        assert "Unexpected public dataset" in str(error)
    else:
        raise AssertionError("Unexpected JSON must not be published")
print("Static deployment checks passed")
