# Malaysia and Japan research log

Audit trail for the international expansion (draft PR #4). Nothing here is published until
`_directory-sync/publication.json` is changed with the owner's approval.

## Files
| File | What it holds |
|---|---|
| `research/records-jp.csv` | Desk-researched Japanese establishments, one row each, evidence kept by source type |
| `research/evidence-jp.jsonl` | Every evidence item behind those rows (URL, short excerpt, source type, date accessed) |
| `research/chain-evidence-my.csv` | Operator and JAKIM statements about Malaysian chains (reported, contradicted, not certified) |
| `research/osm-*.json.gz`, `research/coverage-*.csv` | OpenStreetMap extract (ODbL) and per-area coverage |
| `research/jakim-checks.json` | Outcome of the JAKIM MYeHALAL lookup attempt |
| `state/prepared-my.csv`, `state/prepared-jp.csv` | Every record with its evidence tier, readiness and blocking issues |

## Evidence tiers (kept separate; never merged into one "verified" figure)
1. **Certified** – confirmed on the certifying body's own list or official register.
2. **Certification reported** – claimed by the establishment, its operator (chain-level), a tourism body or the press; not confirmed.
3. **Self-declared** – the establishment's own published declaration, or a tourism-body listing of information the establishment supplied.
4. **Community** – OpenStreetMap report only.
Muslim ownership and "selected halal menu" are recorded alongside the tier, never as certification.
A government Muslim-friendly scheme (e.g. Yamanashi Food Diversity, "no pork / no alcohol in named items") is recorded as such and never as halal certification.

## 2026-10-17
- Sources used: official tourism bodies (GO TOKYO guide 2026-27, Kyoto City Tourism Association, Aichi Prefecture,
  VISIT FUKUOKA, Kobe Tourism Bureau, Visit Kinosaki, Shizuoka Halal Portal, Yamanashi Prefecture, Ibaraki, Visit Miyagi,
  Niseko, Kagoshima CVB, Kurashiki, Okayama City, MLIT Chugoku guide, JNTO), establishments' own sites and press releases,
  operator halal pages (Marrybrown, Texas Chicken, Sushi King, McDonald's Malaysia), JAKIM statements reported in the press.
- Not used: Halal Gourmet Japan, Halal Media Japan directory, Google Maps, Tabelog, TripAdvisor and similar directories.
- JAKIM MYeHALAL search returned a server error for every query, so no Malaysian outlet could be confirmed individually.
- Not reachable without additional site permissions: GO TOKYO guide icons (pork, alcohol, halal meat), Aichi dining-guide PDFs,
  Chiba "Map for Muslims", Kanagawa Muslim-friendly guidebook, OCVB Okinawa Muslim guide, certifier member lists.
- Miri (Sarawak): 471 OSM records; contributor's edits cite local knowledge and street-level imagery (332 changesets, 2024);
  no same-name duplicates within 300 m; 452 carry Miri 980xx postcodes; all edited 2024–2025; 7 are outlets of chains with
  operator JAKIM statements; Sushi Zanmai held back (operator statement: not halal); none confirmed at outlet level.

## 2026-10-18
- GO TOKYO Muslim Travelers' Guide 2026-27: icons read visually for 109 entries (pork, alcohol, halal meat, kitchen,
  utensils, ownership, prayer space). Only icons clearly legible were recorded; nothing inferred from unclear icons.
- Japan: 339 researched records across 30 prefectures (with OSM-only records); 196 meet C1–C5 (111 in Tokyo).
- JAKIM premises register searched through a browser session (the server-side request still fails): 931 register premises
  for McDonald's, Marrybrown, Texas Chicken and Sushi King. Of 326 mapped outlets of these chains, 142 matched one register
  premises at the same postcode (confirmed), 65 matched only by name or shared a premises with another outlet (review,
  not certified) and 119 had no or several candidates (not found). Derived facts only: `jakim-outlets-my.csv`.
- Miri: 5 chain outlets confirmed on the JAKIM register; the 464 community-only records stay unverified and unpublished.
