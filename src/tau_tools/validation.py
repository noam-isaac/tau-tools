"""Publication contracts matching Dib It's schemas.ts and annualRegistry.ts.

Unknown fields and missing optional fields remain compatible with historical feeds.
"""

import re
from datetime import datetime, timedelta

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

STRING = {"type": "string"}
NUMBER = {"type": "number"}


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


def array(items):
    return {"type": "array", "items": items}


def record(values, pattern=None):
    return {"type": "object", "additionalProperties": values,
            **({"propertyNames": {"pattern": pattern}} if pattern else {})}


EXAM = obj({key: STRING for key in ("moed", "date", "hour", "type")})
PREREQUISITES = obj({"kind": {"enum": ["any", "all"]},
    "courses": array({"anyOf": [STRING, {"$ref": "#/$defs/prerequisites"}]}),
    "parallel": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/prerequisites"}]}})
COURSE = obj({"name": STRING, "faculty": STRING, "exams": array(EXAM),
    "groups": array(obj({"group": STRING, "lecturer": {"type": ["string", "null"]},
        "lessons": array(obj({key: STRING for key in ("day", "time", "building", "room", "type")}))})),
    "exam_links": array(STRING), "prerequisites": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/prerequisites"}]}})
INFO = obj({"currentSemester": STRING,
    "semesters": record(obj({"startDate": STRING, "endDate": STRING}), r"^\d{4}[ab]$")}, ["semesters"])
BID = {"anyOf": [{"type": "number", "minimum": 0}, {"const": ""}]}
STAMP = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z$"}
ANNUAL_YEAR = obj({"source": {"const": "https://www.ims.tau.ac.il/Tal/KR/Search_P.aspx"},
    "filter": {"const": "ckSem=0"}, "verifiedAt": {"type": "string", "format": "date"},
    "groups": {**record({**array({"type": "string", "pattern": r"^\d{2}$"}), "minItems": 1}, r"^\d{8}$"), "minProperties": 1},
    "exams": record(obj({"verifiedAt": STAMP, "groups": record(array(EXAM), r"^\d{2}$")}, ["verifiedAt", "groups"]), r"^\d{8}$"),
    "examFailures": record(STAMP, r"^\d{8}$"), "classificationFailedAt": STAMP},
    ["source", "filter", "verifiedAt", "groups"])
SCHEMAS = {
    "info": INFO,
    "courses": record(obj({"name": STRING, "faculty": STRING, "semesters": array(STRING), "lecturers": array(STRING)})),
    "semester": {**record(COURSE), "$defs": {"prerequisites": PREREQUISITES}},
    "plans": record(record(record(obj({"courses": record(obj({"id": STRING, "weight": {"type": ["string", "number"]}})), "count": NUMBER}, ["courses", "count"])))),
    "bidding": record(record(record(array(obj({"faculty": STRING, "maximal": BID, "minimal": BID,
        **{key: NUMBER for key in ("wanted", "received", "run_available", "total_available")}}))))),
    "grades": record(record(record(array(obj({"mean": {"type": ["number", "null"]}}))))),
    "annual-groups": obj({"version": {"const": 1}, "years": {**record(ANNUAL_YEAR, r"^\d{4}$"), "minProperties": 1},
        "classificationFailures": record(STAMP, r"^\d{4}$")}, ["version", "years"]),
}
VALIDATORS = {name: Draft202012Validator(schema, format_checker=FormatChecker()) for name, schema in SCHEMAS.items()}


def validate_dataset(name, value):
    kind = "semester" if re.fullmatch(r"courses-\d{4}[ab]", name) else "plans" if re.fullmatch(r"plans-\d{4}", name) else name
    try:
        VALIDATORS[kind].validate(value)
        if kind == "annual-groups":
            # datetime also rejects impossible dates in failure/snapshot timestamps.
            entries = value["years"].values()
            stamps = [*value.get("classificationFailures", {}).values(),
                *[stamp for entry in entries for stamp in entry.get("examFailures", {}).values()],
                *[entry["classificationFailedAt"] for entry in entries if "classificationFailedAt" in entry],
                *[exam["verifiedAt"] for entry in entries for exam in entry.get("exams", {}).values()]]
            for stamp in stamps:
                datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValidationError, ValueError) as error:
        location = ".".join(map(str, error.absolute_path)) if isinstance(error, ValidationError) else "timestamp"
        raise ValueError(f"Invalid {name}.json at {location}: {error.message if isinstance(error, ValidationError) else error}") from error


def validate_calendar(info, required_semesters=()):
    validate_dataset("info", info)
    semesters = info["semesters"]
    if not semesters:
        raise ValueError("Invalid semester index")
    def parse(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.strptime(value, "%B %d, %Y %H:%M:%S")
    for semester in {*required_semesters, *([info["currentSemester"]] if "currentSemester" in info else [])}:
        try:
            dates = semesters[semester]
            duration = parse(dates["endDate"]) - parse(dates["startDate"])
            if not timedelta(0) < duration <= timedelta(days=366):
                raise ValueError("Invalid date range")
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError(f"Missing or invalid calendar dates for {semester}") from error
