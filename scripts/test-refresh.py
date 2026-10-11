"""Offline regression checks: python scripts/test-refresh.py."""

import copy
import os
import runpy
import json
import subprocess
import textwrap
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import ANY, Mock, patch, call
from types import SimpleNamespace

from tau_tools.plans import get_plan, get_plans, main as scrape_plans, request_graphql

import requests
from bs4 import BeautifulSoup
from tau_tools.courses import GroupInfo, LessonInfo, get_school_courses, parse_exams, parse_result_page, main as scrape_courses
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
# The existing standalone CLI keeps its own semester/exam policy and course order.
with TemporaryDirectory() as directory:
    groups = [spring, annual, replace(spring, group="02", exams=[exam, exam]), replace(spring, group="03"), replace(spring, id="00000000")]
    with patch('tau_tools.courses.get_schools', return_value=[('lstDep1', ['01'])]), patch('tau_tools.courses.get_school_courses', return_value=groups), patch('tau_tools.courses.get_prerequisites', return_value=None):
        scrape_courses(str(Path(directory) / 'courses-{year}{semester}.json'), year=2026)
    standalone = json.loads((Path(directory) / 'courses-2027b.json').read_text())
    assert list(standalone) == [spring.id, '00000000'] and standalone[spring.id]['exams'] == [exam, exam]
    assert [g['group'] for g in standalone[spring.id]['groups']] == ['01', '02', '03']
    assert json.loads((Path(directory) / 'courses-2027a.json').read_text()) == {}
    assert list(catalog(groups, 'b', {})) == ['00000000', annual.id, spring.id]
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
    assert 1 <= scrape.call_count <= 4, 'A failure may finish only the initial bounded batch'
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
    prerequisites = Mock(side_effect=lambda course, group, year, semester, s=None: None if semester == 'a' else {"kind": "all", "courses": ["87654321"]})
    def write_plans(output_file_template, year, strict, exclude_doctoral):
        assert strict and exclude_doctoral and year == 2026
        Path(output_file_template.format(year=year + 1)).write_text(json.dumps({"School": {"Program": {"Required": {"courses": {}, "count": 0}}}}))
    plans = Mock(side_effect=write_plans)
    with patch.dict(refresh.__globals__, {"ROOT": root, "get_schools": lambda: [('lstDep1', ['01'])], "get_school_courses": scrape, "get_prerequisites": prerequisites, "refresh_plans": plans}), patch('requests.Session.get', side_effect=tau_discovery) as discover, patch('tau_tools.annual.collect', return_value={annual.id: [annual.group]}) as classify, patch('urllib.request.urlopen', side_effect=AssertionError('Exam already fetched')):
        refresh()
    assert not (root / ".vercel/output").exists(), "Refresh validates inputs; only the workflow builds output"
    scrape.assert_called_once_with(0, ('lstDep1', ['01']), '2026')
    classify.assert_called_once_with(2027)
    assert prerequisites.call_args_list == [call(annual.id, '01', '2026', 'a', s=ANY), call(annual.id, '01', '2026', 'b', s=ANY)]
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

# TAU's inventory mixes source years. Never fetch older entries as this year's
# curricula, or even resolve their missing IDs before applying the year filter.
school = SimpleNamespace(id='1000', name='School', faculties=[])
programs = [
    {'teur': 'Historical', 'tcid': '8053', 'currentSafa': '1', 'shana': '2024', 'egedid': ''},
    {'teur': 'Current', 'tcid': '9001', 'currentSafa': '1', 'shana': '2026', 'egedid': ''},
    {'teur': 'Historical without ID', 'tcid': None, 'currentSafa': '1', 'shana': '2024', 'egedid': 'old'},
]
with patch('tau_tools.plans.request_graphql', return_value={'getPrograms': {'results': programs}}) as query:
    assert [plan.id for plan in get_plans(school, year=2026)] == ['9001']
    query.assert_called_once()
programs[1]['toar'] = 'ראשון'
programs.extend([
    {'teur': 'Doctoral', 'tcid': None, 'currentSafa': '1', 'shana': '2026', 'egedid': 'phd', 'toar': 'שלישי'},
    {'teur': 'Masters', 'tcid': '9002', 'currentSafa': '1', 'shana': '2026', 'egedid': '', 'toar': 'שני'},
])
with patch('tau_tools.plans.request_graphql', return_value={'getPrograms': {'results': programs}}) as query:
    assert [plan.id for plan in get_plans(school, year=2026, exclude_doctoral=True)] == ['9001', '9002']
    query.assert_called_once()

# POST retries apply only to explicit read-only GraphQL queries, preserving the
# global GET policy and never making mutation calls retryable.
from tau_tools.utilities import new_session
with new_session() as session:
    assert set(session.get_adapter('https://example.org').max_retries.allowed_methods) == {'GET'}
for query, methods in [('query results { results }', {'GET', 'POST'}), ('mutation update { update }', {'GET'})]:
    with patch('tau_tools.plans.request', return_value='{"data": {}}') as transport:
        request_graphql({'query': query})
        session = transport.call_args.args[2]
        assert set(session.get_adapter('https://tochniot.tau.ac.il/graphql').max_retries.allowed_methods) == methods
        assert session.get_adapter('https://tochniot.tau.ac.il/graphql').max_retries.total == 3

# A doctoral program can exist without a course curriculum. Accept only TAU's
# explicit zero-row response for plan details, preserving strict source failures.
plan = SimpleNamespace(id='4586', language='1')
zero_rows = {'data': {'results': {'body': {'Tau': {'status': '001', 'numrows': '0', 'errmsgeng': 'No data'}}}}}
with patch('tau_tools.plans.request', return_value=json.dumps(zero_rows)):
    assert get_plan(plan, year=2026) == {}
    try:
        request_graphql({})
    except Exception as error:
        assert str(error) == 'No data'
    else:
        raise AssertionError('An empty inventory must still fail')
for change in ({'status': '500'}, {'numrows': '1'}, {'errmsgeng': 'Service unavailable'}):
    failure = copy.deepcopy(zero_rows)
    failure['data']['results']['body']['Tau'].update(change)
    with patch('tau_tools.plans.request', return_value=json.dumps(failure)):
        try:
            get_plan(plan, year=2026)
        except Exception:
            pass
        else:
            raise AssertionError('A source failure must not become an empty plan')

# Reuse the upstream plan scraper, but abort publication instead of silently skipping a failed plan.
with TemporaryDirectory() as directory:
    target = Path(directory) / 'plans-{year}.json'
    school = SimpleNamespace(name='School')
    plan = SimpleNamespace(id='1', name='Program')
    with patch('tau_tools.plans.get_schools', return_value=[school]), patch('tau_tools.plans.get_plans', return_value=[plan]) as plans, patch('tau_tools.plans.get_plan', side_effect=ValueError('Plan unavailable')):
        try:
            scrape_plans(str(target), year=2026, strict=True)
        except ValueError as error:
            assert str(error) == 'Plan unavailable'
        else:
            raise AssertionError('Strict plan refresh must propagate source failures')
        plans.assert_called_once_with(school, year=2026, exclude_doctoral=False)
    assert not list(Path(directory).glob('*.json'))
print('Direct prerequisite and plan checks passed')

# Exercise the actual workflow guard with a mocked clock/process: never start a scraper.
workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/scrape.yml').read_text()
assert "cron: '23 22 * * 6'" in workflow
night_guard = textwrap.dedent(workflow.split("python - <<'PYTHON'\n", 1)[1].split('          PYTHON', 1)[0])
for event, override, hour, allowed, seconds in [
    *[('schedule', 'false', hour, allowed, seconds) for hour, allowed, seconds in
      [(21, False, None), (22, True, 21600), (0, True, 14400), (3, True, 3600), (4, False, None)]],
    ('schedule', 'true', 11, False, None),
    ('workflow_dispatch', 'false', 11, False, None),
    ('workflow_dispatch', '', 11, False, None),
    ('workflow_dispatch', 'true', 11, True, 10800),
    ('workflow_dispatch', 'true', 3, True, 3600),
]:
    with patch.dict(os.environ, {'GITHUB_EVENT_NAME': event, 'ALLOW_DAYTIME_REFRESH': override}), patch('datetime.datetime') as clock, patch('subprocess.run') as run:
        clock.now.return_value = datetime(2026, 9, 26, hour, tzinfo=timezone.utc)
        try:
            exec(compile(night_guard, '<workflow overnight guard>', 'exec'), {})
        except SystemExit:
            assert not allowed
        else:
            assert allowed
        if allowed:
            assert run.call_count == 1 and run.call_args.kwargs['timeout'] == seconds
            assert run.call_args.kwargs['check'] is True
        else:
            run.assert_not_called()
for failure in [subprocess.TimeoutExpired(['scraper'], 10800), subprocess.CalledProcessError(1, ['scraper'])]:
    with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'ALLOW_DAYTIME_REFRESH': 'true'}), patch('datetime.datetime') as clock, patch('subprocess.run', side_effect=failure):
        clock.now.return_value = datetime(2026, 10, 11, 11, tzinfo=timezone.utc)
        try:
            exec(compile(night_guard, '<workflow daytime guard>', 'exec'), {})
        except type(failure):
            pass
        else:
            raise AssertionError('Manual refresh failures must still block publication')
print('Weekly overnight window and explicit manual daytime checks passed')

# Parallel output stays ordered and cannot exceed four active lookups.
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, get_ident
parallel_map = refresh_module['parallel_map']
barrier, guard = Barrier(4), Lock()
counts = {'active': 0, 'peak': 0}
def concurrent_lookup(number):
    with guard:
        counts['active'] += 1
        counts['peak'] = max(counts['peak'], counts['active'])
    try:
        if number < 4:
            barrier.wait(timeout=3)
        return number * 2
    finally:
        with guard:
            counts['active'] -= 1
assert parallel_map(concurrent_lookup, range(12), 'Concurrency fixture') == list(range(0, 24, 2))
assert counts['peak'] == 4 and counts['active'] == 0

# An error stops queued work and HTTP calls in already-running school workers.
from tau_tools.utilities import request_cancelled
barrier = Barrier(4)
def failing_lookup(number):
    assert number < 4, 'No next batch after a failure'
    barrier.wait(timeout=3)
    if number == 0:
        raise ValueError('First source failure')
    assert request_cancelled.get().wait(timeout=3)
    request('get', 'https://example.org/cancelled', delay=0)
with patch('requests.Session.request', side_effect=AssertionError('Cancelled worker sent HTTP')) as http:
    try:
        parallel_map(failing_lookup, range(12), 'Cancellation fixture')
    except ValueError as error:
        assert str(error) == 'First source failure'
    else:
        raise AssertionError('A source failure must propagate')
    http.assert_not_called()
assert request_cancelled.get() is None, 'Worker cancellation must not leak'

# Simultaneous duplicate misses share one request; different keys stay parallel.
with TemporaryDirectory() as directory:
    previous_directory = Path.cwd()
    barrier = Barrier(2)
    def response_fixture(method, url, **kwargs):
        barrier.wait(timeout=3)
        return Mock(text='Complete cached response: ' + url)
    try:
        os.chdir(directory)
        with patch.dict(os.environ, {'TAU_TOOLS_FORCE_FETCH': ''}), patch('requests.Session.request', side_effect=response_fixture) as http, patch('os.replace', wraps=os.replace) as replace_cache:
            with ThreadPoolExecutor(max_workers=4) as pool:
                result = list(pool.map(lambda key: request('get', 'https://example.org/' + key, cache_category='parallel', cache_key=key, delay=0), ['a', 'a', 'b', 'b']))
            assert http.call_count == 2 and replace_cache.call_count == 2
            assert result == ['Complete cached response: https://example.org/' + key for key in ['a', 'a', 'b', 'b']]
            assert sorted(p.name for p in Path('cache-parallel').iterdir()) == ['a.txt', 'b.txt']
    finally:
        os.chdir(previous_directory)

# Prerequisite workers reuse isolated sessions and close them on completion.
barrier = Barrier(4)
sessions, owners = [], {}
def session_fixture():
    session = Mock()
    sessions.append(session)
    return session
def prerequisite_fixture(course, group, year, semester, s=None):
    with guard:
        owners.setdefault(get_ident(), set()).add(id(s))
    if int(course) < 4:
        barrier.wait(timeout=3)
    return {'kind': 'all', 'courses': [course]}
fixture_courses = {f'{number:08d}': {'groups': [{'group': '01'}]} for number in range(12)}
with patch.dict(refresh_module['prerequisites'].__globals__, {'new_session': session_fixture, 'get_prerequisites': prerequisite_fixture}):
    result = refresh_module['prerequisites'](fixture_courses, 2027, 'a')
assert list(result) == list(fixture_courses)
assert all(result[key]['prerequisites']['courses'] == [key] for key in result)
assert all('prerequisites' not in course for course in fixture_courses.values())
assert len(sessions) == 4 and all(len(values) == 1 for values in owners.values())
assert all(session.close.call_count == 1 for session in sessions)
print('Parallel refresh, cancellation, cache and session checks passed')
