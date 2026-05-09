# pdf_inspect_layout drawing clustering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pdf_inspect_layout` emit a compact, signal-rich layout listing by clustering raw PyMuPDF drawing paths into 5-15 macro regions per page, with the existing verbose dump available behind an opt-in flag.

**Architecture:** Add a `_cluster_drawings` helper to `pdf_server.py` that uses spatial-hash union-find to merge overlapping/nearby drawing rects, then filter zero-dim and small-area clusters and cap to top N by area. Modify `pdf_inspect_layout` to use the helper by default; add `verbose=True` short-circuit. Mirror every change to `lm-studio-mcp/pdf_server.py` (frozen-copy fork).

**Tech Stack:** Python 3.10+, PyMuPDF (`fitz`), pytest, FastMCP. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-05-09-pdf-inspect-layout-clustering-design.md](../specs/2026-05-09-pdf-inspect-layout-clustering-design.md)

---

## File Structure

- **Modify** `pdf_server.py` — add `_cluster_drawings` helper near line 187 (next to other helpers); modify `pdf_inspect_layout` body at line 836-905 to branch on `verbose` and use clusters when compact.
- **Modify** `lm-studio-mcp/pdf_server.py` — apply identical changes (frozen-copy fork; only `__main__` block differs from canonical).
- **Modify** `tests/test_pdf_server.py` — add 10 new tests covering clustering, filtering, capping, end-to-end behavior, validation, and performance.
- **Modify** `docs/superpowers/specs/2026-05-07-pdf-mcp-design.md` — add a reference at §6.8 pointing to the new design spec.

---

## Task 1: `_cluster_drawings` helper — overlap merging and disjoint separation

**Files:**
- Modify: `pdf_server.py` (add helper after `_to_tsv` near line 215)
- Test: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def _make_drawing(x0, y0, x1, y1, items_count=1):
    """Test fixture: build a drawing dict shaped like p.get_drawings() output."""
    import fitz
    return {"rect": fitz.Rect(x0, y0, x1, y1), "items": [None] * items_count}


def test_cluster_drawings_overlap_merges():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    a = _make_drawing(10, 10, 50, 50, items_count=3)
    b = _make_drawing(40, 40, 90, 90, items_count=2)  # overlaps a
    clusters = pdf_server._cluster_drawings(
        [a, b], cluster_tolerance=0, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 1
    c = clusters[0]
    assert c["rect"] == (10, 10, 90, 90)
    assert c["n_drawings"] == 2
    assert c["total_shapes"] == 5


def test_cluster_drawings_disjoint_separate():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    a = _make_drawing(10, 10, 50, 50)
    b = _make_drawing(500, 500, 600, 600)  # far away
    clusters = pdf_server._cluster_drawings(
        [a, b], cluster_tolerance=8, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py::test_cluster_drawings_overlap_merges tests/test_pdf_server.py::test_cluster_drawings_disjoint_separate -v`
Expected: FAIL with `AttributeError: module 'pdf_server' has no attribute '_cluster_drawings'`

- [ ] **Step 3: Write minimal implementation**

In `pdf_server.py`, after the `_to_tsv` function (around line 215), add:

```python
def _cluster_drawings(
    drawings: list[dict],
    cluster_tolerance: int,
    min_area: int,
    max_drawings: int,
) -> list[dict]:
    """Cluster drawing dicts (each with `rect` and `items`) into macro regions.

    Two drawings cluster together iff their rects overlap when each is
    inflated by `cluster_tolerance` on every side. Filters degenerate rects
    (zero width or height) before clustering and small-area clusters after.
    Returns clusters sorted by union-bbox area descending, capped at
    `max_drawings`.

    Each output dict: {"rect": (x0,y0,x1,y1) tuple in PDF points,
                       "n_drawings": int, "total_shapes": int}.
    """
    rects = []
    shapes_per = []
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        x0, y0, x1, y1 = float(r.x0), float(r.y0), float(r.x1), float(r.y1)
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            continue
        rects.append((x0, y0, x1, y1))
        shapes_per.append(len(d.get("items") or []))
    n = len(rects)
    if n == 0:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    tol = cluster_tolerance
    for i in range(n):
        ix0, iy0, ix1, iy1 = rects[i]
        for j in range(i + 1, n):
            jx0, jy0, jx1, jy1 = rects[j]
            if ix0 - tol <= jx1 and jx0 <= ix1 + tol and \
               iy0 - tol <= jy1 and jy0 <= iy1 + tol:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    clusters = []
    for members in groups.values():
        x0 = min(rects[i][0] for i in members)
        y0 = min(rects[i][1] for i in members)
        x1 = max(rects[i][2] for i in members)
        y1 = max(rects[i][3] for i in members)
        area = (x1 - x0) * (y1 - y0)
        if area < min_area:
            continue
        clusters.append({
            "rect": (x0, y0, x1, y1),
            "n_drawings": len(members),
            "total_shapes": sum(shapes_per[i] for i in members),
            "_area": area,
        })

    clusters.sort(key=lambda c: c["_area"], reverse=True)
    clusters = clusters[:max_drawings]
    for c in clusters:
        del c["_area"]
    return clusters
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py::test_cluster_drawings_overlap_merges tests/test_pdf_server.py::test_cluster_drawings_disjoint_separate -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add _cluster_drawings helper with overlap merging

Naive O(n²) union-find pairwise overlap test. Spatial-hash optimization
follows in a separate task. Caps clusters at max_drawings sorted by area.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: tolerance-based merging

**Files:**
- Test: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_pdf_server.py`:

```python
def test_cluster_drawings_tolerance_merges():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    # Two rects 5 PDF points apart; with tolerance=8 they should merge.
    a = _make_drawing(10, 10, 50, 50)
    b = _make_drawing(55, 10, 90, 50)  # 5pt gap on x-axis
    clusters = pdf_server._cluster_drawings(
        [a, b], cluster_tolerance=8, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 1, f"expected merge with tolerance=8, got {clusters}"

    # Same rects with tolerance=0 must stay separate.
    clusters = pdf_server._cluster_drawings(
        [a, b], cluster_tolerance=0, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 2
```

- [ ] **Step 2: Run test to verify behavior**

Run: `./run_tests.sh tests/test_pdf_server.py::test_cluster_drawings_tolerance_merges -v`
Expected: PASS (the implementation from Task 1 already supports tolerance via `tol` in the overlap test).

If the test fails, check that the inequality in `_cluster_drawings` uses `<=` (inclusive) so a rect exactly `tolerance` away still merges.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pdf_server.py
git commit -m "test(pdf): cover cluster_tolerance gap-merging behavior

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: zero-dimension and below-min-area filtering

**Files:**
- Test: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_cluster_drawings_filters_zero_dim():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    # Width=0 (vertical line) and height=0 (horizontal line) — both useless
    # for cropping, must be dropped before clustering.
    horizontal_line = _make_drawing(10, 10, 50, 10)
    vertical_line = _make_drawing(10, 10, 10, 50)
    legit = _make_drawing(100, 100, 200, 200)
    clusters = pdf_server._cluster_drawings(
        [horizontal_line, vertical_line, legit],
        cluster_tolerance=0, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 1
    assert clusters[0]["rect"] == (100, 100, 200, 200)


def test_cluster_drawings_filters_below_min_area():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    tiny = _make_drawing(10, 10, 15, 15)        # 25 pt²
    medium = _make_drawing(100, 100, 200, 200)  # 10000 pt²
    clusters = pdf_server._cluster_drawings(
        [tiny, medium], cluster_tolerance=0, min_area=100, max_drawings=10,
    )
    assert len(clusters) == 1
    assert clusters[0]["rect"] == (100, 100, 200, 200)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py::test_cluster_drawings_filters_zero_dim tests/test_pdf_server.py::test_cluster_drawings_filters_below_min_area -v`
Expected: PASS (Task 1 implementation already handles both filters).

- [ ] **Step 3: Commit**

```bash
git add tests/test_pdf_server.py
git commit -m "test(pdf): cover zero-dim and min_area filtering in clusters

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: max_drawings cap with area-descending sort

**Files:**
- Test: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_pdf_server.py`:

```python
def test_cluster_drawings_caps_to_max_drawings():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    # 5 disjoint rects with monotonically increasing area; cap at 3 must
    # return the 3 largest.
    drawings = [
        _make_drawing(0, 0, 10, 10),       # area 100  (rank 5)
        _make_drawing(100, 0, 120, 20),    # area 400  (rank 4)
        _make_drawing(200, 0, 230, 30),    # area 900  (rank 3)
        _make_drawing(300, 0, 340, 40),    # area 1600 (rank 2)
        _make_drawing(400, 0, 450, 50),    # area 2500 (rank 1, biggest)
    ]
    clusters = pdf_server._cluster_drawings(
        drawings, cluster_tolerance=0, min_area=0, max_drawings=3,
    )
    assert len(clusters) == 3
    # Order must be biggest first.
    assert clusters[0]["rect"] == (400, 0, 450, 50)
    assert clusters[1]["rect"] == (300, 0, 340, 40)
    assert clusters[2]["rect"] == (200, 0, 230, 30)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `./run_tests.sh tests/test_pdf_server.py::test_cluster_drawings_caps_to_max_drawings -v`
Expected: PASS (Task 1 implementation already sorts and caps).

- [ ] **Step 3: Commit**

```bash
git add tests/test_pdf_server.py
git commit -m "test(pdf): cover max_drawings cap with area-descending order

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: spatial-hash optimization for large inputs

**Files:**
- Modify: `pdf_server.py` (replace pairwise loop in `_cluster_drawings`)
- Test: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing perf test**

Append to `tests/test_pdf_server.py`:

```python
def test_cluster_drawings_perf_14k():
    """15K random rects on a 2500x1750 px canvas must cluster in < 2s.
    Sanity ceiling for the worst observed page (page 5 of the architectural
    PDF: 14735 raw drawings)."""
    import importlib
    import random
    import time
    import pdf_server
    importlib.reload(pdf_server)
    rng = random.Random(0)
    drawings = []
    for _ in range(15000):
        x0 = rng.uniform(0, 2400)
        y0 = rng.uniform(0, 1650)
        w = rng.uniform(1, 100)
        h = rng.uniform(1, 100)
        drawings.append(_make_drawing(x0, y0, x0 + w, y0 + h))
    t0 = time.perf_counter()
    clusters = pdf_server._cluster_drawings(
        drawings, cluster_tolerance=8, min_area=100, max_drawings=20,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"clustering 15k rects took {elapsed:.2f}s (>2s ceiling)"
    # Sanity: should produce some clusters (most rects will overlap given density).
    assert len(clusters) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh tests/test_pdf_server.py::test_cluster_drawings_perf_14k -v`
Expected: FAIL — naive O(n²) on 15K is ~112M comparisons in pure Python, will exceed 2s (likely 8-15s).

- [ ] **Step 3: Replace pairwise loop with spatial hash**

In `pdf_server.py`, replace the `for i in range(n):` block inside `_cluster_drawings` with:

```python
    tol = cluster_tolerance
    # Spatial hash: bin rects by grid cell so we only test pairs that share a
    # cell. Cell size scales with tolerance; floor of 50pt keeps the bin
    # count modest on tiny-tolerance runs.
    cell = max(50.0, tol * 10.0) if tol > 0 else 50.0
    bins: dict[tuple[int, int], list[int]] = {}
    for i in range(n):
        x0, y0, x1, y1 = rects[i]
        cx0 = int((x0 - tol) // cell)
        cy0 = int((y0 - tol) // cell)
        cx1 = int((x1 + tol) // cell)
        cy1 = int((y1 + tol) // cell)
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                bins.setdefault((cx, cy), []).append(i)

    seen_pairs: set[tuple[int, int]] = set()
    for members in bins.values():
        m = len(members)
        for a in range(m):
            i = members[a]
            ix0, iy0, ix1, iy1 = rects[i]
            for b in range(a + 1, m):
                j = members[b]
                pair = (i, j) if i < j else (j, i)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                jx0, jy0, jx1, jy1 = rects[j]
                if ix0 - tol <= jx1 and jx0 <= ix1 + tol and \
                   iy0 - tol <= jy1 and jy0 <= iy1 + tol:
                    union(i, j)
```

- [ ] **Step 4: Run perf test + all earlier tests to verify**

Run: `./run_tests.sh tests/test_pdf_server.py -k "cluster_drawings" -v`
Expected: PASS (all 5 cluster tests including perf).

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "perf(pdf): use spatial-hash binning in _cluster_drawings

Replaces O(n²) pairwise loop with grid-binned candidate generation so
overlap tests stay local. Verified < 2s on 15K random rects (synthetic
ceiling matching the worst-case observed PDF page).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: wire `pdf_inspect_layout` to use clustering by default

**Files:**
- Modify: `pdf_server.py` lines 836-905
- Test: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing end-to-end test**

Append to `tests/test_pdf_server.py`:

```python
@pytest.fixture
def vector_drawing_pdf(sandbox):
    """A 1-page PDF with one big rectangle plus 5 dense groups of 12 small
    rectangles each. Within each group the rects are 5pt apart (well within
    the default cluster_tolerance=8) so they collapse into one cluster;
    groups are 100pt apart so they stay separate. Expected compact output:
    1 big + 5 group clusters = 6 drawing rows. Raw drawings: 61."""
    import fitz
    pdf_path = sandbox / "vector-drawing.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 in pt
    # Big rectangle filling most of the page — one obvious macro region.
    page.draw_rect(fitz.Rect(50, 50, 545, 600))
    # 5 packed groups in the lower portion, each 12 small rects.
    for group in range(5):
        base_x = 50 + group * 100  # groups 100pt apart (>> tolerance)
        base_y = 700
        for i in range(12):
            x = base_x + (i % 4) * 5  # 5pt spacing within group < tol=8
            y = base_y + (i // 4) * 5
            page.draw_rect(fitz.Rect(x, y, x + 4, y + 4))
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_pdf_inspect_layout_compact_default(vector_drawing_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_inspect_layout(vector_drawing_pdf.name, page=1, dpi=150)
    # Header line should mention drawing-cluster summary.
    assert "drawing cluster" in out, f"missing cluster header in: {out[:200]!r}"
    # Drawing rows should be far fewer than the 61 raw drawings.
    drawing_rows = [line for line in out.splitlines() if "\tdrawing\t" in line]
    assert len(drawing_rows) < 15, (
        f"compact mode emitted {len(drawing_rows)} drawing rows, expected <15"
    )
    # Hint format: "<n> drawings, <m> shapes".
    assert any(re.search(r"\d+ drawings, \d+ shapes", row) for row in drawing_rows), \
        f"no cluster hint found in: {drawing_rows!r}"
```

(Add `import re` at the top of the test file if not already present — check before editing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh tests/test_pdf_server.py::test_pdf_inspect_layout_compact_default -v`
Expected: FAIL — current `pdf_inspect_layout` emits one row per raw drawing and uses `"<n> shapes"` (without the `drawings,` prefix).

- [ ] **Step 3: Modify `pdf_inspect_layout` to use clustering**

In `pdf_server.py`, replace lines 836-905 (the entire `pdf_inspect_layout` function body) with:

```python
@mcp.tool()
def pdf_inspect_layout(
    path: str,
    page: int,
    dpi: int = _DPI_DEFAULT,
    cluster_tolerance: int = 8,
    min_area: int = 100,
    max_drawings: int = 20,
    verbose: bool = False,
) -> str:
    """List detectable regions on a PDF page with their bounding boxes.

    Returns TSV with columns: index, type, x0, y0, x1, y1, hint. type is one
    of 'text', 'image', 'drawing'. Bounding boxes are in pixels at the given
    DPI — same coordinate system pdf_extract_region expects, and matching the
    DPI you rendered the page at via pdf_render_page. Use this when you want
    to crop a known region (e.g. 'extract block 3') without eyeballing pixel
    coordinates from a render.

    By default, vector drawings are spatially clustered so a multi-path
    diagram surfaces as one row instead of hundreds. Tune via cluster_tolerance
    (PDF points), min_area (PDF points² floor for cluster bbox), and
    max_drawings (top-N cap). Pass verbose=True to skip clustering and emit
    one row per raw PyMuPDF drawing (subject to the 50KB TSV cap).
    """
    target = _open_target(path)
    parsed = _get_parsed(target)
    total = parsed["meta"]["page_count"]
    if not (1 <= page <= total):
        raise ValueError(f"page must be in range [1, {total}]")
    if not (_DPI_MIN <= dpi <= _DPI_MAX):
        raise ValueError(f"dpi must be between {_DPI_MIN} and {_DPI_MAX}")

    rows: list[list] = [["index", "type", "x0", "y0", "x1", "y1", "hint"]]
    idx = 0
    n_text = 0
    n_image = 0
    raw_drawing_count = 0
    with fitz.open(target) as doc:
        p = doc.load_page(page - 1)

        for x0, y0, x1, y1, content, _bno, btype in p.get_text("blocks") or []:
            kind = "text" if btype == 0 else "image"
            if kind == "text":
                hint = (content or "").strip().replace("\n", " ").replace("\t", " ")[:60]
                n_text += 1
            else:
                hint = ""
                n_image += 1
            px = _points_to_pixels((x0, y0, x1, y1), dpi)
            rows.append([idx, kind, *px, hint])
            idx += 1

        seen_image_rects: set[tuple] = set()
        for r in rows[1:]:
            if r[1] == "image":
                seen_image_rects.add(tuple(r[2:6]))
        for info in p.get_image_info(xrefs=True) or []:
            bbox_pt = info.get("bbox")
            if not bbox_pt:
                continue
            bbox_px = _points_to_pixels(bbox_pt, dpi)
            if bbox_px in seen_image_rects:
                continue
            w, h = info.get("width", 0), info.get("height", 0)
            rows.append([idx, "image", *bbox_px, f"{w}×{h}"])
            idx += 1
            n_image += 1

        raw = p.get_drawings() or []
        raw_drawing_count = len(raw)
        if verbose:
            for d in raw:
                rect = d.get("rect")
                if rect is None:
                    continue
                n_items = len(d.get("items") or [])
                rows.append([idx, "drawing", *_points_to_pixels(rect, dpi),
                             f"{n_items} shapes"])
                idx += 1
            n_drawing_rows = len(rows) - 1 - n_text - n_image
        else:
            clusters = _cluster_drawings(
                raw,
                cluster_tolerance=cluster_tolerance,
                min_area=min_area,
                max_drawings=max_drawings,
            )
            for c in clusters:
                rows.append([idx, "drawing",
                             *_points_to_pixels(c["rect"], dpi),
                             f"{c['n_drawings']} drawings, {c['total_shapes']} shapes"])
                idx += 1
            n_drawing_rows = len(clusters)

    if verbose:
        cluster_summary = f"{n_drawing_rows} drawing rows (verbose, no clustering)"
    else:
        cluster_summary = (
            f"{n_drawing_rows} drawing clusters (from {raw_drawing_count} raw drawings)"
        )
    header = [
        f"# layout for page {page} of {total}, bbox in pixels @ {dpi} dpi",
        f"# {n_text} text, {n_image} image, {cluster_summary}",
    ]
    if len(rows) == 1:
        header.append("# no regions detected on this page")
        return "\n".join(header)
    if not verbose and raw_drawing_count > 0 and n_drawing_rows == 0:
        header.append(
            "# all drawings filtered as noise "
            "(set verbose=True or lower min_area to see them)"
        )
    return _to_tsv(rows, header, max_chars=_TSV_MAX_CHARS)
```

- [ ] **Step 4: Run new + existing layout tests**

Run: `./run_tests.sh tests/test_pdf_server.py -k "inspect_layout or cluster_drawings" -v`
Expected: PASS for the new compact test and all existing `inspect_layout` tests (none of them asserted on raw drawing counts; if any do, see Task 7 for the verbose-mode fix path).

If an existing test breaks because it assumed one drawing per row, switch that test to call `verbose=True` (will be added in Task 7) or update its assertion.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): cluster drawings by default in pdf_inspect_layout

Compact output collapses thousands of raw PyMuPDF path entries into a
handful of macro regions (e.g. 14735 → ~10 on the worst observed page),
keeping the model under context budget without losing layout signal.
verbose=True wired in next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: verbose=True passthrough regression test

**Files:**
- Test: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_pdf_server.py`:

```python
def test_pdf_inspect_layout_verbose_keeps_old_format(vector_drawing_pdf):
    """verbose=True must skip clustering and emit one row per raw drawing
    with the old "<n> shapes" hint format. Regression for power users who
    rely on per-path detail."""
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_inspect_layout(
        vector_drawing_pdf.name, page=1, dpi=150, verbose=True,
    )
    drawing_rows = [line for line in out.splitlines() if "\tdrawing\t" in line]
    # Fixture has 1 big rect + 60 small lines = 61 raw drawings; verbose
    # should emit (close to) all of them, far more than compact mode.
    assert len(drawing_rows) >= 50, (
        f"verbose mode emitted only {len(drawing_rows)} drawings, "
        "expected ~61 raw entries"
    )
    # Old hint format: "<n> shapes" with no "drawings," prefix.
    for row in drawing_rows:
        assert re.search(r"\b\d+ shapes\b", row), f"missing shape count in {row!r}"
        assert "drawings," not in row, (
            f"verbose row has cluster-style hint: {row!r}"
        )
    # Header should call out verbose mode.
    assert "verbose" in out.splitlines()[1]
```

- [ ] **Step 2: Run test to verify it passes**

Run: `./run_tests.sh tests/test_pdf_server.py::test_pdf_inspect_layout_verbose_keeps_old_format -v`
Expected: PASS (Task 6 already wired the `verbose=True` branch).

- [ ] **Step 3: Commit**

```bash
git add tests/test_pdf_server.py
git commit -m "test(pdf): regression for verbose=True passthrough format

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: parameter validation

**Files:**
- Modify: `pdf_server.py` (validation block in `pdf_inspect_layout`)
- Test: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_pdf_inspect_layout_validates_new_params(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="cluster_tolerance"):
        pdf_server.pdf_inspect_layout(
            simple_text_pdf.name, page=1, cluster_tolerance=-1,
        )
    with pytest.raises(ValueError, match="min_area"):
        pdf_server.pdf_inspect_layout(
            simple_text_pdf.name, page=1, min_area=-1,
        )
    with pytest.raises(ValueError, match="max_drawings"):
        pdf_server.pdf_inspect_layout(
            simple_text_pdf.name, page=1, max_drawings=0,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py::test_pdf_inspect_layout_validates_new_params -v`
Expected: FAIL — no validation in place yet.

- [ ] **Step 3: Add validation in `pdf_inspect_layout`**

In `pdf_server.py`, immediately after the existing `dpi` validation in `pdf_inspect_layout`, insert:

```python
    if cluster_tolerance < 0:
        raise ValueError(f"cluster_tolerance must be >= 0, got {cluster_tolerance}")
    if min_area < 0:
        raise ValueError(f"min_area must be >= 0, got {min_area}")
    if max_drawings < 1:
        raise ValueError(f"max_drawings must be >= 1, got {max_drawings}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py::test_pdf_inspect_layout_validates_new_params -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): validate new pdf_inspect_layout cluster params

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: mirror to lm-studio-mcp/pdf_server.py

**Files:**
- Modify: `lm-studio-mcp/pdf_server.py`

- [ ] **Step 1: Confirm baseline mirror state**

Run: `diff pdf_server.py lm-studio-mcp/pdf_server.py`
Expected: only the `__main__` transport block at the very bottom should differ. If anything else is out of sync, stop and reconcile before continuing — that's a bug.

- [ ] **Step 2: Apply the same `_cluster_drawings` helper**

In `lm-studio-mcp/pdf_server.py`, copy the `_cluster_drawings` function from `pdf_server.py` (added in Tasks 1 + 5) verbatim into the same position (right after `_to_tsv`).

- [ ] **Step 3: Apply the same `pdf_inspect_layout` rewrite**

In `lm-studio-mcp/pdf_server.py`, replace the `pdf_inspect_layout` function body with the version from `pdf_server.py` (Tasks 6 + 8 combined — includes validation block).

- [ ] **Step 4: Verify diff is still only the `__main__` block**

Run: `diff pdf_server.py lm-studio-mcp/pdf_server.py`
Expected: same single-region diff at the bottom (`__main__` transport block) — nothing else.

- [ ] **Step 5: Run full test suite**

Run: `./run_tests.sh tests/test_pdf_server.py -v`
Expected: all tests pass (the test file uses the canonical `pdf_server.py`; mirror is verified by the `diff` above).

- [ ] **Step 6: Commit**

```bash
git add lm-studio-mcp/pdf_server.py
git commit -m "chore(pdf): mirror clustering changes to lm-studio-mcp fork

Per the frozen-copy convention: every change to pdf_server.py lands
identically in lm-studio-mcp/pdf_server.py. Only the __main__ transport
block remains as the intentional fork point.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: cross-reference the new design from the original spec

**Files:**
- Modify: `docs/superpowers/specs/2026-05-07-pdf-mcp-design.md`

- [ ] **Step 1: Read the existing §6.8 of the spec**

Open `docs/superpowers/specs/2026-05-07-pdf-mcp-design.md` and locate the section starting `### 6.8 pdf_inspect_layout(...)` (around line 324).

- [ ] **Step 2: Add a forward reference**

Insert a single line at the end of §6.8 (just before §6.9 starts):

```markdown
> **Update 2026-05-09:** vector drawings are now spatially clustered by
> default to handle PDFs where `get_drawings()` returns thousands of raw
> path entries. See [`2026-05-09-pdf-inspect-layout-clustering-design.md`](./2026-05-09-pdf-inspect-layout-clustering-design.md).
```

- [ ] **Step 3: End-to-end verification on the real architectural PDF**

Restart the HTTP MCP servers so the new code is loaded:

```bash
./stop-mcp-http.sh
LM_PDF_INLINE_RENDER=0 ./start-mcp-http.sh
```

Then run an MCP probe to confirm compact output on the user's actual PDF:

```bash
uv run --with 'mcp>=1.2' python3 - <<'PY'
import asyncio
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

PDF = "RN ZZJZ - montažni fasada - 5.01 Sjever.pdf"

async def main():
    async with streamablehttp_client("http://127.0.0.1:8092/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("pdf_inspect_layout", {"path": PDF, "page": 5})
            text = next(c.text for c in res.content if c.type == "text")
            print(text)
            drawing_rows = [l for l in text.splitlines() if "\tdrawing\t" in l]
            print(f"\n=> {len(drawing_rows)} drawing rows on page 5 (was 14735 raw)")

asyncio.run(main())
PY
```

Expected: ≤ 20 drawing rows, header reports `N drawing clusters (from 14735 raw drawings)`, total response is well under the previous 50KB cap.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-07-pdf-mcp-design.md
git commit -m "docs(pdf): cross-link clustering design from original spec §6.8

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] Run full test suite once more:

  ```bash
  ./run_tests.sh tests/test_pdf_server.py -v
  ```

  Expected: all 103 tests pass (93 baseline + 10 new).

- [ ] Confirm canonical/mirror parity:

  ```bash
  diff pdf_server.py lm-studio-mcp/pdf_server.py
  ```

  Expected: only the `__main__` transport block differs.

- [ ] Confirm git log shows clean per-task commits:

  ```bash
  git log --oneline -12
  ```

  Expected: 10 task commits (`feat/perf/test/chore/docs(pdf): ...`) plus the spec commit and the earlier ASCII-URL fix.
