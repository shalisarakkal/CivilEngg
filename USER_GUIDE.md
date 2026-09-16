# User Guide

A short guide to what this application does today, for someone using it
rather than developing it. For setup and running instructions, see
[README.md](README.md) (development) or [DEPLOYMENT.md](DEPLOYMENT.md)
(a standing local deployment).

## What it does

1. Create a project.
2. Upload site-plan files to it.
3. Process a file to extract its geometry and text into a site model.
4. Review the extracted data, then accept it into a project revision.
5. Run deterministic engineering calculations against an accepted revision.
6. Generate a source-grounded summary, or ask a question about the project.

## Supported files

PDF, DXF, CSV, TXT, TIFF/TIF, LandXML, and related document files.

- TIFF/TIF currently provides raster metadata only; OCR (needed for
  scanned/image-only PDFs and TIFFs) is planned for a later phase.
- DXF: straight lines, polylines, text, points, and dimensions; curved
  alignments (arcs/spirals) are not extracted (see RISK_REGISTER.md).
- LandXML: points, surface points, and straight alignment segments.
- CSV: point/coordinate data, including quadrant bearing/distance (COGO)
  courses chained from an explicit point of beginning.

## Units

Distances support feet, inches, and meters; slope results are labeled as
either a percent or a ratio, whichever the request specifies. Every
calculation response states the units it used — there is no implicit
unit conversion between a project's stored coordinates and a requested
output unit without it being shown in the result.

## Calculations

All calculations are deterministic (not AI-generated) and reproducible:
identical inputs always produce identical results, and every response
includes its inputs, formula, result, units, and the source entities it
used.

- **Distance** — point-to-point and geometry-to-geometry.
- **Elevation** — lookup and statistics where the source data supports it.
- **Slope** — `slope = (change in elevation / horizontal distance) * 100`,
  with direction and percent-vs-ratio labeling.
- **Area** — parcel area and basic geometry measurements.

Calculations only run against an **accepted revision** of a project's
site model, not against a file that has only been processed.

## Summaries and questions

- A generated site summary is source-grounded: it draws only from the
  site model and extracted document text, never an invented fact. Every
  summary you generate is kept (not overwritten) in a history list on
  the project, so past summaries remain available after generating a
  new one.
- Asking a question routes anything computable to the deterministic
  calculation engine first; anything else is answered from retrieved
  source text, or with an explicit insufficient-data/ambiguous response
  rather than a guess.
- The AI layer is currently a deterministic mock that makes no network
  calls (see DECISIONS.md ADR-006) — answers are limited to what the
  site model and extracted text can actually support.

## File and project lifecycle

- Archiving a project or file removes it from the active view without
  deleting it; it can be restored from the archived-items panel.
- An archived project or file that nobody restores or purges is
  **automatically, permanently purged** after a configurable retention
  window (180 days by default). Archived items show a countdown, flagged
  once inside 15 days of that date, so it's never a surprise.
- Every purge — manual or automatic — is recorded in a permanent history
  log with what it was, when it was archived, why it was purged, and
  when (`GET /admin/purge-history`; no browsing UI yet).
- Uploading a file that duplicates one already in the project (by
  content, not just name) is detected and rejected, including against
  archived files.

## Known limitations

See RISK_REGISTER.md for the full list; the most relevant to day-to-day
use:

- No OCR yet — a scanned/image-only PDF page or a TIFF produces a
  warning rather than extracted text/geometry.
- No authentication — this is a single-user, local-only application
  (DECISIONS.md ADR-005). Do not expose it beyond local use.
- Calculations assume a projected (not geographic lat/lon) coordinate
  system; using a geographic CRS is not yet validated or rejected.
- Curved DXF/LandXML alignments (arcs, spirals) are not extracted.
- Label-to-geometry linking only covers DXF-sourced labels.
