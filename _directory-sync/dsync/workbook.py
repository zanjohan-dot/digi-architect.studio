"""Read and (on administrator action only) change the published directory workbook.

This is the only module that touches Excel. A future move to a database
(e.g. Supabase) replaces this module; the matching, checks and reporting
work on plain dicts and do not change.

Every write follows the same safe path:
  1. edit a copy in a temporary folder
  2. recalculate formulas headlessly (LibreOffice) so the website reads fresh values
  3. verify the result: same sheets and headers, table range intact, every
     listing has a unique ID, and rows that were not meant to change are identical
  4. only then atomically replace the live file
If any step fails the live workbook is left exactly as it was.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import openpyxl

from .normalise import norm_postal

SHEET = "Establishments"
TABLE = "tblEstablishments"
# Live formula columns. Templates are written for row {r}; they mirror the
# formulas in the workbook as of Oct 2026 so new rows work even when the
# table has no data rows to copy from.
FORMULA_TEMPLATES = {
    "ID": '=IF(B{r}<>"","est-"&TEXT(ROW()-1,"000"),"")',
    "Postal Prefix": '=IF(C{r}="Singapore",IF(LEN(TEXT(E{r},"000000"))=6,LEFT(TEXT(E{r},"000000"),2),""),"")',
    "Data Completeness": '=IF(OR(A{r}="",B{r}="",C{r}="",D{r}=""),"Missing required fields",'
                         'IF(NOT(AND(ISNUMBER(M{r}),ISNUMBER(N{r}))),"Missing coordinates","Complete"))',
    "Map Ready": '=IF(AND(ISNUMBER(M{r}),ISNUMBER(N{r})),"Ready","Coordinates required")',
    "Demo Disclaimer": '=IF(OR(AT{r}=TRUE,AT{r}="TRUE"),"This sample listing is provided solely to demonstrate '
                       'the directory interface. It does not represent a live declaration, verification, '
                       'endorsement or participating establishment.","")',
    "Record Validation": '=IF(OR(AT{r}=TRUE,AT{r}="TRUE"),"Demo record",IF(A{r}="","Missing ID",'
                         'IF(B{r}="","Missing name",IF(NOT(AND(ISNUMBER(M{r}),ISNUMBER(N{r}))),'
                         '"Coordinates required","Ready for publication"))))',
}
FORMULA_COLUMNS = ("ID", "Postal Prefix", "Demo Disclaimer", "Data Completeness",
                   "Map Ready", "Record Validation")


class WorkbookError(RuntimeError):
    pass


# ---------------------------------------------------------------- reading --

def read_directory(path):
    """Return (header, listings) using saved formula results, as the website does."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    out = []
    for n, values in enumerate(rows, start=2):
        rec = dict(zip(header, values))
        if not rec.get("Name"):
            continue
        rec["_row"] = n
        out.append(rec)
    wb.close()
    return header, out


def postal_lookup(wb):
    if "Singapore_Postal_Lookup" not in wb.sheetnames:
        return {}
    ws = wb["Singapore_Postal_Lookup"]
    rows = ws.iter_rows(values_only=True)
    header = [str(h or "") for h in next(rows)]
    idx = {h: i for i, h in enumerate(header)}
    table = {}
    for r in rows:
        if r and r[idx["Postal Prefix"]]:
            table[str(r[idx["Postal Prefix"]]).zfill(2)] = {
                "Area / Prefecture": r[idx.get("Area", 3)],
                "Postal Sector": r[idx.get("Postal Sector", 1)],
                "Postal District": r[idx.get("Postal District", 2)],
            }
    return table


# ---------------------------------------------------------------- helpers --

def _header(ws):
    return {c.value: c.column for c in ws[1] if c.value}


def _formula_for(ws, col_letter, name, r):
    """Formula for a formula column at row r.

    Uses the fixed template; checks it still matches the workbook's own
    row-2 formula when one exists, so an edited workbook is not silently
    overwritten with stale logic.
    """
    from openpyxl.formula.translate import Translator
    tpl = FORMULA_TEMPLATES[name]
    model = ws[f"{col_letter}2"].value
    if isinstance(model, str) and model.startswith("=") and model != tpl.format(r=2):
        # Workbook formula was changed by hand: follow the workbook.
        return Translator(model, origin=f"{col_letter}2").translate_formula(f"{col_letter}{r}")
    return tpl.format(r=r)


def _set_formulas(ws, col, r):
    for name in FORMULA_COLUMNS:
        if name in col:
            letter = openpyxl.utils.get_column_letter(col[name])
            f = _formula_for(ws, letter, name, r)
            if f:
                ws[f"{letter}{r}"] = f


def _fill_location(rec, lookup):
    postal = norm_postal(rec.get("Postal Code"))
    if postal:
        rec["Postal Code"] = postal
        if not rec.get("Area / Prefecture"):
            rec.update({k: v for k, v in lookup.get(postal[:2], {}).items() if v})


def _snapshot(path):
    """{ID: tuple(values)} of saved values, plus header and sheet names."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[SHEET]
    header = [c.value for c in ws[1]]
    rows = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[header.index("Name")]:
            rows[r[header.index("ID")] or f"<no id {len(rows)}>"] = r
    return {"sheets": wb.sheetnames, "header": header, "rows": rows,
            "table": ws.tables[TABLE].ref if TABLE in ws.tables else None}


def recalc(path, outdir):
    """Recalculate formulas headlessly so the website reads fresh values."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise WorkbookError("LibreOffice is required to recalculate the workbook.")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="lo-profile-"))
    try:
        subprocess.run(
            [soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--calc",
             "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(outdir), str(path)],
            check=True, capture_output=True, timeout=240,
        )
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = outdir / Path(path).name
    if not out.exists():
        raise WorkbookError("LibreOffice did not produce a recalculated workbook.")
    return out


def _safe_commit(wb, live_path, verify):
    """Stage, recalc, verify, then atomically replace the live workbook."""
    live_path = Path(live_path)
    before = _snapshot(live_path)
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / live_path.name
        wb.save(staged)
        result = recalc(staged, Path(tmp) / "out")
        after = _snapshot(result)
        if after["sheets"] != before["sheets"]:
            raise WorkbookError("Sheet list changed during write; live workbook untouched.")
        if after["header"] != before["header"]:
            raise WorkbookError("Header row changed during write; live workbook untouched.")
        if not after["table"]:
            raise WorkbookError("Table definition lost during write; live workbook untouched.")
        ids = list(after["rows"])
        if any(i.startswith("<no id") for i in ids):
            raise WorkbookError("A listing has no ID after recalculation; live workbook untouched.")
        verify(before, after)
        tmp_live = live_path.with_name(live_path.name + ".writing")
        shutil.copyfile(result, tmp_live)
        os.replace(tmp_live, live_path)
    return after


# ---------------------------------------------------------------- writing --

def append_records(path, records):
    """Append new listings (dicts keyed by header). Returns the IDs assigned."""
    wb = openpyxl.load_workbook(path)
    ws = wb[SHEET]
    col = _header(ws)
    lookup = postal_lookup(wb)
    table = ws.tables[TABLE]
    first, last = table.ref.split(":")
    last_col = re.sub(r"\d", "", last)
    last_row = int(re.sub(r"\D", "", last))
    target = max((r for r in range(2, ws.max_row + 1) if ws.cell(r, col["Name"]).value), default=1) + 1
    new_rows = []
    for rec in records:
        rec = dict(rec)
        _fill_location(rec, lookup)
        r = target
        target += 1
        for h, v in rec.items():
            if h in col and h not in FORMULA_COLUMNS and v not in (None, ""):
                ws.cell(r, col[h]).value = v
        _set_formulas(ws, col, r)
        new_rows.append(r)
    if new_rows and max(new_rows) > last_row:
        table.ref = f"{first}:{last_col}{max(new_rows)}"
    added = []

    def verify(before, after):
        for i, row in before["rows"].items():
            if after["rows"].get(i) != row:
                raise WorkbookError(f"Existing listing {i} changed while adding rows; live workbook untouched.")
        added[:] = [i for i in after["rows"] if i not in before["rows"]]
        if len(added) != len(records):
            raise WorkbookError(f"Expected {len(records)} new listings, found {len(added)}; live workbook untouched.")

    _safe_commit(wb, path, verify)
    return list(added)


def update_records(path, changes):
    """Update existing listings. changes = {listing_id: {header: value}}."""
    wb = openpyxl.load_workbook(path)
    ws = wb[SHEET]
    col = _header(ws)
    data = openpyxl.load_workbook(path, data_only=True)[SHEET]
    row_of = {data.cell(r, col["ID"]).value: r for r in range(2, data.max_row + 1)
              if data.cell(r, col["Name"]).value}
    missing = [i for i in changes if i not in row_of]
    if missing:
        raise WorkbookError(f"Listing(s) not found: {', '.join(missing)}")
    for lid, fields in changes.items():
        for h, v in fields.items():
            if h in FORMULA_COLUMNS or h not in col:
                continue
            ws.cell(row_of[lid], col[h]).value = None if v == "" else v

    def verify(before, after):
        for i, row in before["rows"].items():
            if i not in after["rows"]:
                raise WorkbookError(f"Listing {i} disappeared during update; live workbook untouched.")
            if i not in changes and after["rows"][i] != row:
                raise WorkbookError(f"Listing {i} changed but was not meant to; live workbook untouched.")

    _safe_commit(wb, path, verify)


def remove_records(path, listing_ids):
    """Remove listings, keeping a blank formula row so the table stays valid."""
    wb = openpyxl.load_workbook(path)
    ws = wb[SHEET]
    col = _header(ws)
    data = openpyxl.load_workbook(path, data_only=True)[SHEET]
    keep = []
    for r in range(2, data.max_row + 1):
        if not data.cell(r, col["Name"]).value:
            continue
        lid = data.cell(r, col["ID"]).value
        if lid not in listing_ids:
            keep.append([ws.cell(r, c).value for c in range(1, ws.max_column + 1)])
    ncols = ws.max_column
    table = ws.tables[TABLE]
    first, last = table.ref.split(":")
    last_col = re.sub(r"\d", "", last)
    models = {c: ws.cell(2, c).value for c in range(1, ncols + 1)
              if isinstance(ws.cell(2, c).value, str) and str(ws.cell(2, c).value).startswith("=")}
    for r in range(2, ws.max_row + 1):
        for c in range(1, ncols + 1):
            ws.cell(r, c).value = None
    for c, f in models.items():  # keep row 2's formulas as the model for every row
        ws.cell(2, c).value = f
    for offset, values in enumerate(keep):
        r = 2 + offset
        for c, v in enumerate(values, start=1):
            if isinstance(v, str) and v.startswith("="):
                continue
            ws.cell(r, c).value = v
        _set_formulas(ws, col, r)
    end = max(2, 1 + len(keep))
    if not keep:
        _set_formulas(ws, col, 2)  # blank template row: formulas return "" until a name is entered
    table.ref = f"{first}:{last_col}{end}"
    removed = set(listing_ids)

    def verify(before, after):
        for i in removed:
            if i in before["rows"] and any(row[after["header"].index("Name")] == before["rows"][i][after["header"].index("Name")]
                                           and row[after["header"].index("Postal Code")] == before["rows"][i][after["header"].index("Postal Code")]
                                           for row in after["rows"].values()):
                raise WorkbookError(f"Listing {i} still present after removal; live workbook untouched.")
        if len(after["rows"]) != len(before["rows"]) - len(removed & set(before["rows"])):
            raise WorkbookError("Unexpected number of listings after removal; live workbook untouched.")

    _safe_commit(wb, path, verify)


def bump_data_version(html_path, version):
    """Update DATA_VERSION in the directory page so browsers fetch the new workbook."""
    html_path = Path(html_path)
    if not html_path.exists():
        return False
    text = html_path.read_text(encoding="utf-8")
    new, n = re.subn(r"var DATA_VERSION = '\d{8}[a-z]?';", f"var DATA_VERSION = '{version}';", text, count=1)
    if n:
        html_path.write_text(new, encoding="utf-8")
    return bool(n)
