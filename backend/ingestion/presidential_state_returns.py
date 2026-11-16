"""Pinned FEC state summary extraction. Excel support is preparation-only.

Three source buckets retain the two named major nominees and the publication's
all-other residual. They are neither person identities nor county allocations.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from ingestion.medsl import STATE_NAMES

RULESET = "fec-presidential-state-summary-v1"
BUCKETS = {
    2000: ("GEORGE W. BUSH", "AL GORE", "OTHER"),
    2004: ("GEORGE W. BUSH", "JOHN KERRY", "OTHER"),
    2008: ("BARACK OBAMA", "JOHN MCCAIN", "OTHER"),
    2012: ("BARACK OBAMA", "MITT ROMNEY", "OTHER"),
    2016: ("DONALD TRUMP", "HILLARY CLINTON", "OTHER"),
    2020: ("JOE BIDEN", "DONALD TRUMP", "OTHER"),
    2024: ("KAMALA HARRIS", "DONALD TRUMP", "OTHER"),
}


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def scope(year: int) -> str:
    if year not in BUCKETS:
        raise ValueError("Unsupported presidential year")
    return f"president:general:{year}:state:TOTAL"


def integer(value: object) -> int:
    try:
        number = Decimal(str(value).replace(",", ""))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError("Expected nonnegative integral votes")
        return int(number)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid vote value: {value!r}") from exc


def workbook(path: Path) -> dict[str, list[tuple[int, dict[str, object]]]]:
    """Read cells without a DataFrame dependency or evaluating formulas.

    XLS uses the repository's optional research dependency xlrd. XLSX reads
    stored values with the standard library, including cached formula results.
    Missing numeric caches fail validation rather than becoming zero.
    """
    if path.suffix == ".xls":
        import xlrd
        book = xlrd.open_workbook(path)
        return {s.name: [(n + 1, {column_name(i): v for i, v in enumerate(s.row_values(n))})
                         for n in range(s.nrows)] for s in book.sheets()}
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    relns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in node.findall(".//m:t", ns))
                       for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", ns)]
        targets = {r.get("Id"): r.get("Target") for r in
                   ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        result = {}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).findall("m:sheets/m:sheet", ns):
            target = targets[sheet.get(relns)]
            name = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            rows = []
            for row in ET.fromstring(archive.read(name)).findall("m:sheetData/m:row", ns):
                cells = {}
                for cell in row.findall("m:c", ns):
                    value = cell.find("m:v", ns)
                    value = value.text if value is not None else ""
                    if cell.get("t") == "s":
                        value = strings[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//m:t", ns))
                    cells[re.sub(r"\d", "", cell.get("r"))] = value
                rows.append((int(row.get("r")), cells))
            result[sheet.get("name")] = rows
        return result


def column_name(index: int) -> str:
    name = ""
    while index >= 0:
        name = chr(65 + index % 26) + name
        index = index // 26 - 1
    return name


def extract_summary(path: Path, spec: dict) -> dict:
    """Validate exact headers, 51 states, each state sum and national totals."""
    year = spec["year"]
    rows = workbook(path)[spec["sheet"]]
    cells = dict(rows)
    for address, expected in spec["headers"].items():
        column, row = re.fullmatch(r"([A-Z]+)(\d+)", address).groups()
        if cells[int(row)].get(column) != expected:
            raise ValueError(f"FEC header changed: {address}")
    states = []
    for n, row in rows:
        state = spec.get("state_labels", {}).get(row.get("A"), row.get("A"))
        if state not in STATE_NAMES:
            continue
        values = [integer(row.get(c, "")) for c in spec["columns"]]
        if year == 2024:
            # FEC prints all candidate columns, followed by TOTAL VOTES. Blanks
            # mean no reported votes in that candidate column, not missing states.
            component_sum = sum(integer(row[c]) for c in spec["candidate_columns"] if row.get(c) not in ("", None))
            major_a, major_b, total = values
            if component_sum != total:
                raise ValueError(f"FEC candidate sum differs: {state}")
            values = [major_a, major_b, total - major_a - major_b, total]
        if sum(values[:3]) != values[3]:
            raise ValueError(f"FEC state buckets do not reconcile: {state}")
        states.append(dict(state_code=state, votes=dict(zip(BUCKETS[year], values[:3])),
                           total_votes=values[3], source_locator=f"Workbook {spec['sheet']!r}; row {n}; columns {','.join(spec['columns'])}"))
    if len(states) != 51 or {s["state_code"] for s in states} != set(STATE_NAMES):
        raise ValueError("Expected exactly 51 distinct states/DC")
    totals = [sum(s["votes"][bucket] for s in states) for bucket in BUCKETS[year]]
    if totals != spec["national_buckets"] or sum(totals) != spec["national_votes"]:
        raise ValueError("FEC national totals do not reconcile")
    return dict(format=RULESET, year=year, source=spec, states=sorted(states, key=lambda s: s["state_code"]))


def verify_package(package: dict) -> None:
    year = package["year"]
    if package["format"] != RULESET or year == 2008:
        raise ValueError("Use the existing reviewed 2008 publication workflow")
    scope(year)
    states = package["states"]
    if len(states) != 51 or {s["state_code"] for s in states} != set(STATE_NAMES):
        raise ValueError("Incomplete or duplicate FEC states")
    for state in states:
        if set(state["votes"]) != set(BUCKETS[year]) or not state["source_locator"].strip():
            raise ValueError("Unexpected FEC bucket or missing extraction locator")
        values = list(state["votes"].values())
        if any(type(v) is not int or v < 0 for v in values) or sum(values) != state["total_votes"]:
            raise ValueError("Invalid state vote partition")
    spec = package["source"]
    if spec["year"] != year or sum(s["total_votes"] for s in states) != spec["national_votes"]:
        raise ValueError("Invalid FEC election scope/national total")
    if [sum(s["votes"][b] for s in states) for b in BUCKETS[year]] != spec["national_buckets"]:
        raise ValueError("Invalid national candidate totals")
