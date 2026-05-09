# pdf_inspect_layout: spatial clustering of vector drawings

**Status:** design approved, awaiting implementation plan
**Date:** 2026-05-09
**Scope:** modify the `pdf_inspect_layout` MCP tool in `pdf_server.py` (and its
`lm-studio-mcp/pdf_server.py` frozen-copy mirror)

## Problem

`pdf_inspect_layout` is the entry point for vision-driven crop workflows: the
LLM lists regions on a PDF page and picks one to feed into `pdf_extract_region`.
The current output dumps every result of `page.get_drawings()` as one TSV row.
The 2026-05-07 spec assumed PyMuPDF would group related path segments into
one drawing entry per logical block ("cijela tablica je 1 drawing s mnogo
linija"), so the row count would stay in the 5-50 range per page.

In practice, on a real architectural drawing
(`RN ZZJZ - montažni fasada - 5.01 Sjever.pdf`) the assumption fails badly:

| Page | text blocks | drawings | zero-dim | single-shape | area ≥ 1000 pt² |
|------|------------:|---------:|---------:|-------------:|----------------:|
| 1    |          49 |   10,258 |    5,190 |        5,884 |              23 |
| 2    |          46 |   10,531 |    5,346 |        6,084 |              23 |
| 3    |          31 |    6,151 |    2,203 |        4,341 |              89 |
| 4    |          31 |    3,341 |    1,084 |        2,126 |              79 |
| 5    |          31 |   14,735 |    5,434 |       10,499 |             116 |
| 6    |          31 |   11,052 |    4,663 |        7,933 |             129 |

The 50 KB `_to_tsv` cap truncates the output to ~242 rows, so the LLM gets a
small unrepresentative slice of degenerate boxes (zero-width segments,
hatching strokes) instead of the actual layout. WebUI screenshot from
2026-05-09 confirms: rows 224-225 on page 4 are `567,1103 → 624,1103`
(57×0 px) and `627,1103 → 627,1103` (0×0 px) — useless as crop targets.

The model cannot reason about 10K-row tables even if they fit, and the user
flagged the call as expensive ("dosta skupa operacija"). What the model
actually needs is **5-15 macro regions per page**: title block, main drawing
area, detail tables, legend, notes — each as one entry with a usable bbox.

## Goal

Make `pdf_inspect_layout` emit a **compact, signal-rich** layout listing by
default — typically 30-60 total rows per page (text + image + a handful of
drawing clusters) — while keeping today's verbose dump available behind an
opt-in flag for power users.

Workflow target (confirmed 2026-05-09): **find 5-15 macro regions per page,
crop one, move on.**

## Non-goals

- Auto-detecting figure-vs-caption pairs (already excluded in 2026-05-07 spec
  §10).
- Replacing the bbox parameter on `pdf_extract_region` with a block index
  (mentioned as future possibility, not in this scope).
- Reordering or re-classifying text/image blocks. They are already coarse
  enough (30-50 per page on this corpus).
- Optimizing `get_drawings()` itself — we treat its output as fixed input.

## Algorithm: spatial-hash union-find clustering

Applied **only to drawings**. Text and image blocks pass through unchanged.

1. **Filter degenerate inputs.** Drop drawings whose `rect.width <= 0` or
   `rect.height <= 0`. These are zero-area lines/points that can't be cropped.
2. **Spatial hash.** Pick `cell = max(50, cluster_tolerance * 10)` PDF points.
   For each surviving drawing, compute the inclusive range of cells its rect
   covers and register the drawing's index in every covered cell.
3. **Pairwise overlap test inside each cell.** Two drawings i and j cluster
   together iff their rects overlap when each is inflated by
   `cluster_tolerance` on every side. Union-find merge.
4. **Aggregate per cluster.** For each connected component compute:
   - `union_bbox` = (min x0, min y0, max x1, max y1) over member rects
   - `n_drawings` = number of member drawings
   - `total_shapes` = sum of `len(d["items"])` over members
5. **Filter small clusters.** Drop clusters whose `union_bbox` area (in PDF
   points²) is below `min_area`.
6. **Sort by area descending, cap at `max_drawings`.**

**Performance:** spatial-hash binning keeps the pairwise comparisons local.
Expected runtime on the worst observed page (page 5, 14,735 drawings) is
< 500 ms in pure Python; verified by `test_cluster_drawings_perf_14k`
(synthetic 15K random rects, must finish < 2 s as sanity ceiling).

A drawing whose rect spans multiple cells is registered in each, so a pair
may be tested for overlap more than once. Union-find handles duplicate unions
without state corruption; the redundant work is bounded by cluster fan-out
and is cheap.

## API surface

```python
def pdf_inspect_layout(
    path: str,
    page: int,
    dpi: int = 150,
    cluster_tolerance: int = 8,    # PDF points (~17 px @ 150 dpi)
    min_area: int = 100,           # PDF points² (~434 px² @ 150 dpi)
    max_drawings: int = 20,        # cap on returned drawing clusters
    verbose: bool = False,         # if True: skip clustering, emit raw rows
) -> str
```

All new parameters have defaults that preserve the goal output for the
observed PDF corpus, and existing callers that pass only `path/page/dpi`
get the new compact behavior automatically — no callers in the repo pass
the new parameters today.

`verbose=True` short-circuits the clustering pipeline entirely and emits
exactly today's TSV (one row per raw drawing, capped at 50 KB by `_to_tsv`).

### Compact output format

```
# layout for page 4 of 6, bbox in pixels @ 150 dpi
# 31 text, 0 image, 8 drawing clusters (3341 raw drawings, 1084 zero-dim, 2241 below min_area filtered)
index   type      x0    y0    x1    y1    hint
0       text      ...
...
30      text      ...
31      drawing   204   320   2280  1620  127 drawings, 482 shapes
32      drawing   2050  217   2450  1755  43 drawings, 187 shapes
33      drawing   1350  559   1475  1475  18 drawings, 64 shapes
...
```

- `index` is a sequential counter across the whole table (text → image →
  drawing clusters), matching today's behavior so existing prompts referring
  to "block N" still parse.
- `hint` for a drawing cluster is `"{n_drawings} drawings, {total_shapes} shapes"`.
  No "X more drawings omitted" trailer — the header line already gives the
  totals (raw count, zero-dim filtered, min-area filtered).

### Edge cases

| Case | Behavior |
|------|----------|
| Page has no drawings | Header reports `0 drawing clusters`; only text/image rows emitted (already handled). |
| All drawings filtered as noise | Emit a single line: `# all N drawings filtered as noise (set verbose=True or lower min_area to see them)`. |
| Verbose mode hits 50 KB cap | Existing `_to_tsv` truncation kicks in; existing trailer line `# truncated at ...` already explains. No change. |
| Cluster spans > half the page | Returned as-is. The `n_drawings` hint signals "this is a big merged region" so the model can decide whether to drill in with verbose. |
| `cluster_tolerance < 0` or `min_area < 0` or `max_drawings < 1` | `ValueError`, matching style of existing `dpi` range validation. |

## Defaults — rationale

| Parameter | Default | Why |
|-----------|--------:|-----|
| `cluster_tolerance` | 8 pt | PyMuPDF splits paths along segment boundaries; observed gaps between siblings of one diagram are typically 0-5 pt. 8 pt provides margin without bridging genuinely separate blocks (title-block-to-drawing gaps in this corpus are 30+ pt). |
| `min_area` | 100 pt² | Filters single dimension arrows (~1×30 pt = 30 pt²) and hatching cells (~5×5 = 25 pt²); preserves anything ≥ 10×10 pt. |
| `max_drawings` | 20 | Comfortably above the user-stated "5-15 macro regions" target with a buffer for dense pages. |

These defaults are tuned for the observed architectural-drawing corpus.
Other PDF families (research papers, scanned reports) typically have far
fewer drawings to begin with, so the clustering is a no-op or near-no-op
and the defaults stay correct.

## Mirror to lm-studio-mcp/pdf_server.py

Per `feedback_frozen_copies.md`, every change lands in both
`pdf_server.py` (canonical, HTTP transport) and
`lm-studio-mcp/pdf_server.py` (frozen-copy fork, stdio transport for LM
Studio). The only diff between the files remains the `__main__` transport
block.

## Testing

Add to `tests/test_pdf_server.py` (currently 93 tests passing):

1. `test_cluster_drawings_overlap_merges` — two overlapping rects → one cluster.
2. `test_cluster_drawings_tolerance_merges` — two rects within `cluster_tolerance` but not overlapping → one cluster.
3. `test_cluster_drawings_disjoint_separate` — two rects far apart → two clusters.
4. `test_cluster_drawings_filters_zero_dim` — degenerate rect (`width=0` or `height=0`) → ignored.
5. `test_cluster_drawings_filters_below_min_area` — rect smaller than `min_area` → ignored.
6. `test_cluster_drawings_caps_to_max_drawings` — more than `max_drawings` clusters → returns top N by area.
7. `test_pdf_inspect_layout_compact_default` — on a fixture PDF with many vector paths, output row count is bounded by `max_drawings + n_text + n_image`, not raw drawing count.
8. `test_pdf_inspect_layout_verbose_keeps_old_format` — `verbose=True` regression: output identical to today's format (one row per raw drawing).
9. `test_pdf_inspect_layout_validates_new_params` — `cluster_tolerance < 0`, `min_area < 0`, `max_drawings < 1` each raise `ValueError`.
10. `test_cluster_drawings_perf_14k` — synthetic benchmark with 15,000 random rects on a 2500×1750 px canvas, must complete < 2 s on the test runner.

Existing tests for `pdf_inspect_layout` remain valid (the compact output is
a strict superset of "has text/image/drawing rows with bbox in pixels").

## Implementation outline

(to be expanded by the implementation plan)

- Add `_cluster_drawings(drawings, tolerance, min_area, max_drawings) -> list[ClusterInfo]` helper.
- Add small `_UnionFind` class (or use ad-hoc `parent[]` array, keep file dep-free).
- Modify `pdf_inspect_layout` to branch on `verbose`; in compact mode, replace the `for d in p.get_drawings():` block with `for cluster in _cluster_drawings(...):`.
- Update header line to report cluster summary stats.
- Mirror to `lm-studio-mcp/pdf_server.py`.
- Update docstring and the 2026-05-07 spec §6.8 with a note pointing here.
