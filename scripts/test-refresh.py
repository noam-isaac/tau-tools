"""Offline regression checks: python scripts/test-refresh.py."""

import copy
import os
import runpy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

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

download_response = Mock(status_code=200, content=b'{}')
download_response.json.return_value = {}
with patch('requests.Session.get', side_effect=[requests.ConnectionError('interrupted body'), download_response]) as get, patch('time.sleep'):
    assert refresh_module['download']('bidding.json') == ('bidding.json', b'{}')
    assert get.call_count == 2

# A failure after downloading replacement files must leave the published inputs intact.
with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "data").mkdir()
    (root / "data/info.json").write_text('{"original": true}')
    (root / "snapshot.json").write_text('{"original": true}')
    response = Mock(text='<select name="lstYear"><option value="2025">2026</option><option value="2026">2027</option></select>')
    download = lambda name: (name, json.dumps(calendar if name == 'info.json' else {}).encode())
    refresh = refresh_module["refresh"]
    scrape = Mock(side_effect=ValueError('source failure'))
    with patch.dict(refresh.__globals__, {"ROOT": root, "download": download, "get_schools": lambda: [('lstDep1', ['01', '02', '03'])], "get_school_courses": scrape}), patch('requests.Session.get', return_value=response):
        try:
            refresh()
        except ValueError as error:
            assert str(error) == 'source failure'
        else:
            raise AssertionError('A failed source must abort publication')
    assert scrape.call_count == 1, 'No later TAU searches after a source failure'
    assert (root / 'data/info.json').read_text() == '{"original": true}'
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
    historical_calendar = {**calendar, "semesters": {**calendar['semesters'], "2025a": {}}}
    response = Mock(text='<select name="lstYear"><option value="2025">2026</option><option value="2026">2027</option></select>')
    download = Mock(side_effect=lambda name: (name, json.dumps(historical_calendar if name == 'info.json' else {}).encode()))
    refresh = refresh_module['refresh']
    scrape = Mock(return_value=[annual])
    with patch.dict(refresh.__globals__, {"ROOT": root, "download": download, "get_schools": lambda: [('lstDep1', ['01'])], "get_school_courses": scrape}), patch('requests.Session.get', return_value=response), patch('tau_tools.annual.collect', return_value={annual.id: [annual.group]}) as classify, patch('urllib.request.urlopen', side_effect=AssertionError('Exam already fetched')):
        refresh()
    scrape.assert_called_once_with(0, ('lstDep1', ['01']), '2026')
    classify.assert_called_once_with(2027)
    for semester in ('2025a', '2026a', '2026b'):
        assert (root / f'data/courses-{semester}.json').read_bytes() == old_bytes
        assert f'courses-{semester}.json' not in [call.args[0] for call in download.call_args_list]
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
        schools = Mock(side_effect=AssertionError('Must validate dates before scraping schools'))
        with patch.dict(refresh.__globals__, {"ROOT": root, "download": lambda name: (name, json.dumps(invalid).encode()), "get_schools": schools}), patch('requests.Session.get', return_value=response):
            try:
                refresh()
            except ValueError as error:
                assert 'calendar dates' in str(error)
            else:
                raise AssertionError('Incomplete calendar accepted')
        schools.assert_not_called()
print('Calendar guards passed')
