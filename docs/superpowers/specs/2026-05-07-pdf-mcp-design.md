# LM Studio PDF MCP — Design Spec

**Datum:** 2026-05-07
**Status:** Draft, awaiting implementation
**Kontekst:** brainstorming session, korisnik = raja_rasta

## 1. Pregled

`lm-pdf` je read-only MCP server koji daje LM Studio LLM-u (i llama.cpp WebUI) alate za inspekciju, navigaciju i pretraživanje PDF dokumenata unutar `LM_MCP_ROOT` sandboxa.

**Glavni use case:** mješoviti / strukturni dokumenti — ugovori, ponude, tehničke specifikacije s naslovima, sekcijama, tablicama i (povremeno) skeniranim stranicama. LLM treba moći:

- dobiti pregled strukture nepoznatog dokumenta,
- pročitati specifične stranice ili sekcije,
- pretraživati tekst (fuzzy, jer hrvatski ima sklonidbe i dijakritike),
- izvući tablice za daljnju obradu.

**Tipičan dokument:** 20–100 stranica, mix digital text + povremeno skenirane stranice, s 1–10 tablica raspoređenih kroz dokument.

## 2. Arhitektura

- Zaseban MCP server u `pdf_server.py` (project root) pored postojećih active HTTP-aware verzija [server.py](../../../server.py), [web_server.py](../../../web_server.py) i [xlsx_server.py](../../../xlsx_server.py).
  - Napomena: `lm-studio-mcp/` direktorij sadrži frozen stdio-only kopije ostala tri servera za legacy LM Studio config. **Za `lm-pdf` ne radimo frozen kopiju** — nema postojeće LM Studio konfiguracije za pdf koju treba očuvati. Mcp.json će se update-ati da pokazuje direktno na root.
- Koristi `FastMCP` (isti paket kao ostala 3 servera).
- FastMCP server name: `lm-pdf`.
- Dijeli sandbox preko `LM_MCP_ROOT` env var.
- PEP 723 inline header — `uv run --script pdf_server.py` self-bootstrap, bez vanjskog `requirements.txt`.
- Podržava oba transporta kao xlsx_server.py: `MCP_TRANSPORT=stdio` (default, LM Studio) i `MCP_TRANSPORT=http` (llama.cpp WebUI), kontroliran istim env mehanizmom.

LM Studio (`~/.lmstudio/mcp.json`) ima 4 servera registrirana paralelno: `lm-fs` (file ops), `lm-web` (web/SearXNG), `lm-xlsx` (Excel), `lm-pdf` (PDF). Razdvajanje znači:

- Jasna granica odgovornosti — file ops nisu zatrpani PyMuPDF/pdfplumber/pytesseract ovisnostima.
- PDF server se može isključiti u LM Studiju kad ne treba.
- Manji blast radius kod izmjena.
- Ovisno o platformi (Linux/Windows packaging), PDF dependencies su izolirane.

`_safe(path)` sandbox helper se kopira iz `xlsx_server.py` u `pdf_server.py`. Sa 3 konzumenta i ~6 redaka koda, duplikat je još uvijek prihvatljiviji od refaktora u zajednički modul. Prag za refaktor: kad četvrti server bude trebao isti helper, ide u zajednički modul.

## 3. Sandbox semantika

Identično postojećim serverima:

- `LM_MCP_ROOT` env var je obavezan, server pukne pri startu ako ga nema ili nije postojeći direktorij.
- Path se resolvira (`Path.resolve()`) i provjerava da je unutar root-a — zaštita od `../`, apsolutnih putanja, simlinkova.
- Putanje u tool argumentima su relativne na root (apsolutne dopuštene ali moraju ležati unutar root-a).
- Path izvan root-a → `ValueError("path escapes sandbox root")`.

## 4. Biblioteke (PEP 723 inline deps)

```python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "pymupdf>=1.24",        # text, outline (TOC), metadata, page rendering
#   "pdfplumber>=0.11",     # table extraction
#   "rapidfuzz>=3.0",       # fuzzy search
#   "pytesseract>=0.3.10",  # OCR fallback (samo ako tesseract postoji u PATH)
# ]
# ///
```

Uloge:

- **PyMuPDF (`fitz`)** — primarni izvor: `doc.get_toc()` za outline, `page.get_text("text")` za tekst, `page.get_pixmap()` za render kad treba OCR, metadata.
- **pdfplumber** — tablice. PyMuPDF zna naći tablice u 1.23+, ali `pdfplumber`-ova `extract_tables()` daje čišći i kontroliraniji output.
- **rapidfuzz** — `token_set_ratio` / `partial_ratio`, isti pattern kao xlsx (threshold 60 za search, 70 za section heading match).
- **pytesseract** — OCR samo ako `tesseract` binary postoji u sustavu. Ako ne postoji → server radi normalno za digital-text PDF-ove, OCR-ovi alati vraćaju jasnu poruku.

Sustavna ovisnost (nije Python paket): `tesseract-ocr` + `tesseract-ocr-hrv` + `tesseract-ocr-eng`. Server provjerava prisutnost binary-ja u startup-u i logira (ne pukne).

## 5. Cache

Nužan jer:

- pdfplumber ekstrakcija tablica je sporo (~1–2s po stranici s tablicama),
- OCR je vrlo sporo (5–30s po stranici),
- LLM tipično radi više poziva nad istim dokumentom (overview → read_section → search → extract_tables).

### 5.1 Lokacija i ključ

- Direktorij: `<LM_MCP_ROOT>/.lm-pdf-cache/`
- Naziv fajla: `<basename>__<size>__<mtime_ns>.json`
  - npr. `ugovor.pdf__285431__1714867234123456789.json`
- Hash uključuje veličinu i `mtime_ns` → automatska invalidacija kad se PDF promijeni.
- Cache direktorij se stvori automatski pri prvom pisanju.

### 5.2 Sadržaj

```json
{
  "version": 1,
  "source": "ugovor.pdf",
  "size": 285431,
  "mtime_ns": 1714867234123456789,
  "meta": {
    "title": "Ugovor o nabavi...",
    "author": "...",
    "creator": "...",
    "creation_date": "2025-04-12",
    "page_count": 47
  },
  "outline": [
    {"level": 1, "title": "1. Predmet ugovora", "page": 2},
    {"level": 2, "title": "1.1 Definicije", "page": 3}
  ],
  "pages": [
    {"page": 1, "text": "...", "ocr_used": false},
    {"page": 2, "text": "...", "ocr_used": false}
  ],
  "tables": [
    {"page": 5, "index": 0, "rows": [["Stavka", "Količina"], ["Vijak", "500"]]}
  ],
  "stats": {
    "pages_with_text": 45,
    "pages_ocr": 2,
    "pages_empty": 0,
    "tables_count": 7
  }
}
```

### 5.3 Pipeline (prvi poziv)

1. Otvori PDF kroz PyMuPDF.
2. Izvuci `meta` iz `doc.metadata`.
3. Izvuci `outline` iz `doc.get_toc()`.
4. Za svaku stranicu:
   a. `page.get_text("text")`.
   b. Ako rezultat ima ≥ 20 znakova ne-whitespace → koristi taj tekst, `ocr_used=false`.
   c. Inače, ako `tesseract` postoji: `page.get_pixmap(dpi=200)` → `pytesseract.image_to_string(img, lang="hrv+eng")`. `ocr_used=true`.
   d. Inače: `text=""`, stranica se broji u `pages_empty`.
5. Otvori PDF kroz pdfplumber, `page.extract_tables()` za svaku stranicu, akumuliraj u `tables`.
6. Zapiši cache JSON atomski (`tempfile` + `os.replace`).

### 5.4 Disable / debug

`LM_PDF_NO_CACHE=1` env var → preskoči disk cache, parsiraj svaki put. Za debug i development.

## 6. Tool API

Svi alati su read-only. Svi prihvaćaju `path` kao prvi argument (relativan na sandbox root).

Stranice su **1-based** kroz cijeli API (kako PDF stranice ljudi pišu). Ovo se razlikuje od xlsx-a koji ima 0-based redove jer ima header.

### 6.1 `pdf_overview(path)`

Brzi pogled na dokument. Prvi poziv koji LLM napravi nad nepoznatim PDF-om.

Vraća (plain text s `# ...` headerom):

- File name, page count, file size.
- PDF metadata: title, author, creator, creation_date (ako postoje).
- Outline / TOC kao indented popis: `1. Predmet ugovora (str. 2)` / `  1.1 Definicije (str. 3)`.
  - Ako PDF nema bookmarke → `# no TOC bookmarks; use pdf_search to locate sections`.
- Stats: `pages_with_text=45 pages_ocr=2 pages_empty=0`.
- Popis stranica s tablicama: `tables on pages: 5, 8, 12 (7 total)`.

### 6.2 `pdf_read_pages(path, start, count=3)`

Čitanje raspona stranica `[start, start+count)`.

- `start` 1-based.
- `count` default **3**, hard cap **20** (stranice mogu biti goleme; veći cap bi prelio 50k char limit outputa).
- Output po stranici:

  ```
  # page 5 of 47
  
  <plain text stranice, line-broken kako je u PDF-u>
  
  # page 6 of 47
  ...
  ```

- Ako stranica je OCR-ana, header je `# page 5 of 47 (OCR)`.
- Ako stranica je prazna (text="", nije OCR-ana), header je `# page 5 of 47 (no text)`.
- **Inline tablice u stranici nisu posebno renderane** — koristi `pdf_extract_tables(path, page=5)`. Razlog: pdfplumber tablice i PyMuPDF tekst koriste različite parser-e i miješanje radi neuredan output. Podijeli odgovornost.

### 6.3 `pdf_read_section(path, heading, level=None)`

Vrati cijelu sekciju po naslovu.

- `heading` se traži u TOC-u kroz `rapidfuzz.partial_ratio(heading, toc_entry.title)` (threshold 70).
- `level=None` → bilo koja razina; `level=1` → samo top-level. Korisno kad je heading "Definicije" duplican u više glavnih sekcija.
- Vraća **prvi** match s najvišim score-om. Ako više matcheva s istim score-om → vraća prvi po redoslijedu pojavljivanja, a u headeru outputa popisuje ostale s napomenom "use level= to disambiguate".
- Output: tekst od početne stranice sekcije do **stranice prije** sljedećeg naslova iste-ili-više razine.
- Header: naziv sekcije, raspon stranica, popis ostalih kandidata ako postoje.
- Edge case: PDF bez TOC → `ValueError("PDF has no TOC bookmarks; cannot resolve sections — use pdf_search instead")`.
- Edge case: nijedan TOC entry ne prelazi threshold 70 → `ValueError("section <heading> not found; nearest TOC entries: ...")` s top 3 najbliža.

### 6.4 `pdf_search(path, query, mode="fuzzy", limit=20, page_range=None)`

Pretraga teksta.

- Granularnost: **paragraf**. Tekst svake stranice se cijepa na paragrafe po praznim redovima (regex `\n\s*\n+`), svaki paragraf se score-a posebno.
- `mode`:
  - `"exact"` — case-insensitive substring match na paragrafu.
  - `"fuzzy"` (default) — `rapidfuzz.token_set_ratio(query, paragraph)` ≥ 60.
- `page_range: list[int] | None = None` — opcionalno, lista točno 2 elementa `[start, end]` (1-based, inclusive). Drugi oblici → `ValueError("page_range must be a 2-element list [start, end]")`.
- Output (fuzzy):

  ```
  # search "rok isporuke", mode=fuzzy, threshold=60, top 20 of 8 matches
  score	page	section	paragraph
  87	5	3.2 Isporuka	Rok isporuke je 30 dana od potpisa ugovora...
  72	12	5.1 Penali	U slučaju kašnjenja u roku isporuke...
  ```

- `section` kolona — najbliži TOC heading koji pokriva tu stranicu (po pravilu: najveći page_start ≤ trenutna stranica). Prazno ako nema TOC-a.
- TSV truncate na 50k znakova s `# truncated, X more matches omitted` linijom (isto kao xlsx).
- Paragraf u TSV ćeliji escapean: tabovi → `\t`, newline → `\n`, carriage return → `\r`.

### 6.5 `pdf_extract_tables(path, page=None)`

- `page=None` → sve tablice u dokumentu, grupirane po stranici.
- `page=N` → samo tablice s te stranice (1-based).
- Output: TSV blok po tablici:

  ```
  # 7 tables in document, on pages: 5, 8, 12
  
  ## table 0 (page 5, 8 rows × 4 cols)
  Stavka	Količina	JM	Cijena
  Vijak M8x40 inox	500	kom	0.45
  ...
  
  ## table 1 (page 5, 3 rows × 5 cols)
  ...
  ```

- Bez normalizacije spojenih ćelija — pdfplumber output ide direktno u TSV. Limitacija ovog pristupa, dokumentirano u headeru.
- Hard cap **20 tablica po pozivu**, preko toga truncate s napomenom `# truncated, X more tables omitted — use page= to narrow`.
- Empty cells → prazan string u TSV-u (isto kao xlsx).

## 7. Output format

Sve vraća **TSV ili plain text s `# ...` metadata headerom** (isti pattern kao xlsx). Razlozi:

- Minimum tokena (markdown table troši duplo zbog `|` i `-` separatora).
- LLM odlično parsira TSV.
- Lakše za truncate na granici reda / stranice.

Pravila:

- Ćelije s tabovima/newline → escape u `\t` / `\n`.
- NaN/None → prazan string.
- Hard cap na ~50k znakova outputa po pozivu; preko toga truncate na granici reda/stranice/tablice i dodaj `# truncated, X more ... omitted`.
- Header preko `# ...` linija na vrhu (file name, page count, search params, itd.).

## 8. Edge cases i error handling

**Path / sandbox:**

- Path izvan `LM_MCP_ROOT` → `ValueError("path escapes sandbox root")`.
- File ne postoji → `FileNotFoundError`.
- Nije PDF (po ekstenziji) → `ValueError("expected .pdf, got <ext>")`.
- Encrypted PDF bez passworda → `ValueError("PDF is encrypted; password not supported")`. Ne pokušavamo crack-ati ili pitati za password — explicitly out of scope.
- Corrupted PDF (PyMuPDF baci) → propušta original exception s napomenom file path-a.

**Stranica:**

- `page` ili `start` < 1 → `ValueError("page must be >= 1")`.
- `start` > broj stranica → prazan rezultat s napomenom `# start X > page_count Y`.
- `count <= 0` → `ValueError`.
- `count` preko cap-a → klemaj na cap (20 za read_pages, 20 za extract_tables), javi u outputu.

**Section / TOC:**

- PDF bez TOC + `pdf_read_section` → `ValueError("PDF has no TOC bookmarks; cannot resolve sections — use pdf_search instead")`.
- Section heading bez matcha → `ValueError` sa top 3 najbližih kandidata.
- Više section-a s istim score-om → uzmi prvi, javi ostale u headeru.

**Search:**

- Prazan `query` → `ValueError("query cannot be empty")`.
- `page_range` van granica → klemaj na `[1, page_count]`, javi u headeru.
- Nijedan match (fuzzy ispod praga) → prazan rezultat s napomenom `# no matches`.

**OCR:**

- `tesseract` binary nije u PATH → server startuje normalno, log poruka pri startupu, `pages_ocr=0` u stats-u za skenirane PDF-ove. Stranice bez teksta i bez OCR-a označene kao `(no text)`.
- `tesseract-ocr-hrv` paket nije instaliran → fallback na `lang="eng"`, log warning. Hrvatski tekst će biti loše OCR-an ali ne pukne.
- OCR neuspjeh na stranici (timeout, korumpirana slika) → catch, prazan tekst, log warning.

**Cache:**

- Cache direktorij ne postoji → kreiraj ga.
- Cache fajl korumpiran (JSON parse fail) → re-parsiraj, prepiši cache.
- Disk full pri pisanju cache-a → log warning, fallback na in-memory parsing za taj poziv.
- `LM_PDF_NO_CACHE=1` → potpuno preskoči disk cache.

## 9. LM Studio integracija

Dodaje se 4. server u postojeći `~/.lmstudio/mcp.json`:

```json
{
  "mcpServers": {
    "lm-fs": { ... },
    "lm-web": { ... },
    "lm-xlsx": { ... },
    "lm-pdf": {
      "command": "/home/josip-rastocic/.local/bin/uv",
      "args": [
        "run",
        "--script",
        "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/pdf_server.py"
      ],
      "env": {
        "LM_MCP_ROOT": "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/lm-studio-sandbox"
      }
    }
  }
}
```

Sva 4 servera dijele isti `LM_MCP_ROOT`. PDF datoteke koje LLM treba čitati moraju biti unutar tog direktorija.

## 10. llama.cpp WebUI integracija

Sukladno postojećem dual-frontend setupu (LM Studio + llama.cpp WebUI), `lm-pdf` mora biti dostupan i kroz HTTP transport za llama.cpp.

- PEP 723 script podržava oba transporta: `MCP_TRANSPORT=stdio` (default, za LM Studio) i `MCP_TRANSPORT=http` (za llama.cpp).
- HTTP host/port preko `MCP_HOST`/`MCP_PORT` env vars, default `127.0.0.1:8092` (xlsx koristi 8091 — uzimamo sljedeći).
- `start-mcp-http.sh` se proširuje da podiže i `lm-pdf` HTTP server pored `lm-xlsx`.
- `stop-mcp-http.sh` se proširuje da gasi i `lm-pdf`.

## 11. Što NIJE u opsegu (out of scope)

- Pisanje / mijenjanje PDF-a (read-only).
- Encrypted PDF-ovi (password handling).
- PDF forms (fillable form fields) — option E iz prve faze brainstorminga, eksplicitno odbačeno.
- Ekstrakcija slika / figura — opcija F, eksplicitno odbačeno za prvi krug.
- Cross-document search / kompariranje više PDF-ova.
- Math / equations — koristio bi marker-pdf umjesto našeg pristupa.
- Eksport u drugi format (HTML, DOCX).
- Komparacija s xlsx-om / cross-tool join.
- AI parser-i (docling, marker-pdf) — odbačeni u korist lakšeg toolchaina.

Ako neka od ovih stavki zatreba u budućnosti, dodaje se kao zaseban alat — ne diramo postojećih 5.

## 12. Test plan (skica)

Fixture datoteke (sve unutar `tests/fixtures/pdf/`):

- `simple-text.pdf` — 5 stranica plain text, born-digital, generiran iz Markdown-a.
- `with-toc.pdf` — 10 stranica s pravim TOC bookmarkima i 3-razinskim hijerarhijom.
- `with-tables.pdf` — 3 stranice s 4 tablice raznih veličina (uključuje 1 spojenu ćeliju).
- `scanned-page.pdf` — 3 stranice, srednja je skenirana slika bez text layera.
- `croatian.pdf` — kratak hrvatski tekst s dijakriticima (š, č, ć, đ, ž) za fuzzy search.
- `large.pdf` — generiran skriptom, 100 stranica, za testiranje paginacije i hard cap-ova.

Pokrivenost:

- Po jedan happy-path test za svaki od 5 alata.
- Sandbox escape (path izvan root-a).
- File ne postoji, krivi ekstenzija.
- Encrypted PDF → ValueError.
- `pdf_overview` na PDF-u s i bez TOC-a.
- `pdf_read_pages` paginacija: start=1, sredina, preko range-a, count preko cap-a.
- `pdf_read_section` s exact match-om, fuzzy match-om, ambiguous match-om, no-match (sa preporukama), no-TOC error.
- `pdf_search` exact i fuzzy, hrvatski upit s dijakriticima, page_range filter, prazan upit.
- `pdf_extract_tables` na stranici s više tablica, na PDF-u bez tablica, page=None vs page=N.
- OCR: skenirana stranica s tesseract-om instaliran (provjeri `ocr_used=true`); ako tesseract nije dostupan u CI-u, mock pytesseract.
- Cache: prvi poziv puni cache, drugi koristi cache (provjera mtime-based invalidacije nakon `touch` fajla), `LM_PDF_NO_CACHE=1` flag.
- Truncate ponašanje (output preko 50k znakova).

Testovi se pokreću kroz postojeći `./run_tests.sh tests/test_pdf_server.py -v`.

## 13. Sigurnosni razmotrenja

- Sandbox identičan ostalim serverima — path escape je jedini relevantan attack vector.
- `pytesseract` poziva `tesseract` binary preko `subprocess` — `pytesseract` interno escape-a argumente, ne ručna konstrukcija command-line-a.
- Cache JSON sadrži samo ekstrahirani tekst (ne sirove byte-ove PDF-a), nema rizika od code execution.
- PyMuPDF i pdfplumber su mature, dobro održavane biblioteke; CVE-i pratimo kroz `uv` lockfile (kad ga uvedemo).
- Velikim/zlonamjernim PDF-om može se pokušati DoS (PyMuPDF zip bomb, pdfplumber memory exhaust). Mitigacija odgođena — sandbox je lokalan, korisnik kontrolira što stavlja u njega.
