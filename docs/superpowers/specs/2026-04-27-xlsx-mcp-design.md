# LM Studio Excel/CSV MCP — Design Spec

**Datum:** 2026-04-27
**Status:** Draft, awaiting implementation
**Kontekst:** brainstorming session, korisnik = raja_rasta

## 1. Pregled

`lm-xlsx` je read-only MCP server koji daje LM Studio LLM-u alate za inspekciju i pretraživanje velikih Excel (`.xlsx`, `.xls`) i CSV datoteka unutar `LM_MCP_ROOT` sandboxa.

**Glavni use case:** usporedba dvije liste artikala gdje su nazivi semantički slabo definirani (varijacije pisanja, drugačiji red riječi, kratice). LLM dobiva nepotpunu listu novih artikala i treba ih spojiti s postojećim katalogom u tablici. Pretraga radi "kako bi čovjek tražio" — fuzzy, iz opisa, traži najbolji match.

**Tipična tablica:** ~10k redaka, jedan glavni sheet, ~1.5M tokena ako se učita cijela. Zato je ciljano čitanje (paginacija + pretraga) nužno — sirovo otvaranje cijele datoteke u kontekst nije izvedivo.

## 2. Arhitektura

- Zaseban MCP server u `xlsx_server.py` pored postojećeg [server.py](../../../server.py)
- Koristi `FastMCP` (isti paket kao `lm-fs`)
- Dijeli sandbox preko `LM_MCP_ROOT` env var
- PEP 723 inline header — `uv run xlsx_server.py` self-bootstrap, bez vanjskog `requirements.txt`
- FastMCP server name: `lm-xlsx`

LM Studio ima oba servera registrirana paralelno: `lm-fs` (file ops) i `lm-xlsx` (excel ops). Razdvajanje znači:
- Jasna granica odgovornosti — file ops nisu zatrpan pandas/rapidfuzz ovisnostima
- Excel server se može isključiti u LM Studiju kad ne treba, bez diranja file ops servera
- Manji blast radius kod izmjena

Sandbox helper `_safe(path)` se kopira iz `server.py` u `xlsx_server.py`. Ako bude treća upotreba u budućnosti, refaktor u zajednički modul. Za sad ne — duplikat 6 linija nije problem.

## 3. Sandbox semantika

Identično postojećem serveru:
- `LM_MCP_ROOT` env var je obavezan, server pukne pri startu ako ga nema ili nije postojeći direktorij
- Path se resolvira (`Path.resolve()`) i provjerava da je unutar root-a — zaštita od `../`, apsolutnih putanja, simlinkova
- Putanje u tool argumentima su relativne na root (apsolutne su dopuštene ali moraju ležati unutar root-a)
- Path izvan root-a → `ValueError("path escapes sandbox root")`

## 4. Tool API

Svi alati su read-only. Svi prihvaćaju `path` kao prvi argument (relativan na sandbox root).

### 4.1 `xlsx_overview(path, sheet=None)`

Brzi pogled na tablicu. Ovo je prvi poziv koji LLM napravi nad nepoznatom datotekom da se orijentira.

Vraća:
- Ime datoteke i tip (`xlsx` / `xls` / `csv`)
- Popis sheetova (za xlsx/xls) i koji je aktivan
- Dimenzije: `rows × cols`
- Popis stupaca s tipom svakog (`string` / `int` / `float` / `datetime` / `bool`)
- Prvih 5 redaka
- Zadnjih 5 redaka

### 4.2 `xlsx_read_rows(path, start, count=50, sheet=None)`

Čitanje raspona redaka `[start, start+count)`.

- `start` 0-based, red 0 = prvi data red (nakon headera)
- `count` default 50, hard cap 1000
- Output: header + redovi + napomena `showing X–Y of Z total`

### 4.3 `xlsx_read_column(path, column, start=0, count=200, sheet=None, unique=False)`

Vrijednosti jednog stupca s paginacijom.

- `column` može biti ime stupca (string) ili 0-based index (int)
- `unique=True` → vrati samo različite (distinct) vrijednosti, čuvaj prvi pojavljeni redoslijed (ne sortiraj) — korisno za "koje kategorije/jmj postoje"
- `count` default 200, hard cap 2000

### 4.4 `xlsx_search(path, query, columns=None, mode="fuzzy", limit=20, sheet=None)`

Pretraga.

- `columns=None` → pretražuj sve string-stupce (pandas `object` dtype); inače lista imena stupaca
- Vrijednosti odabranih stupaca po redu spajaju se u jedan string preko jednog razmaka (`" "`) prije usporedbe
- `mode`:
  - `"exact"` — substring match, case-insensitive, na spojenom stringu reda
  - `"fuzzy"` (default) — `rapidfuzz.token_set_ratio(query, joined_row)`, vraća se samo redovi sa `score >= 60`
- Vraća top `limit` redaka, sortirano po score-u opadajuće, sa dodatnom `score` kolonom (0–100)

### 4.5 `xlsx_match_list(path, candidates, column, limit_per_candidate=5, sheet=None)`

Glavni use case: lista vs lista.

- `candidates` je lista stringova (npr. nepoznati artikli koje treba spojiti s katalogom)
- Za svaki kandidat, vrati top N najsličnijih redaka iz `column` po `rapidfuzz.token_set_ratio`
- **Bez minimalnog threshold-a** — uvijek vrati top N sa score kolonom, neka LLM sam procijeni je li match dovoljno dobar (ako je top score 12, to je signal "nema dobrog matcha")
- Output je grupiran po kandidatu, po jedan blok rezultata na svaki

## 5. Output format

Sve vraća **TSV s headerom** (tab-separated values).

Razlozi:
- Minimum tokena (markdown table troši duplo zbog `|` i `-` separatora)
- LLM odlično parsira TSV
- Lakše za truncate na granici reda

Pravila:
- Ćelije s tabovima/newline → escape u `\t` / `\n` da ne razbiju strukturu
- NaN/None → prazan string
- Datumi → `str(value)` (čuva originalni prikaz iz tablice)
- Metadata header preko `# ...` linije na vrhu (npr. `# rows 0–49 of 12483, sheet "Glavni"`)
- Hard cap na ~50k znakova outputa; preko toga truncate na granici reda i dodaj `# truncated, X more rows omitted — narrow your query or paginate`

**Primjer (`xlsx_read_rows`):**
```
# rows 0–49 of 12483, sheet "Glavni"
sifra	naziv	cijena	jmj
1001	Vijak M8x40 inox	0.45	kom
1002	Matica M8 inox	0.12	kom
```

**Primjer (`xlsx_search`, fuzzy):**
```
# search "M8 nehrdajuci vijak 40", mode=fuzzy, top 20 of 47 matches
score	sifra	naziv	cijena	jmj
94	1001	Vijak M8x40 inox	0.45	kom
71	1015	Vijak M8x50 inox	0.52	kom
```

**Primjer (`xlsx_match_list`):**
```
# matched 3 candidates against column "naziv", top 5 each

## "M8 vijak nehrdajuci 40mm"
score	sifra	naziv
94	1001	Vijak M8x40 inox
71	1015	Vijak M8x50 inox

## "matica M8 inox"
score	sifra	naziv
98	1002	Matica M8 inox
```

## 6. Edge cases i error handling

**Path / sandbox:**
- Path izvan `LM_MCP_ROOT` → `ValueError("path escapes sandbox root")`
- File ne postoji → `FileNotFoundError`
- Nepodržana ekstenzija → `ValueError("unsupported file type, expected .xlsx/.xls/.csv")`

**Sheet:**
- `.csv` + `sheet` parametar → tiho ignoriraj (CSV nema sheetove)
- `.xlsx`/`.xls` bez `sheet` → koristi prvi/aktivni, javi koji je u outputu
- `sheet` ne postoji → `ValueError("sheet 'X' not found, available: ['A','B','C']")`

**Stupac:**
- `column` ne postoji → `ValueError("column 'X' not found, available: [...]")`
- `column` kao broj izvan range → isto
- Prazan stupac (svi NaN) u `xlsx_read_column` → vrati prazan rezultat s napomenom

**Paginacija:**
- `start` ≥ broj redaka → prazan rezultat s napomenom `start X >= total Y`
- `count <= 0` → `ValueError`
- `count` preko hard cap-a → klemaj na cap (1000 za rows, 2000 za column), javi u outputu

**Pretraga:**
- Prazan `query` → `ValueError("query cannot be empty")`
- `xlsx_match_list` s praznom listom kandidata → `ValueError`
- Nijedan match (fuzzy ispod praga) → prazan rezultat s napomenom

**Format datuma/brojeva:**
- Pandas defaultno parsira datume kao `Timestamp`. U TSV outputu sve kroz `str()` (ne ISO format jer Excel datumi često stižu kao `01.04.2025`)
- Opcijski `date_format` parametar može se dodati kasnije ako bude trebalo

**Encoding CSV:**
- Probaj UTF-8 → cp1250 (Windows hrvatski) → latin-1 fallback
- Javi u outputu koji je encoding korišten ako nije UTF-8

## 7. Dependencies

PEP 723 inline header:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "pandas>=2.0",
#   "openpyxl>=3.1",
#   "xlrd>=2.0.1",
#   "rapidfuzz>=3.0",
# ]
# ///
```

Napomene:
- `xlrd` 2.0+ podržava samo stari `.xls` (od 2.0 izbacili xlsx podršku iz security razloga)
- `.xlsx` ide kroz `openpyxl` backend pandasa
- CSV ide kroz pandas builtin (csv modul interno)

`uv run xlsx_server.py` će sve to skinuti automatski prvi put.

## 8. LM Studio integracija

LM Studio MCP config (na korisničkoj strani):

```json
{
  "mcpServers": {
    "lm-fs": {
      "command": "uv",
      "args": ["run", "/full/path/to/server.py"],
      "env": {"LM_MCP_ROOT": "/full/path/to/sandbox"}
    },
    "lm-xlsx": {
      "command": "uv",
      "args": ["run", "/full/path/to/xlsx_server.py"],
      "env": {"LM_MCP_ROOT": "/full/path/to/sandbox"}
    }
  }
}
```

Oba servera dijele isti `LM_MCP_ROOT`. Excel/CSV datoteke koje LLM treba čitati moraju biti unutar tog direktorija.

## 9. Što NIJE u opsegu (out of scope)

- Pisanje / mijenjanje ćelija (read-only)
- Formule i izračuni
- Slike, charts, formatiranje
- Više-fajl join / cross-table query
- Eksport u drugi format
- Pivot tablice / agregacije

Ako neka od ovih stavki zatreba u budućnosti, dodaje se kao zaseban alat — ne diramo postojećih 5.

## 10. Test plan (skica)

Fixture datoteke:
- Mali xlsx s 2 sheeta, ~50 redaka, miješani tipovi (string/int/float/datum)
- Mali csv u UTF-8 i jedan u cp1250 (testiranje fallbacka)
- Veliki xlsx generiran skriptom (10k redaka) za testiranje paginacije i hard cap-ova

Pokrivenost:
- Po jedan happy-path test za svaki od 5 alata
- Sandbox escape (path izvan root-a)
- Sheet not found, column not found
- Paginacija: start=0, start usred, start preko range-a
- Encoding: UTF-8 i cp1250 csv
- Fuzzy search s primjerom iz domene (vijci, matice — varijacije naziva)
- `xlsx_match_list` s 3-5 kandidata, provjera grupiranja outputa
- Truncate ponašanje (output preko 50k znakova)
