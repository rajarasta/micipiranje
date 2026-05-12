# `lm-delegate` filesystem tools — `read_with_focus` + `rank_files`

**Datum:** 2026-05-12
**Status:** Design — čeka korisničko odobrenje prije implementacije

## 1. Cilj

Proširiti `lm-delegate` MCP server s dva nova alata koja čitaju datoteke s diska i koriste mali 9B model za triage:

- **`read_with_focus(path, focus, max_words)`** — pročita datoteku (text ili PDF), 9B sažme s usmjerenjem, vrati summary + relevantni rasponi (linije za tekst, stranice za PDF). 35B onda može selektivno učitati samo te raspone umjesto cijele datoteke.
- **`rank_files(query, paths, preview_chars)`** — uzme N datoteka, učita preview svake, 9B u jednom batched pozivu rangira ih po relevantnosti za upit. 35B onda zna koje datoteke vrijedi otvoriti.

**Glavni cilj: smanjiti tokene koje 35B troši na čitanje velikih datoteka i triage.** Primarni use case je analiza dokumenata kao Feal katalog (PDF s 80+ stranica) i navigacija kroz codebase.

## 2. Polazno stanje

### `lm-delegate` MCP server (postojeći)

- Datoteka: [`delegate_server.py`](../../delegate_server.py)
- Port: 8095 (HTTP) ili stdio (LM Studio kroz frozen kopiju `lm-studio-mcp/delegate_server.py`)
- Backend: 9B Qwen3.5 na `http://127.0.0.1:8093/v1`, 65k context, `--parallel 1`
- Postojeći alati: `quick_classify`, `extract_json`, `summarize_chunk`
- Sve alate dijele `_client()` + `_model()` helpere, stateless OpenAI klijent per call, `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`

### Testna infrastruktura

- Unit testovi: `tests/test_delegate_server.py` — mock OpenAI klijent, importlib.reload pattern, 9 testova (3 po postojećem alatu)
- Integration testovi: `tests/test_delegate_server_integration.py` — opt-in (`RUN_INTEGRATION=1`), live llama-server endpoint
- Test runner: `run_tests.sh` već uključuje `mcp>=1.2`, `openai>=1.40`, `pymupdf>=1.24`

### Token economics (procjena za tipičan rad)

| Operacija u prošloj sesiji | Trošak (35B kontekst) |
|----------------------------|-----------------------|
| `read_file` PDF kataloga 50k tokena | ~50 000 tokena |
| `search_files` vrati 20 putanja | ~500 tokena (mali) |
| `terminal` output 500 linija | ~3 000 tokena |
| `skill_view` skill datoteka | ~2 000-5 000 tokena |

`read_with_focus` na PDF: ~50 000 → ~500 tokena u 35B kontekst (sa relevant page rasponima). **Ušteda ~99% za PDF triage.**

`rank_files` na 20 putanja umjesto 20×`read_file`: ~50 000 → ~2 000 tokena. **Ušteda ~96% za multi-file triage.**

## 3. Tool surface

### 3.1 `read_with_focus`

```python
@mcp.tool()
def read_with_focus(path: str, focus: str, max_words: int = 200) -> dict[str, Any]:
    """Read a file and return a focused summary + relevant ranges.

    For text files (.py, .js, .ts, .sh, .md, .txt, .json, .yaml, .csv, ...):
        - Returns line-based ranges. range_unit = "lines".
    For PDF files (.pdf):
        - Returns page-based ranges via pymupdf. range_unit = "pages".
    For other files:
        - Attempt UTF-8 read; if it fails, raise ValueError("binary file not supported").

    Args:
        path: Absolute path to the file.
        focus: What the caller cares about (e.g., "where prices are calculated",
               "Feal articles with louvre profiles", "HTTP server setup").
        max_words: Target summary length in words.

    Returns:
        dict with keys:
          summary: str        # ~max_words words
          relevant_ranges: list[tuple[int, int]]   # inclusive line or page ranges
          range_unit: str     # "lines" or "pages"
          total_units: int    # total line count or page count
          file_type: str      # "python", "pdf", "text", "json", ...

    Raises:
        FileNotFoundError: path does not exist.
        ValueError: binary file, or file too large for single-pass (>60k token estimate).
    """
```

### 3.2 `rank_files`

```python
@mcp.tool()
def rank_files(query: str, paths: list[str], preview_chars: int = 2000) -> list[dict[str, Any]]:
    """Rank files by relevance to query via a single batched LLM call.

    For each path, reads up to preview_chars (or first page only for PDFs).
    Files that fail to open get score 0 with reason "(file not found)" or
    "(unreadable)" — they do not abort the batch.

    Total preview tokens are estimated against 60k budget; exceeds budget
    raises ValueError. The caller should pre-filter (e.g. via search_files
    or grep) if too many candidates.

    Args:
        query: Relevance query (e.g. "FastMCP server setup", "tax calculation").
        paths: Absolute paths to candidate files.
        preview_chars: Bytes/chars to read from each file (default 2000).

    Returns:
        list of dicts sorted by score descending:
          [{path: str, score: int (0-10), reason: str}, ...]

    Raises:
        ValueError: estimated token budget exceeds 60k.
    """
```

## 4. Internal flow

### 4.1 `read_with_focus`

```
1. Validate: Path(path).exists() else FileNotFoundError.

2. Detect file_type from extension (case-insensitive):
     .pdf                → "pdf"
     .py                 → "python"
     .js / .ts           → "javascript" / "typescript"
     .sh                 → "shell"
     .md                 → "markdown"
     .json               → "json"
     .yaml / .yml        → "yaml"
     .csv                → "csv"
     .txt / no extension → "text"
     other               → "text" (attempt UTF-8; binary fallback raises)

3. Read content:
   - PDF: pymupdf.open(path), iterate pages, build text with "=== PAGE {n} ===" markers.
   - Else: Path(path).read_text(encoding="utf-8"). On UnicodeDecodeError raise
     ValueError("binary file not supported: {path}").

4. Pre-budget check:
   - Estimate tokens = len(content) // 4.
   - If estimate > 60000: raise ValueError(
       f"file too large for single-pass ({estimate} estimated tokens); "
       "consider grep/lm-pdf chunking first").

5. Special cases (no LLM call):
   - total_units == 0 (empty file) → return {
       summary: "(empty file)",
       relevant_ranges: [],
       range_unit: "lines" if not PDF else "pages",
       total_units: 0,
       file_type: <detected>,
     }

6. Build numbered content for LLM prompt:
   - For text: prepend each line with f"L{n}: " (1-indexed).
   - For PDF: page markers already in place from step 3.

7. Single LLM call:
   - Compute `unit = "pages" if file_type == "pdf" else "lines"`.
   - system prompt (Python f-string with `unit` substituted):
       f"Read the following file. Focus: {focus}. Return JSON exactly matching:\n"
       f"  {{\"summary\": <max ~{max_words} word summary>,\n"
       f"   \"relevant_ranges\": [[start, end], ...],\n"
       f"   \"range_unit\": \"{unit}\"}}\n"
       f"Be conservative — only include ranges with genuinely relevant content."
   - user message: numbered content
   - temperature=0.2
   - max_tokens=max_words * 4 + 500   # summary + JSON wrapper headroom
   - response_format={"type": "json_object"}
   - extra_body={"chat_template_kwargs": {"enable_thinking": False}}

8. Parse JSON. Augment with total_units (line/page count from step 3) and
   file_type. Return.

9. If json.JSONDecodeError: raise ValueError(
     "model did not return valid JSON; raw={raw[:500]!r}") from exc.
```

### 4.2 `rank_files`

```
1. Empty input fast path: paths == [] → return [].

2. For each path (preserving order, tracking index):
   - If not Path(path).exists():
       previews[i] = None, errors[i] = "(file not found)"
   - If .pdf:
       try pymupdf.open(path), extract page 1 text only, truncate to preview_chars
       on FileDataError/IndexError: errors[i] = "(unreadable PDF)"
   - Else:
       try Path(path).read_text(encoding="utf-8")[:preview_chars]
       on UnicodeDecodeError: errors[i] = "(binary)"
       on OSError: errors[i] = "(unreadable)"

3. Estimate token budget:
     budget = sum(len(p) for p in previews if p is not None) // 4 + (50 * len(paths))
   The 50/path overhead accounts for index markers + path strings in prompt.
   If budget > 60000:
     raise ValueError(
       f"rank_files token budget exceeded ({budget} > 60000); "
       f"consider smaller preview_chars or fewer paths").

4. Build prompt:
   - system:
       "Query: {query}
        Score each file 0-10 for relevance (10 = exactly what query asks about, 
        0 = unrelated). Return JSON exactly matching:
        {\"rankings\": [{\"index\": <int>, \"score\": <int 0-10>, \"reason\": <short string>}, ...]}
        One object per file. Reason: max 15 words."
     (Wrapped in an outer object because `response_format={"type": "json_object"}`
     requires the top-level value to be an object, not a bare array.)
   - user: concatenated previews like:
       "[0] /path/to/file.py
        <preview text>
        
        [1] /path/to/other.pdf
        <preview text>
        
        ..."
     Errored files appear with placeholder: "[3] /path/to/missing.x
                                             (could not load)"

5. Single LLM call (same params as 4.1 step 7, but max_tokens = 50 * len(paths) + 500).

6. Parse JSON. Extract `rankings` list from the top-level object. For each item:
   - If index in errors: emit {path, score: 0, reason: errors[index]}
   - Else: emit {path: paths[index], score: clamp(score, 0, 10), reason: reason}
   - Missing indices in model output: emit {path, score: 0, reason: "(model omitted)"}

7. Sort by score descending. Return.
```

## 5. Edge cases (binding contract)

| Slučaj | Ponašanje |
|--------|-----------|
| `read_with_focus(path="/nonexistent")` | `FileNotFoundError` |
| `read_with_focus(path=".../image.png")` | `ValueError("binary file not supported")` |
| `read_with_focus` na praznoj datoteci | Vrati prazan rezultat, NULL LLM poziva |
| `read_with_focus` na datoteci >60k tokena | `ValueError("file too large...")` |
| `read_with_focus` na korumpiranom PDF-u | `ValueError("PDF read failed: {pymupdf err}")` |
| `rank_files(paths=[])` | Vrati `[]` |
| `rank_files` budget > 60k tokena | `ValueError("rank_files token budget exceeded...")` |
| `rank_files` jedan path ne postoji | Taj path dobije `score=0, reason="(file not found)"`, batch nastavi |
| `rank_files` model omitne index | Taj path dobije `score=0, reason="(model omitted)"` |
| Bilo koji LLM odgovor nije valid JSON | `ValueError("model did not return valid JSON; raw=...")` |

## 6. Token budget math (provjera)

### `read_with_focus`

Worst case: tekstualna datoteka točno na granici (60k tokena ≈ 240 000 chars), max_words=500.

- Input prompt: ~60 000 tokena (sadržaj) + ~200 tokena (system)
- Output: max_words × 4 + 500 = 2500 tokena (summary + JSON wrapper)
- Total slot ctx: ~62 700 tokena → fits in 65 536 slot.

Praktično: PDF Feal kataloga 80 stranica × ~250 riječi/strana × 1.3 token/riječ = ~26 000 tokena. Solidno unutar budgeta.

### `rank_files`

Worst case: 30 datoteka, `preview_chars=2000`.

- Previews: 30 × 2000 chars ≈ 30 × 500 tokena = 15 000 tokena
- Path strings + index markers: ~30 × 50 = 1 500 tokena
- System prompt: ~150 tokena
- Output: 30 × 50 + 500 = 2 000 tokena
- Total slot ctx: ~18 650 tokena → puno headroom-a.

Limit od 60k tokena na ulazu znači u praksi ~120 datoteka × 2k chars, ili 60 datoteka × 4k chars.

## 7. Dependencies

Dodati u PEP 723 metadata `delegate_server.py`:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "openai>=1.40",
#   "pymupdf>=1.24",       # NEW — PDF text extraction
# ]
# ///
```

`run_tests.sh` već uključuje `pymupdf>=1.24` (testira `pdf_server.py`), ne treba dodatne izmjene.

## 8. Testing

### Unit testovi (`tests/test_delegate_server.py`)

Slijedi postojeći pattern (mocked OpenAI klijent, `importlib.reload(delegate_server)` per test, `_fake_completion` helper).

**Za `read_with_focus` (6 testova):**

1. `test_read_with_focus_text_file_returns_summary_and_line_ranges` — pripremi tmp_path datoteku s 30 linija Python koda, mock vrati JSON s `relevant_ranges=[[5,10]]`, asserta:
   - povratni dict ima `summary`, `relevant_ranges=[(5,10)]`, `range_unit="lines"`, `total_units=30`, `file_type="python"`
   - system prompt sadrži `focus` string
   - user message sadrži numbered lines (`L1: ...`)
   - temperature=0.2, response_format json_object, extra_body s no-think
2. `test_read_with_focus_pdf_file_returns_page_ranges` — fixture PDF (2 stranice, generiraj preko pymupdf), assert `range_unit="pages"`, `total_units=2`, page markers u prompt-u
3. `test_read_with_focus_empty_file_skips_llm` — prazna datoteka, assert nikakav LLM poziv (`fake_client.chat.completions.create.assert_not_called()`)
4. `test_read_with_focus_binary_raises` — datoteka s bytes-ima koji nisu UTF-8, assert `ValueError("binary")`
5. `test_read_with_focus_missing_path_raises` — assert `FileNotFoundError`
6. `test_read_with_focus_file_too_large_raises` — patch `Path.read_text` da vrati 250k chars, assert `ValueError("file too large")`

**Za `rank_files` (5 testova):**

7. `test_rank_files_batched_returns_sorted_results` — 3 mock fixture files, mock vrati `[{index:1,score:9}, {index:0,score:4}, {index:2,score:2}]`, asserta:
   - rezultat sortiran descending: `paths[1]` prvi, `paths[0]` drugi, `paths[2]` treći
   - svaki rezultat ima `path`, `score`, `reason`
   - single LLM poziv (`assert_called_once`)
8. `test_rank_files_empty_paths_skips_llm` — paths=[], assert nikakav LLM poziv, vrati []
9. `test_rank_files_missing_path_gets_zero` — 3 paths, prvi ne postoji; mock vrati scoring za druga dva; assert da non-existent path ima `score=0, reason="(file not found)"`
10. `test_rank_files_budget_exceeded_raises` — 100 paths svaki 10k chars, assert `ValueError("token budget exceeded")` PRIJE LLM poziva
11. `test_rank_files_pdf_preview_uses_only_first_page` — mock pymupdf da fixture PDF ima 5 stranica, assert da preview u prompt-u sadrži samo prvi page text, ne sve stranice

### Integration testovi (`tests/test_delegate_server_integration.py`)

Dodati 2 nova testa, gated `RUN_INTEGRATION=1`:

12. `test_read_with_focus_live` — kreira tmp_path Python datoteku s funkcijom `compute_tax(amount, rate)` i ~30 drugih linija. Poziv `read_with_focus(path, focus="tax calculation", max_words=80)`. Asserta:
    - `range_unit == "lines"`
    - barem jedan range sadrži linije gdje je `def compute_tax`
    - `summary` spominje "tax" ili "porez"
13. `test_rank_files_live` — kreira 3 fixture datoteke (jedna s HTTP servera, jedna s tax računanja, jedna s utility funkcijama). Query="HTTP server setup". Asserta da je file s HTTP serverom na vrhu.

## 9. LM Studio mirror

Nakon implementacije:
1. `cp delegate_server.py lm-studio-mcp/delegate_server.py`
2. **Odmah ručno trim** `__main__` block u frozen kopiji (vrati na čisti `if __name__ == "__main__": mcp.run()`) — matchira konvenciju ostalih frozen-a.
3. Nema promjena u `~/.lmstudio/mcp.json` — entry već postoji, alati se otkrivaju kroz `ListToolsRequest`.

## 10. Out of scope (svjesno)

- **Caching** — ista datoteka summarize-ana 5× ide cijeli krug ponovo. YAGNI; ako se pojavi pravo cijeđenje, dodati LRU dekorator kasnije.
- **Streaming** — alati blokiraju do kompletnog odgovora. 9B s ovim payload-ovima završava u 1-5 sekundi.
- **Recursive directory ranking** — `rank_files(paths=[...])` zahtijeva eksplicitnu listu. "Rank sve `.py` u repo-u" radi 35B u dva koraka: `search_files` → `rank_files`.
- **Multi-language line numbering** — alat ne razumije jezik datoteke (`.py` vs `.js` vs `.go`); naprosto numerira sve linije. Model odlučuje koje su relevantne.
- **OCR za skenirane PDF-ove** — pymupdf vraća prazan tekst za skenirane PDF-ove. Korisnik treba prvo proći kroz `lm-pdf` koji ima OCR fallback. Ako `read_with_focus` dobije skenirani PDF, vraća prazan summary; ne pokušava OCR samostalno.

## 11. Build sequence (faze)

1. **Faza 1 — `read_with_focus`** (3 koraka)
   - Step 1: Dodati `pymupdf>=1.24` u PEP 723 deps.
   - Step 2: TDD `read_with_focus` — testovi 1-6 → implementacija.
   - Step 3: Commit.

2. **Faza 2 — `rank_files`** (2 koraka)
   - Step 1: TDD `rank_files` — testovi 7-11 → implementacija.
   - Step 2: Commit.

3. **Faza 3 — integration testovi** (1 korak)
   - Live testovi 12-13. Pokrenuti i commit-ati ako prolaze.

4. **Faza 4 — LM Studio mirror** (1 korak)
   - Copy + trim `__main__` + commit.

5. **Faza 5 — Eventual real-world dry-run**
   - Pokreni Hermes na pravom Feal katalogu: "use read_with_focus on Feal-FASADA-50-FK.pdf with focus on louvre profiles". Provjeri da:
     - PDF se uspješno pročita
     - relevant_ranges pokazuje na realne stranice gdje su louvre profili
     - summary je u hrvatskom (jer je sadržaj hrvatski)
   - Ovo nije test već prva produkcijska upotreba; ne ulazi u commit, samo verificira.
