# Phase 6: figures and tables

Goal: every figure is readable at print size and honest about the data; every table is logically grouped,
complete, and ready to typeset. Look at each figure image (Read tool on the PNG; for PDF figures or the compiled
paper use `scripts/render_pages.py`, e.g. `--dpi 300` to see a figure at print resolution). Judge at the size it will be printed: a single column is about 89 mm wide
and a double column about 183 mm, so a figure image 2,000 px wide shown in one column is shrunk about five
times. Text that is fine on screen can be 3 pt on paper.

## Figures: checklist

Readability at final size
- All text (axis labels, tick labels, legends, annotations, panel labels) at least 5 to 7 pt at print
  size; nothing overlapping or clipped; no text cut off at panel edges.
- Line widths and markers visible; dense scatter or bars still separable.
- Panel labels present (a, b, c), consistent, and in reading order.
- Vector format for plots and line art where the venue accepts it; raster images (photos, microscopy)
  at 300 dpi or more at final size.

Honesty and clarity
- Axis labels with units; axis ranges that do not exaggerate (bar charts start at zero; truncated axes
  are marked); log scales labeled.
- Uncertainty shown for estimates and defined in the caption (s.d., s.e.m., 95% CI, IQR), with `n` per
  group or panel and the test used; comparable panels use the same uncertainty definition.
- Colors: no rainbow or jet color maps for ordered data; color-blind safe; not red/green as the only
  contrast; meaning does not depend on color alone; still readable in grayscale.
- Same category, same color across all figures; legends shared or direct labels rather than repeated keys.
- Visual hierarchy: the main result is the most visible element, not a baseline.
- Confusion matrices: rows and columns labeled (actual vs predicted), counts and/or normalized values
  stated, normalization direction stated.
- Image integrity (photos, microscopy, gels): scale bars, no undisclosed splicing, contrast changes
  applied to the whole image and stated.

Caption
- Starts with a title phrase that names the whole figure; describes each panel; defines every symbol,
  color, abbreviation, error bar, and `n`; can be understood without the main text.
- Numbers in the caption match the text and tables (cross-check with phase 3).

Necessity
- Each figure supports a claim made in the text; no figure duplicates a table without adding something.

## Tables: checklist

- Logical grouping: rows ordered meaningfully (by model family, by size, by performance with the best
  marked), related columns adjacent, grouped headers for metric families, a separate block for baselines.
- Every column has a header with units; abbreviations defined in a note; consistent decimals per metric;
  numbers right- or decimal-aligned; best values marked consistently (and the marking matches the max).
- Totals and percentages add up (`recompute_metrics.py sum` / `pct`).
- Uncertainty or `n` given where results are compared.
- No empty cells without an explanation (use a dash and a note).
- Fits the page (no tiny font scaling, no overflow); long tables split or moved to the supplement.
- Booktabs-style rules (no vertical lines, few horizontal lines) unless the venue's template differs.
- Caption says what the table shows, the data split, and the meaning of bold/italic/stars.

## Output

`phases/06-figures-tables.json`: `coverage` in `figures and tables` (total = all displays in
`manuscript.json` of type figure or table, plus any in the supplement you were given). `items`:
`{"label", "type", "verdict": "ready|needs_work", "checked": ["readability", "caption", ...]}`. Set
`location.label` on each finding to the display label so the dashboard gallery attaches it to the image.
