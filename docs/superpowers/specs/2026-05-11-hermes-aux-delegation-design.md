# Hermes — lokalna delegacija na 2 mala llama-server endpointa

**Datum:** 2026-05-11
**Status:** Design — čeka odobrenje korisnika prije implementacije

## 1. Cilj

Konfigurirati Hermes agent framework tako da svoje **automatske auxiliary pozive** (kompresija konteksta, vision, web ekstrakcija, session search, naslovi, curator) i **eksplicitnu delegaciju** (`delegate_task` tool, plus 3 nova MCP alata) rutira na **dva mala lokalna llama-server endpointa**, umjesto na cloud (OpenRouter/Nous/Gemini).

Glavni razlozi po prioritetu:

1. **Brzina/specijalizacija** — mali modeli daju brže odgovore za visokofrekventne sporedne zadatke.
2. **Paralelizam** — `session_search` traži do 3 konkurentne sumarizacije; tekst endpoint je spreman s `--parallel 3`.
3. **Šteđenje glavnog konteksta** — orchestrator (35B) se ne troši na sumarizacije i ekstrakcije.
4. **Bonus: privatnost** — screenshotovi, lokalni dokumenti, CSV-i ne odlaze u cloud.

Sve stateless po dizajnu: svaki poziv ide kroz OpenAI-compatible HTTP API; nijedan worker ne drži persistentnu sesiju.

## 2. Trenutno stanje (potvrđeno provjerom)

### Hardver
- **AMD MI50 (gfx906, 32 GB HBM2)** — vidi se preko ROCm kao GPU index 0.
- **NVIDIA RTX 5070 Ti (16 GB)** — vidi se preko CUDA kao GPU index 0.
- Driver stackovi su odvojeni; nikakvo miješanje `CUDA_VISIBLE_DEVICES`/`HIP_VISIBLE_DEVICES` nije potrebno.

### Pokrenuti procesi (snapshot 2026-05-11)
- **Port 8000** — Docker container kao root, `llama-server` s `Qwen3.6-35B-A3B-Q4_K_M.gguf`, `--ctx-size 122880`, `-ngl 999`, `--no-mmap`. Hermesov glavni model. ROCm build (gfx906).
- **Port 8089-8092** — Četiri FastMCP servera (`lm-fs`, `lm-web`, `lm-xlsx`, `lm-pdf`) pokretana iz `start-mcp-http.sh`.
- **Port 8080** — SearXNG (koristi `lm-web`).

### llama.cpp binarji (na disku)
- `~/llama/latest/build/bin/llama-server` — CUDA, za RTX 5070 Ti.
- `~/llama/amd-gfx906/build/bin/llama-server` — ROCm/gfx906, za MI50.
- Plus ostali ROCm/CUDA buildovi.

### Modeli (`~/.../lmstudio-community/`)
- `Qwen3.6-35B-A3B-GGUF/` (Q4_K_M + mmproj) — orkestrator.
- `Qwen3.5-9B-GGUF/` (Q4_K_M, Q8_0, mmproj) — kandidat za tekstualni aux.
- `gemma-4-E4B-it-GGUF/` (Q4_K_M + mmproj) — kandidat za vision aux.
- `Qwen3.6-27B-GGUF/`, `gemma-4-26B-A4B-it-GGUF/`, `gpt-oss-20b-GGUF/`, `gemma-4-E2B-it-GGUF/` — drugi modeli, nisu dio dizajna ali rezerve za eventualne swap-ove.

### Hermes framework
- Instaliran u `~/.hermes/hermes-agent/`, izvršiv kao `hermes` (`~/.local/bin/hermes` → venv).
- **Auxiliary mehanizam** (`agent/auxiliary_client.py`): 6 prepoznatih task slotova.
- **`delegate_task` tool** (`tools/delegate_tool.py`): explicit subagent spawning s konfigurabilnim model/provider routingom preko `delegation.{provider,model,base_url}`.

## 3. Topologija (cilj)

```
            ┌──────────────────────────────────────────────┐
            │  Hermes orkestrator                          │
            │  main model: http://127.0.0.1:8000           │
            └──┬───────────────────┬───────────────────────┘
               │ auxiliary client  │ MCP tool calls
               │ (transparent)     │ (explicit)
   ┌───────────▼──────────┐  ┌────▼────────────────────────┐
   │  http://127.0.0.1:8093/v1   │  http://127.0.0.1:8095/mcp │
   │  Qwen3.5-9B Q4       │  │  lm-delegate MCP             │
   │  --parallel 3        │  │  • quick_classify            │
   │                      │  │  • extract_json              │
   │  Tasks:              │  │  • summarize_chunk           │
   │  • compression       │  └────┬─────────────────────────┘
   │  • web_extract       │       │ proxy → 8093/v1
   │  • session_search    │◄──────┘
   │  • title_generation  │
   │  • curator           │
   │  • delegate_task ch. │
   └──────────────────────┘
   ┌──────────────────────┐
   │  http://127.0.0.1:8094/v1   │◄─── auxiliary.vision
   │  gemma-4-E4B Q4 +    │
   │  mmproj-gemma-4-E4B  │
   │  --parallel 1        │
   └──────────────────────┘

   GPU: MI50 (gfx906)        → 8000 (Docker, ROCm build)
   GPU: RTX 5070 Ti          → 8093, 8094 (CUDA build)
   Host Python procesi       → 8089-8092 (postojeći MCP), 8095 (lm-delegate)
```

## 4. Što Hermes već koristi — pokriveni izlazi

### 4.1 Auxiliary slotovi (transparentni, automatski)

| # | Task slot | Što radi | Konfiguracijska putanja u `~/.hermes/config.yaml` |
|---|-----------|----------|---------------------------------------------------|
| 1 | `compression` | Sumira sredinu razgovora kad se kontekst približi limitu; štiti glavu/rep. Najkritičniji po kvaliteti. | `auxiliary.compression.*` |
| 2 | `vision` | OCR + opis slika: `vision_analyze` tool, browser screenshots, PDF page renderi. Treba mmproj. | `auxiliary.vision.*` |
| 3 | `web_extract` | Sumira/ekstrahira sadržaj nakon dohvata browser/HTTP alatom. | `auxiliary.web_extract.*` |
| 4 | `session_search` | FTS5 search po SQLite past sesijama → fan-out paralelnih sumarizacija (`max_concurrency` default 3). | `auxiliary.session_search.*` |
| 5 | `title_generation` | Kratak naslov (3-7 riječi) nakon prve izmjene. Primarno gađa main model; aux je fallback. | `auxiliary.title_generation.*` |
| 6 | `curator` | Pozadinski forkan AIAgent — idle-time skill maintenance (pin/archive/consolidate). Cijeli mini agent. | `auxiliary.curator.*` |

### 4.2 Eksplicitna delegacija — `delegate_task` (već postoji)

`tools/delegate_tool.py` spawna child AIAgent s:
- Svježim razgovorom (no parent history).
- Vlastitim task_id, terminal session, file ops cacheom.
- Restriktivnim toolsetom (konfigurabilno; trajno blokirano: `delegate_task`, `clarify`, `memory`, `send_message`, `execute_code`).
- Modelom konfiguriranim preko `delegation.{provider,model,base_url}` — može biti drugačiji od parent modela.
- Paralelizmom: `delegation.max_concurrent_children` (default 3).

Roditelj vidi samo poziv i finalni summary; nikad intermediate steps.

### 4.3 Što NIJE pokriveno auxiliary mehanizmom (svjesno izostavljeno)
- **Memory pruning** (Hermes MEMORY.md/USER.md konsolidacija) — koristi main model. Patch koda izvan scope-a ovog dizajna.
- **`skills_hub`, `mcp`** task slotovi — interni, rijetko konfigurabilni; pustiti na `provider: auto` (fallback chain).

## 5. Što dodajemo — `lm-delegate` MCP server

Tri tanka MCP alata za lightweight one-shot delegaciju. Razlika prema `delegate_task`: **bez AIAgent loop-a**, jedan HTTP poziv → odgovor. Pravo mjesto za mehanički rad gdje pun agent ima preveliki overhead.

### 5.1 Tools

#### `quick_classify(text, categories) -> str`
Jedna kategorija iz zadane liste. Temperature 0, `max_tokens=20`. Vraća ime kategorije ili fallback `"ostalo"` ako model vrati nešto izvan liste.

#### `extract_json(text, schema) -> dict`
Strukturirana ekstrakcija prema JSON Schemi. Koristi `response_format={"type": "json_object"}` (llama.cpp podržava grammar constraint). Vraća parsiran JSON.

#### `summarize_chunk(text, focus="", max_words=200) -> str`
Sažetak teksta s opcionalnim usmjerenjem (npr. `focus="cijene"`). Temperature 0.2, `max_tokens=max_words*2`.

### 5.2 Implementacijski obrazac

Slijedi postojeći FastMCP dual-mode pattern (`server.py`, `web_server.py`, `xlsx_server.py`, `pdf_server.py` u root `LM STUDIO/`):
- Datoteka: `LM STUDIO/delegate_server.py`.
- Stdio mode by default; HTTP mode kad je `MCP_TRANSPORT=http`.
- OpenAI klijent inicijaliziran prema `LM_DELEGATE_BACKEND_URL` env var (default `http://127.0.0.1:8093/v1`) i `LM_DELEGATE_MODEL` (default `qwen3.5-9b`).
- Bez state-a između poziva.

### 5.3 Zašto MCP (ne samo `delegate_task`)

| Pristup | Kad ima smisla | Trošak po pozivu |
|---------|----------------|------------------|
| **`delegate_task`** | Multi-step zadatak gdje child treba tool access (file IO, exec, web). | Skupo: pun AIAgent loop + system prompt + iteracije. 1-5s overhead bez stvarnog rada. |
| **`lm-delegate` MCP** | Već imamo tekst u kontekstu; treba samo transformacija. | Jeftino: jedan HTTP poziv, bez agent loop-a. ~200ms. |

## 6. Modeli, portovi, llama-server flagovi

### 6.1 Sažetak izbora modela

| Uloga | Model | Quant | Veličina | Razlog |
|-------|-------|-------|----------|--------|
| Orkestrator | `Qwen3.6-35B-A3B` | Q4_K_M | ~22 GB | Postojeći, neizmijenjen. |
| Text aux | `Qwen3.5-9B` | Q4_K_M | ~5.5 GB | Isti family kao orkestrator → konzistentno formatiranje summary-ja koji se vraćaju u glavni kontekst. |
| Vision aux | `gemma-4-E4B-it` | Q4_K_M | ~3.5 GB + 0.6 GB mmproj | Mali, brz; dovoljan za screenshot OCR i opis slika. Lako swap na Qwen3.5-9B s mmproj-om ako kvaliteta podbaci (mitigacija u §10). |

### 6.2 Portovi (kompletni plan)

```
8000   main 35B Docker llama-server (MI50)         [POSTOJEĆI]
8080   SearXNG                                     [POSTOJEĆI]
8089   lm-fs MCP                                   [POSTOJEĆI]
8090   lm-web MCP                                  [POSTOJEĆI]
8091   lm-xlsx MCP                                 [POSTOJEĆI]
8092   lm-pdf MCP                                  [POSTOJEĆI]
8093   text aux llama-server (Qwen3.5-9B)          [NOVI]
8094   vision aux llama-server (gemma-4-E4B)       [NOVI]
8095   lm-delegate MCP                             [NOVI]
```

### 6.3 llama-server flagovi

**Text aux (port 8093):**
```bash
~/llama/latest/build/bin/llama-server \
  --model "$MODEL_DIR/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf" \
  --alias "qwen3.5-9b" \
  --host 127.0.0.1 --port 8093 \
  --n-gpu-layers 99 \
  --ctx-size 8192 \
  --parallel 3 \
  --flash-attn on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --jinja
```

**Vision aux (port 8094):**
```bash
~/llama/latest/build/bin/llama-server \
  --model "$MODEL_DIR/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf" \
  --alias "gemma-4-e4b-it" \
  --mmproj "$MODEL_DIR/gemma-4-E4B-it-GGUF/mmproj-gemma-4-E4B-it-BF16.gguf" \
  --host 127.0.0.1 --port 8094 \
  --n-gpu-layers 99 \
  --ctx-size 8192 \
  --parallel 1 \
  --flash-attn on \
  --jinja
```

`--alias` osigurava da `model` polje u OpenAI API odgovorima točno odgovara onome što je upisano u `~/.hermes/config.yaml` (§7.1). Bez `--alias` llama-server vraća GGUF filename kao model id, pa bi config morao biti `model: "Qwen3.5-9B-Q4_K_M.gguf"` što je manje čitljivo i lomljivije kod swap-a kvanta.

### 6.4 VRAM proračun (RTX 5070 Ti, 16 GB)

| Komponenta | Memorija |
|------------|----------|
| Text 9B Q4 weights | 5.5 GB |
| Text KV cache, 3 slots × 8k ctx, Q8_0 | 1.8 GB |
| Text compute buffer | 0.5 GB |
| Vision 4B Q4 weights | 2.5 GB |
| Vision mmproj BF16 | 0.6 GB |
| Vision KV cache, 1 slot × 8k ctx | 0.5 GB |
| Vision compute buffer | 0.5 GB |
| **Ukupno** | **~12 GB** |
| **Headroom** | **~4 GB** |

## 7. Konfiguracija

### 7.1 `~/.hermes/config.yaml`

Sve auxiliary slotove + delegation block:

```yaml
auxiliary:
  compression:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"
    timeout: 60

  web_extract:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"
    timeout: 60

  session_search:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"
    timeout: 60
    max_concurrency: 3        # = --parallel 3 na llama-serveru

  title_generation:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"

  curator:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"

  vision:
    base_url: "http://127.0.0.1:8094/v1"
    api_key: "no-key-required"
    model: "gemma-4-e4b-it"
    timeout: 60
    download_timeout: 30

delegation:
  provider: "custom"
  base_url: "http://127.0.0.1:8093/v1"
  api_key: "no-key-required"
  model: "qwen3.5-9b"
  max_concurrent_children: 2   # ostaviti 1 slot tekst endpointu za auxiliary
  child_timeout_seconds: 300
  subagent_auto_approve: false # safe default

mcp_servers:
  lm-delegate:
    url: "http://127.0.0.1:8095/mcp"
```

### 7.2 LM Studio mirror (frozen kopija)

Sukladno postojećoj konvenciji "frozen copies, not uninstall":
- Kopirati `delegate_server.py` u `LM STUDIO/lm-studio-mcp/delegate_server.py`.
- Dodati ulaz u `~/.lmstudio/mcp.json` (stdio mode, ne HTTP) → LM Studio može pozvati iste tri funkcije ako se koristi LM Studio frontend.

## 8. Lifecycle (start/stop)

### 8.1 Novi `start-aux-llama.sh`

Pokreće dva mala llama-servera u pozadini. Slijedi obrazac `start-mcp-http.sh`:
- PID datoteke u `~/.local/state/llama-mcp/aux-text.pid`, `aux-vision.pid`.
- Logovi u `~/.local/state/llama-mcp/aux-text.log`, `aux-vision.log`.
- Provjera da nije već pokrenut.
- Ne pokreće Docker 35B na 8000 — to ostaje odvojeno (kako jest sada).

### 8.2 Proširenje `start-mcp-http.sh`

Dodati `lm-delegate` na 8095 kao 5. MCP server:
```bash
start_one lm-delegate 8095 "$PROJECT_DIR/delegate_server.py" \
  LM_DELEGATE_BACKEND_URL=http://127.0.0.1:8093/v1 \
  LM_DELEGATE_MODEL=qwen3.5-9b
```

### 8.3 `stop-aux-llama.sh`

Pandant `stop-mcp-http.sh`, čita PID files, šalje SIGTERM, čeka, eventual SIGKILL.

### 8.4 Redoslijed pokretanja

Ovisnosti su tanke; redoslijed bitan samo zato što `lm-delegate` MCP traži text aux endpoint:

```
1. Docker 35B (port 8000)                  [postojeći ručni postupak ili LM Studio]
2. ./start-aux-llama.sh                    [pokreće 8093 + 8094]
3. ./start-mcp-http.sh                     [pokreće 8089-8092 + 8095]
4. hermes  / LM Studio                     [klijenti]
```

Systemd unit za auto-restart ostaje izvan scope-a ove iteracije (planirano za sljedeću iteraciju ako kvaliteta zadovolji).

## 9. Validacija kvalitete (per-task acceptance kriteriji)

Auxiliary mehanizam je u Hermesu eksplicitno označen kao **EXPERIMENTAL** za non-cloud providere. Stoga svaki slot treba minimalnu provjeru prije nego se postavi kao trajna ruta.

| Slot | Test scenario | Acceptance kriterij |
|------|---------------|---------------------|
| `compression` | Sesija od ~30 user/assistant turna na CSV analizi; pratiti je li post-compaction summary zadržao ključne reference (file paths, brojeve narudžbi). | Glavni model nakon kompresije može odgovoriti na "koje smo narudžbe pregledali" bez gubitka. |
| `web_extract` | Dohvati 3 različite web stranice (HR vijest, GitHub README, e-trgovina). | Sažetak sadrži glavnu tezu + ključne brojke/citate, ne haluci. |
| `session_search` | Search query koji match-a 3 stare sesije. | Vrate se 3 različita summary-ja, nijedan nije prazan / placeholder. |
| `title_generation` | Pokreni 5 novih sesija s različitim temama. | Naslovi su 3-7 riječi, opisni, bez navodnika/točki na kraju. |
| `vision` | Screenshot Hermes WebUI + slika `aluminum_analysis.html` chart. | OCR teksta tačan; opis grafa identificira osi i trend. |
| `curator` | Pričekati idle interval; pratiti `~/.hermes/.curator_state`. | Aktivira se, ne diže iznimke, ne uništi skill datoteke. |
| `quick_classify` | Klasificirati 20 redova iz `ExportOrdersSve1.csv` u {aluminij, staklo, oprema, ostalo}. | ≥90% poklapanja s ručno označenim ground-truth (uzorak od 20). |
| `extract_json` | Ekstrahirati `{datum, klijent, suma}` iz 5 stavki `VTR_Dokumentacija_Analiza.txt`. | Sve 5 vraćaju valid JSON; ≥4/5 ima točne vrijednosti. |
| `summarize_chunk` | Sažeti `aluminum_prices_2024.csv` s `focus="trend cijena"`. | Sažetak spominje smjer trenda + barem 2 konkretna broja. |

Ako bilo koji slot ne prođe, mitigacija per §10.

## 10. Rizici i mitigacije

| Rizik | Vjerojatnost | Mitigacija |
|-------|--------------|------------|
| Kompresija od 9B-a gubi važne reference → glavni 35B-a zbunjuje | Srednja | (a) prebaciti `compression` natrag na cloud (Gemini Flash); (b) ili swap na Qwen3.6-27B na MI50 (dijeliti VRAM s 35B-om — provjeriti). Drugi auxiliary slotovi ostaju lokalni. |
| Gemma-4-E4B vision premala za realnu kvalitetu | Srednja | Swap na Qwen3.5-9B s mmproj-om (~7 GB) na portu 8094 — KV-headroom na RTX 5070 Ti tijesan ali izvediv (smanjiti `--parallel` na tekstu na 2). |
| Vision payload format mismatch (Hermes ↔ llama.cpp VL) | Niska-srednja | Gemma-4 i Qwen-VL slijede OpenAI vision payload konvenciju u llama.cpp; ako se pojavi problem, eksplicitno postaviti `auxiliary.vision.provider: "openrouter"` (cloud fallback) dok se ne razriješi. |
| Tekst endpoint OOM s 3 paralelna slota | Niska | KV proračun (1.8 GB) ima ~4 GB headroom; ako se ipak digne, smanjiti `--ctx-size` na 6144 ili `--parallel 2`. |
| Worker padne (OOM / crash) bez fallback-a (config je `provider: custom`, nema auto-chain) | Srednja | Sistemd unit s `Restart=on-failure` u sljedećoj iteraciji; do tada — ručni restart preko `stop+start-aux-llama.sh`. |
| `delegate_task` child traži toolove koje mali 9B model ne koristi efikasno (npr. složen multi-step kod) | Srednja | Postaviti `delegation.max_iterations` nisko (npr. 30) i ostaviti opciju per-call override modela natrag na main (`delegate_task(model="...")` argument). |
| MCP `extract_json` model ne poštuje JSON schemu | Niska | `response_format={"type":"json_object"}` + retry s eksplicitnijim sistem promptom; ako i drugi pokušaj ne uspije, vratiti raw string i greški. |
| Docker 35B (port 8000) zauzme port koji konfliktira s budućim promjenama | Niska | Provjeriti `docker ps` prije pokretanja drugih servisa; portovi 8093+ su tako rezervirani da ne dolaze u doticaj. |

## 11. Out of scope (ne radi se ovaj put)

- Systemd / autostart za male endpointe — sljedeća iteracija.
- Reverse proxy za load balancing između dva endpointa — bez koristi (auxiliary slotovi su per-task pinned, ne benefitira od round-robina).
- HTTP load balancer ispred više identičnih 9B instanci — moguća buduća optimizacija ako `--parallel 3` postane usko grlo.
- Patch Hermes koda za delegaciju Memory pruning-a na auxiliary — izvan scope-a.
- Sub-Hermes (`batch_runner.py`) integracija — ostaje na ručnom pozivu, ne ulazi u rutinski tok.
- Zamjena LM Studio frontend-a — ostaje paralelno (frozen kopija `delegate_server.py` u `lm-studio-mcp/`).

## 12. Build sequence (od čega počinjemo)

Faze, redoslijedom; svaka faza završava acceptance kriterijem.

1. **Faza 1 — llama-server endpointi**
   - Napisati `start-aux-llama.sh` + `stop-aux-llama.sh`.
   - Pokrenuti, provjeriti `curl http://127.0.0.1:8093/v1/models` i `:8094/v1/models`.
   - Acceptance: oba endpointa odgovaraju, VRAM trošak unutar očekivanog (~12 GB).

2. **Faza 2 — `lm-delegate` MCP server**
   - Napisati `LM STUDIO/delegate_server.py` (3 tools, FastMCP dual-mode).
   - Dodati u `start-mcp-http.sh`.
   - Acceptance: `quick_classify`, `extract_json`, `summarize_chunk` rade lokalno (test skripta s 3 sample inputa).

3. **Faza 3 — Hermes config**
   - Backup `~/.hermes/config.yaml`.
   - Dodati `auxiliary.*`, `delegation.*`, `mcp_servers.lm-delegate` blokove.
   - Restart Hermesa.
   - Acceptance: `hermes` proradi, `/sessions` (session_search) i jedan auxiliary call rade bez pada.

4. **Faza 4 — kvaliteta**
   - Proći acceptance kriterije iz §9 jedan po jedan.
   - Za svaki prolaz/pad odluka po §10 mitigaciji.

5. **Faza 5 — LM Studio mirror**
   - Kopirati `delegate_server.py` u `lm-studio-mcp/`.
   - Update `~/.lmstudio/mcp.json`.
   - Acceptance: LM Studio frontend može pozvati `quick_classify` iz chata.
