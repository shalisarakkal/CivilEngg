# User Guide

A short guide to what this application does today, for someone using it
rather than developing it. For setup and running instructions, see
[README.md](README.md) (development) or [DEPLOYMENT.md](DEPLOYMENT.md)
(a standing local deployment).

## Signing in and roles

You need an account to use the application — there's no anonymous access.
An administrator creates your account (see DEPLOYMENT.md/CLIENT_INSTALL.md
for the first `sysadmin` account); there's no self-service sign-up.

Three roles, in increasing order of access:

- **User** — full working access (upload, process, calculate, summarize,
  ask questions) on the specific projects you're associated with, but
  never archive or purge anything, anywhere.
- **Power User** — everything a User can do, on projects you own or are
  a member of, plus archive/purge rights there. Creating a new project
  automatically makes you its owner. As owner, you can add or remove
  collaborators and delete/archive the project itself — a Power User
  who's just a collaborator (not the owner) can do everything except
  those two things.
- **Admin** — everything, on every project, plus user management
  (creating accounts, changing roles, disabling/enabling, reassigning a
  project's owner when needed).

A disabled account can't log in; if it has a session already open, that
session stops working on its next request rather than instantly. A
project's owner must always be a Power User — if that account is
disabled or deleted, an admin has to reassign ownership to another
Power User first.

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
- **Perimeter** — the total boundary length of a line or polygon (a circle
  uses `2 * pi * radius` instead).

Calculations only run against an **accepted revision** of a project's
site model, not against a file that has only been processed.

## Summaries and questions

- A generated site summary is source-grounded: it draws only from the
  site model and extracted document text, never an invented fact. Every
  summary you generate is kept (not overwritten) in a history list on
  the project, so past summaries remain available after generating a
  new one.
- Asking a question routes anything computable — distance/setback, slope,
  elevation, area, perimeter, a directional question ("the setback to
  the north property line"), a specific labeled spot elevation ("Where
  is EL 102.5 located?" or the difference between two such labels), a
  building's dimensions/orientation, a building's setback clearance from
  the parcel boundary, a count of a classified feature ("How many
  parking spaces are shown?"), or a drainage/utility presence question
  — to the deterministic calculation engine first; anything else is
  answered from retrieved source text, or with an explicit
  insufficient-data/ambiguous response rather than a guess. Most of
  these recognize a role in the question (parcel/property, building,
  driveway, curb cut, utility easement, parking, tree, sidewalk,
  detention basin) to pick the right entity when a site model has more
  than one of a similar kind.
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
- There's still no "add collaborator" UI — a Power User owner can
  reassign ownership to an *existing* collaborator, but can't add a new
  one without calling the API directly (see PLAN.md Phase 15).
- A project's coordinate reference system must be projected, not
  geographic (lat/lon degrees): distances, areas, and perimeters are
  measured on a plane. A geographic CRS is now refused when you set it,
  and measurements are refused outright for any project that already
  has one, rather than returning a number in degrees labelled as feet.
- Curved DXF/LandXML alignments (arcs, spirals) are not extracted.
- Label-to-geometry linking only covers DXF-sourced labels.
