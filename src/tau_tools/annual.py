"""Annual-only classification and per-group exams for the shared static feed.

Runs inside TAU Tools' weekly publication. Explicit CLI usage requires years and
an output path; no dependency on Dib It source files or application configuration.
"""
import argparse
import datetime
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from bs4 import BeautifulSoup
from tau_tools.courses import parse_exams as parse_exam_table

BASE = "https://www.ims.tau.ac.il/Tal/KR/"


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.schools, self.hidden, self.groups = {}, {}, set()
        self.select = self.option = None
        self.next = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.select = attrs.get("name")
        if tag == "option" and self.select and self.select.startswith("lstDep"):
            self.option = attrs.get("value")
        if tag == "input":
            if attrs.get("type") == "hidden" and attrs.get("name"):
                self.hidden[attrs["name"]] = attrs.get("value", "")
            self.next |= attrs.get("id") == "next"
        if tag == "a":
            match = re.search(r"/Tal/Syllabus/Syllabus_L.aspx\?course=(\d{8})(\d{2})&year=(\d{4})", attrs.get("href", ""))
            if match:
                self.groups.add(match.groups())

    def handle_data(self, text):
        if self.option:
            self.schools.setdefault(self.select, []).append((self.option, text.strip()))
            self.option = None

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None
        if tag == "option":
            self.option = None


def fetch(opener, path, payload=None):
    data = urllib.parse.urlencode(payload).encode() if payload is not None else None
    time.sleep(1)
    with opener.open(BASE + path, data=data, timeout=60) as response:
        return response.read().decode("utf-8-sig")


def collect(year):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    schools = Page(fetch(opener, "Search_P.aspx")).schools
    if len(schools) != 14:
        raise ValueError("TAU school selector changed; review parser before refreshing")
    groups = {}
    pages = 0
    for field, options in schools.items():
        if options[0][1].startswith("כל "):
            options = options[:1]
        for option, _ in options:
            payload = {"lstYear1": str(year - 1), "ckSem": "0", field: option}
            seen = set()
            while True:
                html = fetch(opener, "Search_L.aspx", payload)
                page = Page(html)
                if not page.groups and "אין נתונים מתאימים למאפייני החיפוש" not in html:
                    raise ValueError(f"Unrecognized annual search response: {year} {field} {option}")
                if page.groups and frozenset(page.groups) in seen:
                    raise ValueError("Repeated pagination page")
                seen.add(frozenset(page.groups))
                for course, group, source_year in page.groups:
                    if int(source_year) != year - 1:
                        raise ValueError("Unexpected academic year in response")
                    groups.setdefault(course, set()).add(group)
                pages += 1
                if not page.next:
                    break
                payload = {**page.hidden, "dir1": "1"}
                time.sleep(0.2)
    if not groups:
        raise ValueError("Empty annual catalog")
    print(f"{year}: {len(groups)} annual courses, {sum(map(len, groups.values()))} groups, {pages} pages", flush=True)
    return {course: sorted(values) for course, values in sorted(groups.items())}


def parse_exams(html):
    return parse_exam_table(BeautifulSoup(html, "html.parser"))


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def collect_exams(year, groups, previous=None, prefetched=None):
    def read_course(pair):
        course, course_groups = pair
        try:
            exams = {}
            for group in course_groups:
                if prefetched is not None and (course, group) in prefetched:
                    exams[group] = prefetched[(course, group)]
                    continue
                time.sleep(1)
                query = urllib.parse.urlencode({"kurs": course, "kv": group, "sem": f"{year - 1}0"})
                with urllib.request.urlopen(BASE + "Bhina_L.aspx?" + query, timeout=60) as response:
                    exams[group] = parse_exams(response.read().decode("utf-8-sig"))
            return course, {"verifiedAt": timestamp(), "groups": exams}, None
        except (OSError, ValueError) as error:
            print(f"Exam refresh failed for {year}/{course}: {error}", file=sys.stderr, flush=True)
            return course, (previous or {}).get(course), timestamp()

    # A course is replaced only after all of its groups succeed, including explicit empty results.
    results = list(map(read_course, groups.items()))
    return {
        "exams": {course: snapshot for course, snapshot, _ in results if snapshot is not None},
        "examFailures": {course: failed for course, _, failed in results if failed is not None},
    }


def refresh(years, target, feed=False, prefetched=None):
    previous = json.loads(target.read_text()) if target.exists() else None
    if feed and previous is not None and (previous.get("version") != 1 or not isinstance(previous.get("years"), dict)):
        raise ValueError("Unsupported annual feed; preserve it for review")
    data = (previous["years"] if feed else previous) if previous is not None else {}
    classification_failures = {}
    for year in years:
        before = data.get(str(year), {})
        try:
            classification = {"source": BASE + "Search_P.aspx", "filter": "ckSem=0",
                              "verifiedAt": datetime.date.today().isoformat(), "groups": collect(year)}
        except (OSError, ValueError) as error:
            print(f"Classification refresh failed for {year}: {error}", file=sys.stderr, flush=True)
            classification = {**before, "classificationFailedAt": timestamp()}
            if not before:
                classification_failures[str(year)] = classification["classificationFailedAt"]
                continue
        exam_data = collect_exams(year, classification["groups"], before.get("exams"), prefetched)
        data[str(year)] = {**classification, **exam_data}
        print(f"{year}: {len(exam_data['exams'])} course snapshots, {len(exam_data['examFailures'])} failed exam refreshes", flush=True)
    if not data:
        raise ValueError("No verified annual data is available; preserve the previous file")
    # Publish successes and retained snapshots together; failure metadata keeps their age visible.
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"version": 1, "years": data, "classificationFailures": classification_failures} if feed else data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(target)


def self_test():
    import io
    import tempfile
    from unittest.mock import patch

    html = '<table class="tableblds"><tr><th>מועד</th><th>תאריך</th><th>שעה</th><th>סוג מטלה</th></tr><tr><td>א</td><td>&nbsp;27/06/2027&nbsp;</td><td>09:00</td><td>בחינה סופית</td></tr></table>'
    assert parse_exams(html) == [{"moed": "א", "date": "27/06/2027", "hour": "09:00", "type": "בחינה סופית"}]
    home = '<table class="tableblds"><tr><th>מועד</th><th>ת.לקיחת מטלה</th><th>שעה</th><th>ת.הגשת מטלה</th><th>שעה</th><th>סוג מטלה</th></tr><tr><td>א</td><td>19/07/2026</td><td>09:00</td><td>21/07/2026</td><td>13:00</td><td>בחינת בית</td></tr></table>'
    assert parse_exams(home) == [{"moed": "א", "date": "19/07/2026", "hour": "09:00", "type": "בחינת בית (הגשה: 21/07/2026 13:00)"}]
    assert parse_exams('<div class="msgerrs rounddiv">אין נתונים</div>') == []
    urls = []
    def exam_response(url, timeout):
        urls.append(url)
        return io.BytesIO(html.encode())
    with patch("urllib.request.urlopen", side_effect=exam_response):
        result = collect_exams(2027, {"21721600": ["01", "02"]})
        assert result["exams"]["21721600"]["groups"] == {group: parse_exams(html) for group in ["01", "02"]}
        assert not result["examFailures"]
    assert sorted(urls) == [BASE + f"Bhina_L.aspx?kurs=21721600&kv={group}&sem=20260" for group in ["01", "02"]]
    for invalid in ['<html>Service unavailable</html>', '<div class="msgerrs">אירעה שגיאה</div>', html.replace("27/06/2027", "31/02/2027"), html.replace("מועד", "changed")]:
        try:
            parse_exams(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid exam source accepted")
    page = Page("""<select name="lstDep1"><option value=""></option>
      <option value="08">כל הפקולטה לאמנויות</option></select>
      <a href="/Tal/Syllabus/Syllabus_L.aspx?course=1031310301&amp;year=2025">סילבוס</a>
      <input type="hidden" name="__VIEWSTATE" value="next-page-token">
      <input id="next" type="submit">""")
    assert page.schools == {"lstDep1": [("08", "כל הפקולטה לאמנויות")]}
    assert page.groups == {("10313103", "01", "2025")}
    assert page.next and page.hidden == {"__VIEWSTATE": "next-page-token"}
    with patch("urllib.request.urlopen", side_effect=AssertionError("Duplicate exam request")):
        reused = collect_exams(2027, {"21721600": ["01", "02"]}, prefetched={
            ("21721600", "01"): parse_exams(html), ("21721600", "02"): [],
        })
    assert reused["exams"]["21721600"]["groups"]["02"] == []
    assert not reused["examFailures"]
    good = {"verifiedAt": "2026-09-18T00:00:00Z", "groups": {"01": parse_exams(html)}}
    def partial_response(url, timeout):
        if "kurs=11111111" in url:
            raise OSError("Source unavailable")
        return io.BytesIO('<div class="msgerrs">אין נתונים</div>'.encode())
    with patch("urllib.request.urlopen", side_effect=partial_response):
        result = collect_exams(2027, {"11111111": ["01"], "22222222": ["01"]}, {"11111111": good, "22222222": good})
    assert result["exams"]["11111111"] == good
    assert result["exams"]["22222222"]["groups"] == {"01": []}, "Cancellation must replace old dates"
    assert set(result["examFailures"]) == {"11111111"}
    def incomplete_course(url, timeout):
        if "kv=02" in url:
            raise OSError("Second group unavailable")
        return io.BytesIO(html.replace("27/06/2027", "28/06/2027").encode())
    with patch("urllib.request.urlopen", side_effect=incomplete_course):
        partial = collect_exams(2027, {"11111111": ["01", "02"]}, {"11111111": good})
    assert partial["exams"]["11111111"] == good, "Never mix successful and failed groups of one course"
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "annualGroups.json"
        before = {"source": BASE + "Search_P.aspx", "filter": "ckSem=0", "verifiedAt": "2026-09-18",
                  "groups": {"11111111": ["01"]}, "exams": {"11111111": good}}
        target.write_text(json.dumps({"2026": before}))
        with patch(__name__ + ".collect", side_effect=OSError("Classification unavailable")), patch(__name__ + ".collect_exams", return_value=result):
            refresh([2026], target)
        updated = json.loads(target.read_text())["2026"]
        assert updated["groups"] == before["groups"] and updated["verifiedAt"] == before["verifiedAt"]
        assert updated["classificationFailedAt"]
        assert updated["exams"]["22222222"]["groups"] == {"01": []}, "Exam updates survive classification failure"
        with patch(__name__ + ".collect", return_value={"11111111": ["01"], "22222222": ["01"]}), patch(__name__ + ".collect_exams", return_value=result):
            refresh([2026, 2028], target)
        updated = json.loads(target.read_text())
        assert set(updated) == {"2026", "2028"}
        assert updated["2026"]["groups"] == {"11111111": ["01"], "22222222": ["01"]}
        assert "classificationFailedAt" not in updated["2026"]
        assert updated["2026"]["exams"]["11111111"] == good, "Classification updates cannot re-date exams"
        previous_bytes = target.read_bytes()
        with patch(__name__ + ".collect", side_effect=RuntimeError("Unexpected bug")):
            try:
                refresh([2026], target)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Unexpected failure ignored")
        assert target.read_bytes() == previous_bytes
        feed = Path(directory) / "annual-groups.json"
        with patch(__name__ + ".collect", return_value={"11111111": ["01"]}), patch(__name__ + ".collect_exams", return_value=result):
            refresh([2028], feed, True)
        assert json.loads(feed.read_text())["version"] == 1
        with patch(__name__ + ".collect", side_effect=[OSError("New year unavailable"), {"11111111": ["01"]}]), patch(__name__ + ".collect_exams", return_value=result):
            refresh([2029, 2028], feed, True)
        partial_feed = json.loads(feed.read_text())
        assert "2029" in partial_feed["classificationFailures"]
        assert "2028" in partial_feed["years"] and "2029" not in partial_feed["years"]
    print("PASS annual source: parsing, reused exam results, independent refreshes, per-course failure, cancellation, retained timestamps and atomic publication")



if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("years", nargs="+", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    years = args.years
    print(f"Verifying annual groups for offered years: {years}", flush=True)
    refresh(years, args.output, feed=True)
