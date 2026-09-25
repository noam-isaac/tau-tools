"""Run with python3 scripts/test-static.py; no network."""

import json
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

from tau_tools.validation import VALIDATORS

for validator in VALIDATORS.values():
    validator.check_schema(validator.schema)

build = runpy.run_path(str(Path(__file__).with_name("build-static.py")))["build"]
with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "data").mkdir()
    for name, value in {"info": {"semesters": {"2027a": {}}}, "courses": {}, "courses-2027a": {}, "grades": {}, "bidding": {}}.items():
        (root / "data" / f"{name}.json").write_text(json.dumps(value))
    (root / "snapshot.json").write_text(json.dumps({"lastSuccessfulRefresh": "<test>"}))
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
    # Rejected records must leave the previously built output untouched.
    output_before = (root / 'dist/data/courses-2027a.json').read_bytes()
    annual = json.loads((root / 'data/annual-groups.json').read_text())
    malformed = {
        'courses-2027a': {'12345678': {'name': 12}},
        'courses': {'12345678': {'semesters': [2027]}},
        'grades': {'12345678': {'2027a': {'01': [{'mean': 'bad'}]}}},
        'bidding': {'12345678': {'2027a': {'01': [{'minimal': -1}]}}},
        'plans-2027': {'school': {'plan': {'category': {'count': 'bad', 'courses': {}}}}},
        'annual-groups': {**annual, 'years': {'2027': {**annual['years']['2027'], 'exams': {
            '12345678': {'verifiedAt': '2026-09-18T00:00:00Z', 'groups': {'01': [{'date': 123}]}}
        }}}},
    }
    for name, value in malformed.items():
        path = root / 'data' / f'{name}.json'
        previous = path.read_bytes() if path.exists() else None
        path.write_text(json.dumps(value))
        try:
            build(root)
        except ValueError as error:
            assert f'Invalid {name}.json' in str(error)
        else:
            raise AssertionError(f'Malformed {name} must fail publication')
        assert (root / 'dist/data/courses-2027a.json').read_bytes() == output_before
        if previous is None:
            path.unlink()
        else:
            path.write_bytes(previous)
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
