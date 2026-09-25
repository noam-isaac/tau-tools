"""Offline regression checks: python scripts/test-refresh.py."""

import copy
import os
import runpy
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch, call
from types import SimpleNamespace

from tau_tools.plans import main as scrape_plans

import requests
from bs4 import BeautifulSoup
from tau_tools.courses import GroupInfo, LessonInfo, get_school_courses, parse_exams, parse_result_page
from tau_tools.utilities import request

refresh_module = runpy.run_path(str(Path(__file__).with_name("refresh-data.py")))
catalog = refresh_module["catalog"]
calendar = {"currentSemester": "2027a", "semesters": {
    f"{year}{semester}": {"startDate": f"{year}-01-01", "endDate": f"{year}-06-01"}
    for year in (2026, 2027) for semester in ("a", "b")
}}
exam = {"moed": "א", "date": "01/07/2027", "hour": "09:00", "type": "בחינה"}
annual = GroupInfo("Annual", "12345678", "01", "Faculty", "Teacher", [exam],
                   [LessonInfo("שנתי", "א", "10:00-12:00", "Building", "1", "שיעור")], {"שנתי": [exam]})
spring = GroupInfo("Spring", "87654321", "01", "Faculty", "Teacher", [],
                   [LessonInfo("ב'", "ב", "12:00-14:00", "Building", "2", "שיעור")], {"ב'": []})
previous = {"12345678": {"exam_links": ["https://example.org/exam"], "exams": [exam]},
            "87654321": {"exams": [exam]}, "00000000": {"name": "Removed"}}
before = copy.deepcopy(previous)
autumn = catalog([annual, spring], "a", previous)
assert list(autumn) == ["12345678"]
assert autumn["12345678"]["exams"] == [exam]
assert autumn["12345678"]["exam_links"] == previous["12345678"]["exam_links"]
assert catalog([annual, spring], "b", previous)["87654321"]["exams"] == []
assert previous == before
assert parse_exams(BeautifulSoup('<div class="msgerrs">אין נתונים</div>', "html.parser")) == []
regular = '<table class="tableblds"><tr><th>מועד</th><th>תאריך</th><th>שעה</th><th>סוג מטלה</th></tr><tr><td>א</td><td>01/07/2027</td><td>09:00</td><td>בחינה</td></tr></table>'
assert parse_exams(BeautifulSoup(regular, "html.parser")) == [exam]
take_home = '<table class="tableblds"><tr><th>מועד</th><th>ת.לקיחת מטלה</th><th>שעה</th><th>ת.הגשת מטלה</th><th>שעה</th><th>סוג מטלה</th></tr><tr><td>א</td><td>01/07/2027</td><td>09:00</td><td>03/07/2027</td><td>12:00</td><td>עבודה</td></tr></table>'
assert parse_exams(BeautifulSoup(take_home, "html.parser"))[0]["type"] == "עבודה (הגשה: 03/07/2027 12:00)"
for invalid in ['<div class="msgerrs">אירעה שגיאה</div>', '<html>Unavailable</html>', regular.replace('01/07/2027', '31/02/2027')]:
    try:
        parse_exams(BeautifulSoup(invalid, "html.parser"))
    except ValueError:
        pass
    else:
        raise AssertionError("A source failure must not erase exams")
response = Mock()
response.raise_for_status.side_effect = requests.HTTPError("503")
with patch('requests.Session.request', return_value=response), patch('builtins.open') as write:
    try:
        request('get', 'https://example.org', cache_key='failure-test')
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("HTTP failures must abort refresh")
    write.assert_not_called()

# A source failure must leave our saved inputs intact, without contacting Arazim.
with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "data").mkdir()
    (root / "data/info.json").write_text(json.dumps(calendar))
    for name in ("grades", "bidding", "courses-2026a", "courses-2026b"):
        (root / f"data/{name}.json").write_text("{}")
    (root / "snapshot.json").write_text('{"original": true}')
    response = Mock(text='<select name="lstYear"><option value="2025">2026</option><option value="2026">2027</option></select>')
    refresh = refresh_module["refresh"]
    scrape = Mock(side_effect=ValueError('source failure'))
    with patch.dict(refresh.__globals__, {"ROOT": root, "get_schools": lambda: [('lstDep1', ['01', '02', '03'])], "get_school_courses": scrape}), patch('requests.Session.get', return_value=response):
        try:
            refresh()
        except ValueError as error:
            assert str(error) == 'source failure'
        else:
            raise AssertionError('A failed source must abort publication')
    assert scrape.call_count == 1, 'No later TAU searches after a source failure'
    assert json.loads((root / 'data/info.json').read_text()) == calendar
    assert (root / 'snapshot.json').read_text() == '{"original": true}'

# Duplicate exam lookups in a fresh run reuse the first successful response.
with TemporaryDirectory() as directory:
    previous_directory = Path.cwd()
    try:
        os.chdir(directory)
        with patch.dict(os.environ, {"TAU_TOOLS_FORCE_FETCH": ""}), patch('requests.Session.request', return_value=Mock(text='exam fixture')) as get:
            assert request('get', 'https://example.org/exam', cache_key='exam-01-2027', delay=0) == 'exam fixture'
            assert request('get', 'https://example.org/exam', cache_key='exam-01-2027', delay=0) == 'exam fixture'
            assert get.call_count == 1
    finally:
        os.chdir(previous_directory)

# Pagination must finish before exam lookups, and dir1 must override hidden state.
first = '<a id="next"></a><input type="hidden" name="dir1" value=""><a href="Syllabus_L.aspx?course=1"></a>'
last = '<a href="Syllabus_L.aspx?course=2"></a>'
events = []
def source_request(*args, **kwargs):
    events.append("page")
    if len(events) == 1:
        return first
    assert kwargs["data"]["dir1"] == "1"
    return last
def parse_page(*args):
    events.append("exams")
    return []
with patch('tau_tools.courses.request', side_effect=source_request), patch('tau_tools.courses.parse_result_page', side_effect=parse_page):
    assert get_school_courses(0, ('lstDep6', ['03']), '2025') == []
assert events == ['page', 'page', 'exams', 'exams']
with patch('tau_tools.courses.request', return_value=first):
    try:
        get_school_courses(0, ('lstDep6', ['03']), '2025')
    except ValueError as error:
        assert 'repeated a page' in str(error)
    else:
        raise AssertionError('Repeated pagination must fail instead of looping')

assert parse_result_page(BeautifulSoup('<div class="msgerrs">אין נתונים מתאימים למאפייני החיפוש</div>', 'html.parser'), '2025') == []
for page in ['<html>Unavailable</html>', '<form id="frmgrid"><table dir="rtl"></table></form>']:
    try:
        parse_result_page(BeautifulSoup(page, 'html.parser'), '2025')
    except ValueError:
        pass
    else:
        raise AssertionError('An unknown empty response must not erase courses')
# TAU uses a six-column take-home header even when one sitting omits deadline cells.
mixed = take_home.replace('<tr><td>א</td>', '<tr><td>ב</td>').replace('</table>', '<tr><td>א</td><td>05/02/2026</td><td>09:00</td><td>בחינת בית</td></tr></table>')
assert parse_exams(BeautifulSoup(mixed, 'html.parser'))[-1] == {
    "moed": "א", "date": "05/02/2026", "hour": "09:00", "type": "בחינת בית",
}
print("Refresh regression checks passed")

# The complete publication owns annual data and reuses exams from the catalog pass.
with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'data').mkdir()
    historical = {"source": refresh_module['TAU'], "filter": "ckSem=0", "verifiedAt": "2025-09-01", "groups": {"12345678": ["01"]}}
    (root / 'data/annual-groups.json').write_text(json.dumps({"version": 1, "years": {"2025": historical, "2026": historical}}))
    old_catalog = {"00000000": {"name": "Preserved TAU history", "faculty": "Faculty", "groups": [], "exams": [exam]}}
    old_bytes = json.dumps(old_catalog).encode()
    for semester in ('2025a', '2026a', '2026b'):
        (root / f'data/courses-{semester}.json').write_bytes(old_bytes)
    (root / 'snapshot.json').write_text(json.dumps({"files": {"courses-2025a.json": {"source": refresh_module['TAU']}}}))
    (root / 'data/plans-2026.json').write_text('{}')
    historical_calendar = {**calendar, "semesters": {**calendar['semesters'], "2025a": {}}}
    response = Mock(text='<select name="lstYear"><option value="2025">2026</option><option value="2026">2027</option></select>')
    (root / 'data/info.json').write_text(json.dumps(historical_calendar))
    (root / 'data/grades.json').write_text('{"12345678": {"2026a": {"01": [{"mean": 82}]}}}')
    (root / 'data/bidding.json').write_text('{"12345678": {"2026a": {"01": [{"minimal": 20}]}}}')
    (root / 'data/courses-2027a.json').write_text(json.dumps(previous))
    retained_bytes = {name: (root / 'data' / name).read_bytes() for name in ('info.json', 'grades.json', 'bidding.json')}
    (root / 'snapshot.json').write_text(json.dumps({"files": {
        "courses-2025a.json": {"source": refresh_module['TAU']},
        "grades.json": {"source": "https://arazim-project.com/data/", "lastSuccessfulRefresh": "2026-09-01T00:00:00Z"},
    }}))
    def tau_discovery(url, **kwargs):
        assert url == refresh_module['TAU'], f"Unexpected feed request: {url}"
        return response
    refresh = refresh_module['refresh']
    scrape = Mock(return_value=[annual])
    prerequisites = Mock(side_effect=lambda course, group, year, semester: None if semester == 'a' else {"kind": "all", "courses": ["87654321"]})
    def write_plans(output_file_template, year, strict):
        assert strict and year == 2026
        Path(output_file_template.format(year=year + 1)).write_text(json.dumps({"School": {"Program": {"Required": {"courses": {}, "count": 0}}}}))
    plans = Mock(side_effect=write_plans)
    with patch.dict(refresh.__globals__, {"ROOT": root, "get_schools": lambda: [('lstDep1', ['01'])], "get_school_courses": scrape, "get_prerequisites": prerequisites, "refresh_plans": plans}), patch('requests.Session.get', side_effect=tau_discovery) as discover, patch('tau_tools.annual.collect', return_value={annual.id: [annual.group]}) as classify, patch('urllib.request.urlopen', side_effect=AssertionError('Exam already fetched')):
        refresh()
    scrape.assert_called_once_with(0, ('lstDep1', ['01']), '2026')
    classify.assert_called_once_with(2027)
    assert prerequisites.call_args_list == [call(annual.id, '01', '2026', 'a'), call(annual.id, '01', '2026', 'b')]
    assert plans.call_count == 1
    assert json.loads((root / 'data/courses-2027a.json').read_text())[annual.id]['prerequisites'] is None
    assert json.loads((root / 'data/courses-2027b.json').read_text())[annual.id]['prerequisites']['courses'] == ['87654321']
    discover.assert_called_once_with(refresh_module['TAU'], timeout=60)
    assert json.loads((root / 'data/courses-2027a.json').read_text())[annual.id]['exam_links'] == previous[annual.id]['exam_links']
    assert {name: (root / 'data' / name).read_bytes() for name in retained_bytes} == retained_bytes
    manifest = json.loads((root / 'snapshot.json').read_text())
    assert manifest['files']['grades.json']['lastSuccessfulRefresh'] == '2026-09-01T00:00:00Z'
    assert manifest['files']['grades.json']['source'] == 'https://arazim-project.com/data/'
    assert all(manifest['files'][name]['refreshStatus'] == 'retained' for name in retained_bytes)
    assert manifest['files']['courses-2027a.json']['refreshStatus'] == 'refreshed'
    assert (root / 'data/plans-2026.json').read_text() == '{}'
    assert json.loads((root / 'snapshot.json').read_text())['files']['plans-2027.json']['source'] == 'https://tochniot.tau.ac.il/graphql'
    preserved = {path.name: path.read_bytes() for path in (root / 'data').glob('*.json')}
    snapshot_before = (root / 'snapshot.json').read_bytes()
    for failure in ('get_prerequisites', 'refresh_plans'):
        with patch.dict(refresh.__globals__, {"ROOT": root, "get_schools": lambda: [('lstDep1', ['01'])], "get_school_courses": scrape, "get_prerequisites": prerequisites, "refresh_plans": plans, failure: Mock(side_effect=ValueError('Source unavailable'))}), patch('requests.Session.get', return_value=response):
            try:
                refresh()
            except ValueError as error:
                assert str(error) == 'Source unavailable'
            else:
                raise AssertionError('Failed direct TAU data must block publication')
        assert {path.name: path.read_bytes() for path in (root / 'data').glob('*.json')} == preserved
        assert (root / 'snapshot.json').read_bytes() == snapshot_before
    for semester in ('2025a', '2026a', '2026b'):
        assert (root / f'data/courses-{semester}.json').read_bytes() == old_bytes
    assert json.loads((root / 'snapshot.json').read_text())['tauAcademicYears'] == [2027]
    assert json.loads((root / 'snapshot.json').read_text())['files']['courses-2025a.json']['source'] == refresh_module['TAU']
    feed = json.loads((root / 'data/annual-groups.json').read_text())
    assert feed['years']['2025'] == historical
    assert feed['years']['2026'] == historical
    assert set(feed['years']) == {'2025', '2026', '2027'}
    assert feed['years']['2027']['exams'][annual.id]['groups']['01'] == [exam]
    assert 'annual-groups.json' in json.loads((root / 'snapshot.json').read_text())['files']
print('Combined catalog and annual publication checks passed')

# Missing/new calendar metadata must stop before school or course scraping.
for invalid in ({"semesters": {"2027a": {}}},
                {**calendar, "currentSemester": "2099a"},
                {**calendar, "semesters": {**calendar['semesters'], "2027b": {"startDate": "2027-02-31", "endDate": "2027-07-01"}}}):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'data').mkdir()
        (root / "data/info.json").write_text(json.dumps(invalid))
        (root / "snapshot.json").write_text("{}")
        schools = Mock(side_effect=AssertionError('Must validate dates before scraping schools'))
        with patch.dict(refresh.__globals__, {"ROOT": root, "get_schools": schools}), patch('requests.Session.get', return_value=response):
            try:
                refresh()
            except ValueError as error:
                assert 'calendar dates' in str(error)
            else:
                raise AssertionError('Incomplete calendar accepted')
        schools.assert_not_called()
# No automatic backfill of missing history or supplements from another publisher.
with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'data').mkdir()
    (root / 'data/info.json').write_text(json.dumps(calendar))
    (root / 'snapshot.json').write_text('{}')
    for missing in ('grades.json', 'bidding.json', 'courses-2026a.json', 'courses-2026b.json'):
        with patch.dict(refresh.__globals__, {"ROOT": root, "get_schools": schools}), patch('requests.Session.get', return_value=response):
            try:
                refresh()
            except ValueError as error:
                assert f'Missing saved dataset: {missing}' in str(error)
            else:
                raise AssertionError('Missing saved input accepted')
        schools.assert_not_called()
        (root / 'data' / missing).write_text('{}')
print('Calendar guards passed')

# Reuse the upstream plan scraper, but abort publication instead of silently skipping a failed plan.
with TemporaryDirectory() as directory:
    target = Path(directory) / 'plans-{year}.json'
    school = SimpleNamespace(name='School')
    plan = SimpleNamespace(id='1', name='Program')
    with patch('tau_tools.plans.get_schools', return_value=[school]), patch('tau_tools.plans.get_plans', return_value=[plan]), patch('tau_tools.plans.get_plan', side_effect=ValueError('Plan unavailable')):
        try:
            scrape_plans(str(target), year=2026, strict=True)
        except ValueError as error:
            assert str(error) == 'Plan unavailable'
        else:
            raise AssertionError('Strict plan refresh must propagate source failures')
    assert not list(Path(directory).glob('*.json'))
print('Direct prerequisite and plan checks passed')

# Exercise the actual workflow guard with a mocked clock/process: never start a scraper.
workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/scrape.yml').read_text()
assert "cron: '23 22 * * 6'" in workflow
night_guard = textwrap.dedent(workflow.split("python - <<'PYTHON'\n", 1)[1].split('          PYTHON', 1)[0])
for hour, allowed, seconds in [(21, False, None), (22, True, 21600), (0, True, 14400), (3, True, 3600), (4, False, None)]:
    with patch('datetime.datetime') as clock, patch('subprocess.run') as run:
        clock.now.return_value = datetime(2026, 9, 26, hour, tzinfo=timezone.utc)
        try:
            exec(compile(night_guard, '<workflow overnight guard>', 'exec'), {})
        except SystemExit:
            assert not allowed
        else:
            assert allowed
        if allowed:
            assert run.call_count == 1 and run.call_args.kwargs['timeout'] == seconds
        else:
            run.assert_not_called()
print('Weekly overnight window checks passed')
