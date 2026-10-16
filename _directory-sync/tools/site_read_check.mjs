// Reads the workbook exactly as muslim-friendly-directory.html does (SheetJS,
// first sheet, saved formula values) and fails if the website would break.
// Usage: node site_read_check.mjs path/to/workbook.xlsx
import { readFileSync } from "node:fs";
import * as XLSX from "xlsx";

const path = process.argv[2];
const wb = XLSX.read(readFileSync(path), { type: "buffer", cellDates: true, dateNF: "yyyy-mm-dd" });
if (!wb.SheetNames.length) throw new Error("Workbook has no sheets");
if (wb.SheetNames[0] !== "Establishments") throw new Error(`First sheet is ${wb.SheetNames[0]}, expected Establishments`);
const rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: null, raw: false });
const normKey = (k) => String(k ?? "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const seen = new Set();
const problems = [];
let listings = 0;
for (const raw of rows) {
  const row = {};
  for (const [k, v] of Object.entries(raw)) { const nk = normKey(k); if (nk && !(nk in row)) row[nk] = v; }
  const id = String(row.id ?? "").trim();
  const name = String(row.name ?? "").trim();
  if (name && !id) problems.push(`"${name}" has a name but no ID (formulas not recalculated?)`);
  if (!id || !name) continue;
  if (seen.has(id)) problems.push(`duplicate ID ${id}`);
  seen.add(id);
  listings++;
}
console.log(`Website would show ${listings} listing(s).`);
if (problems.length) {
  console.error("Workbook problems:\n- " + problems.join("\n- "));
  process.exit(1);
}
