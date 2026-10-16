"""Read and (on approval only) extend the published directory workbook."""
import shutil
import subprocess
import tempfile
from pathlib import Path

import openpyxl
from openpyxl.formula.translate import Translator

from .normalise import norm_postal

SHEET = "Establishments"
TABLE = "tblEstablishments"
# Columns the workbook computes with live Excel formulas. New rows copy the
# formula from the first data row; everything else is written as a value.
FORMULA_COLUMNS = ("ID", "Postal Prefix", "Demo Disclaimer", "Data Completeness",
                   "Map Ready", "Record Validation")


def read_directory(path):
    """Return the listed establishments as dicts (saved formula results)."""
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


def append_records(src, dst, rows_by_header):
    """Append rows (dicts keyed by workbook header) to the table, then recalc.

    Returns the list of IDs Excel assigned to the new rows.
    """
    wb = openpyxl.load_workbook(src)
    ws = wb[SHEET]
    header = [c.value for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(header)}
    lookup = postal_lookup(wb)
    table = ws.tables[TABLE]
    first, last = table.ref.split(":")
    last_row = int("".join(ch for ch in last if ch.isdigit()))
    last_col = "".join(ch for ch in last if ch.isalpha())

    # Reuse empty trailing table rows before extending the table.
    target = max((r for r in range(2, ws.max_row + 1) if ws.cell(r, col["Name"]).value), default=1) + 1
    new_rows = []
    for rec in rows_by_header:
        r = target
        target += 1
        postal = norm_postal(rec.get("Postal Code"))
        if postal and not rec.get("Area / Prefecture"):
            rec.update({k: v for k, v in lookup.get(postal[:2], {}).items() if v})
        for h, v in rec.items():
            if h in col and h not in FORMULA_COLUMNS and v not in (None, ""):
                ws.cell(r, col[h]).value = v
        for h in FORMULA_COLUMNS:
            if h not in col:
                continue
            letter = openpyxl.utils.get_column_letter(col[h])
            model = ws[f"{letter}2"].value
            if isinstance(model, str) and model.startswith("="):
                ws[f"{letter}{r}"] = Translator(model, origin=f"{letter}2").translate_formula(f"{letter}{r}")
        new_rows.append(r)
    if new_rows and max(new_rows) > last_row:
        table.ref = f"{first}:{last_col}{max(new_rows)}"
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / Path(dst).name
        wb.save(staged)
        recalc(staged, Path(tmp) / "out")
        shutil.copyfile(Path(tmp) / "out" / staged.name, dst)
    check = openpyxl.load_workbook(dst, data_only=True)[SHEET]
    ids = [check.cell(r, col["ID"]).value for r in new_rows]
    if any(not i for i in ids):
        raise RuntimeError("Recalculation did not produce IDs for the new rows; workbook not trusted.")
    return ids


def recalc(path, outdir):
    """Recalculate formulas headlessly so the website reads fresh values."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice is required to recalculate the workbook.")
    subprocess.run(
        [soffice, "--headless", "--calc", "--convert-to", "xlsx:Calc MS Excel 2007 XML",
         "--outdir", str(outdir), str(path)],
        check=True, capture_output=True, timeout=180,
    )
