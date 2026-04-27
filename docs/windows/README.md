# LM Studio MCP — Windows setup

Spreman `mcp.json` za Windows je u istom folderu. Default putanje:

- Projekt:        `C:\LMStudio\`
- Windows user:   `RAJA`
- `uv.exe`:       `C:\Users\RAJA\.local\bin\uv.exe`

Ako koristiš drugog usera ili drugu lokaciju, otvori `mcp.json` i Find/Replace:

| Zamijeni            | Sa                                |
|---------------------|-----------------------------------|
| `C:/Users/RAJA`     | `C:/Users/<tvoj-username>`        |
| `C:/LMStudio`       | npr. `D:/LMStudio` ili gdje već   |

Forward-slashove (`/`) JSON podržava i Windows ih jednako razumije — ne treba `\\`.

---

## Koraci

**1. Instaliraj `uv` (PowerShell):**

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Provjeri:

```powershell
uv --version
where.exe uv
```

Ako `uv.exe` završi negdje drugdje (npr. `%USERPROFILE%\AppData\Local\...`), prepiši `command` polja u `mcp.json`.

**2. Kopiraj projekt na Windows.** Detaljan popis u sekciji [Što kopirati](#sto-kopirati) ispod. Kratko: 3 Python skripte + sandbox folder na `C:\LMStudio\`.

**3. Postavi `mcp.json`.**

Kopiraj ga u:

```text
C:\Users\<username>\.lmstudio\mcp.json
```

Ako folder `.lmstudio` ne postoji, LM Studio ga napravi pri prvom pokretanju.

**4. Pokreni LM Studio i provjeri.**
U LM Studio UI → tab gdje su MCP serveri → trebaju se pojaviti `lm-fs`, `lm-web`, `lm-xlsx`. Prvi run će biti spor — `uv` povlači dependency-je u cache.

---

## Što kopirati

### Obavezno (bez ovoga MCP ne radi)

Iz Linux projekta `LM STUDIO/` na Windows `C:\LMStudio\`:

| Što                    | Gdje na Windowsu                       | Zašto                                       |
|------------------------|----------------------------------------|---------------------------------------------|
| `server.py`            | `C:\LMStudio\server.py`                | `lm-fs` MCP — file/projekt operacije        |
| `web_server.py`        | `C:\LMStudio\web_server.py`            | `lm-web` MCP — fetch/search                 |
| `xlsx_server.py`       | `C:\LMStudio\xlsx_server.py`           | `lm-xlsx` MCP — Excel/CSV inspekcija        |
| `lm-studio-sandbox/`   | `C:\LMStudio\lm-studio-sandbox\`       | Root za sve MCP file operacije              |

I MCP konfiguracija (zaseban path, ne ide u projekt folder):

| Što                              | Gdje na Windowsu                                  |
|----------------------------------|---------------------------------------------------|
| `docs/windows/mcp.json`          | `C:\Users\<username>\.lmstudio\mcp.json`          |

### Korisno (preporučeno ali ne obavezno)

| Što              | Gdje                          | Kad treba                                       |
|------------------|-------------------------------|-------------------------------------------------|
| `tests/`         | `C:\LMStudio\tests\`          | Ako želiš pokretati pytest na Windowsu          |
| `docs/`          | `C:\LMStudio\docs\`           | Spec/plan dokumenti za daljnji razvoj           |
| `.git/`          | `C:\LMStudio\.git\`           | Ako želiš `git pull` za update-e (preporučeno)  |

### NE kopiraj (Linux smeće ili autogenerirano)

- `LM-Studio-0.4.12-1-x64.deb` — Linux installer, na Windowsu beskoristan. Skini Windows verziju s lmstudio.ai.
- `__pycache__/` (sve, uključujući one u sandboxu i tests) — Python bytecode cache, regenerira se.
- `.pytest_cache/` — regenerira se.
- `.web_cache/` — regenerira se.
- `lm-studio-sandbox/venv/` — Linux Python venv, ne radi na Windowsu. Ako trebaš venv unutar sandboxa, napravi ga svježi (`python -m venv venv`).
- `lm-studio-sandbox/__pycache__/`, `lm-studio-sandbox/.web_cache/`, `lm-studio-sandbox/.sisyphus/` — autogenerirano, preskoči.
- `run_tests.sh` — bash skripta. Na Windowsu pokreni testove direktno: `uv run --script xlsx_server.py` nije test command — koristi `pytest tests\` iz aktivnog venv-a, ili napravi `run_tests.bat`.
- `modeli/` — prazan folder kod tebe, nema potrebe.

### Što sa sandbox sadržajem

Tvoj `lm-studio-sandbox/` ima HTML/CSV/docx fajlove iz prethodnih sessiona (aluminum, warehouse_ui, tekstica, itd.). To je **tvoj** content — kopiraj ako ga želiš zadržati, ili kreni svjež s praznim sandboxom. Bitno je samo da folder postoji prije nego LM Studio krene MCP servere.

---

## LM Studio settings i modeli (zasebno od MCP)

Tvoji LM Studio modeli i postavke (theme, prompt template-i, hotkeys) **nisu** dio ovog projekta — žive u `~/.lmstudio/` na Linuxu i u `C:\Users\<username>\.lmstudio\` na Windowsu. Windows verzija LM Studija ih ne migrira automatski. Ako želiš zadržati:

- **Modeli (`.gguf` fileovi):** kopiraj `~/.lmstudio/models/` na `C:\Users\<username>\.lmstudio\models\` — LM Studio ih sam pokupi pri pokretanju.
- **Settings:** može se kopirati `~/.lmstudio/settings.json`, ali sigurnije je pustiti Windows verziju da napravi svoje defaultove i ručno podesiti što ti treba.

---

## Što je drugačije od Linux verzije

- **Putanje:** sve apsolutne, Windows-style.
- **`SEARXNG_URL` maknuto:** na Linuxu je bio `http://127.0.0.1:8080`. Ako na Windowsu nemaš pokrenut SearXNG, ostavi tako (server će fallback-ati preko `LM_WEB_BACKEND=auto`). Ako ga imaš (npr. Docker Desktop), dodaj natrag u `lm-web.env`:

  ```json
  "SEARXNG_URL": "http://127.0.0.1:8080"
  ```

- **`lm-xlsx` dodan:** na Linuxu nije bio registriran. Pokriva `xlsx_overview` i `xlsx_read_rows` toolove iz `xlsx_server.py`. Prvi run povlači `pandas` + `openpyxl` + `xlrd` + `rapidfuzz` — može potrajati par minuta.

---

## Excel feature status

`xlsx_server.py` je u aktivnom razvoju (vidi spec u `docs/superpowers/specs/2026-04-27-xlsx-mcp-design.md`). Trenutno funkcionalni toolovi:

- `xlsx_overview(path, sheet=None)` — pregled fajla, sheet liste, dimenzije, tipovi kolona, prvih i zadnjih 5 redova.
- `xlsx_read_rows(path, start, count=50, sheet=None)` — slice redova, hard cap 1000.

Format `xlsx`/`xls`/`csv` se auto-detektira po ekstenziji. CSV encoding fallback: `utf-8` → `cp1250` → `latin-1`. Sve unutar `LM_MCP_ROOT` sandboxa — pokušaji izlaska iz sandboxa rezultiraju greškom.

Kad se dodaju novi toolovi (npr. fuzzy search) ne treba mijenjati `mcp.json` — samo `git pull` na Windows kopiji projekta i restart LM Studija.

---

## Troubleshooting

- **"command not found: uv":** `uv.exe` nije u path-u koji `mcp.json` kaže. `where.exe uv` pa upiši puni path.
- **"LM_MCP_ROOT is not a directory":** sandbox folder ne postoji ili je u drugom folderu — napravi `C:\LMStudio\lm-studio-sandbox\`.
- **Spor prvi start:** normalno, `uv` cache-a deps po `--script`-u; drugi run je instant.
- **`lm-xlsx` server pada:** najčešće `xlrd` ili `openpyxl` install — provjeri da imaš net konekciju pri prvom run-u.
