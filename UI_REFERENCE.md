# UI Reference

What every control on the Project Workspace screen (`frontend/app/ProjectWorkspace.tsx`) actually does, grounded in the code rather than a general description. This is the foundation for a task-oriented user guide (see suggested structure at the bottom) — read section by section in the order they appear on screen, top to bottom, left to right.

There is currently one screen. Everything below lives on it.

## Header

- **"Project workspace" title and "Phase 6 active" badge** — static labels; the badge is a leftover marker from development phases and isn't interactive.
- **Status message banner** — a single line just under the header, pinned to the top of the screen (stays visible while you scroll). Every action in the app — creating a project, uploading a file, running a calculation, asking a question — updates this one line with what just happened or what went wrong. It only ever shows the single most recent action; it is not a log.

## Left Sidebar — Projects

### New project

- **Text field** (placeholder "Oak Street Site") — type the name for a new project here.
- **"+" button** — creates the project using whatever is typed in the field, then automatically selects it and clears the field. If the field is empty, nothing is created and the status message says "Enter a project name first." A newly created project starts with no files, revisions, or calculations — the right-hand panel prompts you to add a source file.

### Project list

Below the "New project" form, every non-archived project is listed by name with its unit system (e.g. "imperial") underneath. **Click a project row** to make it the active project — this loads its files, processing jobs, site-model revisions, and calculations into the right-hand panel. The currently active project is highlighted with a left border.

Archiving a project (see "Archive project" below) is the only way to remove it from this list; there's no direct delete here.

### Admin archive

Shows a running count ("N archived files") and, underneath, one row per archived file across all projects (not just the active one), each with:

- **Restore** — brings the file back to its project's normal file list, in whatever status it had when archived.
- **Purge** — opens a confirmation dialog ("Permanently delete `<name>`?"); confirming permanently deletes the file's database record and on-disk copy. Accepted revisions and calculations that already exist stay intact; only the original source file becomes unrecoverable.

### Archived projects

The same pattern as Admin archive, one level up: a running count ("N archived projects") and one row per archived project across the whole app, each with:

- **Restore** — brings the project back to the Project list above, fully intact (files, revisions, calculations, summaries, and questions were never touched by archiving).
- **Purge** — opens a confirmation dialog ("Permanently delete `<name>`?"); confirming permanently deletes the project's database rows (cascading to everything under it — files, jobs, revisions, entities, calculations, summaries, questions) and its on-disk storage folder. This cannot be undone. A non-archived project can't be purged directly — it has to be archived first.

## Right Panel — Active Project

Nothing in this panel renders until a project is selected; before that, it shows "Create your first project."

At the top, next to the project name, an **"Archive project"** button opens a confirmation dialog ("Archive `<name>`?"). Confirming hides the project from the sidebar's Project list and moves it to "Archived projects"; its files, revisions, calculations, summaries, and questions all become inaccessible along with it — none of it is deleted, but none of it is reachable either until the project is restored, at which point everything comes back exactly as it was.

### Source files (upload)

- **File picker** ("Choose a source file") — opens the OS file dialog, restricted to `.pdf`, `.dxf`, `.csv`, `.txt`, `.tif`, `.tiff`, `.xml`. Selecting a file shows its name in place of the placeholder text.
- **"Upload file" button** — disabled until a file is chosen. Uploads the selected file to the active project. On success, the file appears at the top of the file list below with status "Ready to process," the picker resets to its placeholder, and the status banner names the file ("`<name>` uploaded and queued for processing."). On a duplicate-content rejection (identical file already exists in this project), the picker also resets so you're not stuck reselecting the same rejected file; on any other failure, the picker keeps your selection so you can retry.

### File list

One row per file in the project (not counting archived ones), each showing:

- **Name, size, and checksum.**
- **"Replaced by a newer version"** (italic, only if this file has since been replaced — see "Replace" below).
- **Error message** (red, only if processing failed).
- **Processing warnings** (amber, only if completed with warnings — capped at 3 lines with a "+N more warning(s)" summary if there are more).
- **Status label**, one of: "Ready to process," "Processing...," "Processing completed" / "Processing completed with warnings," or "Processing failed."
- **Action buttons**, which change depending on status:
  - *Ready to process* → **Process** button: runs extraction on the file. Result becomes "Processing completed" or "...with warnings" or "Processing failed."
  - *Failed or stuck processing* → **Retry** button: re-runs extraction (same action as Process, relabeled).
  - *Completed* → **Accept revision** button: turns this file's extracted content into a new site-model revision (see next section). Once accepted, the button becomes disabled and reads "Revision accepted." Only one accept can run at a time across the whole file list — the button is disabled on every row while one is in progress.
  - **Replace** button (hidden once a file has already been replaced): opens an inline "Choose a replacement file" picker plus "Upload replacement" and "Cancel" buttons directly under that file's row. Uploading here links the new file to the original as a newer version of the same document (not a coincidentally-same-named unrelated file) — the original is marked "Replaced by a newer version" and can't be replaced again itself.
  - **Delete** button: opens a confirmation dialog ("Remove `<name>`?"). Confirming archives the file (moves it to the sidebar's Admin archive) — it is not immediately destroyed; accepted revisions and calculations built from it remain.

### Site model — Revision geometry

Only meaningful once at least one file has an accepted revision.

- **Revision dropdown** — lists every accepted revision in the project as "Revision N · filename · checksum." Switching it changes everything else in this section (and the Calculations/Site-intelligence sections below, where relevant) to that revision's data.
- **Entity count** ("N entities") — how many extracted geometry/text/table items exist in the selected revision.
- **Geometry preview** (the light-green box) — a schematic top-down plot of the selected revision's plottable geometry (points and lines; polygons are drawn via their outline). Not a real map — no basemap, no real-world scale. Click a point or line in the preview to highlight it (same as clicking its card below).
- **Entity cards** — one card per extracted item, each showing its type (point, line, text, key_phrase, etc.), validation status (valid/invalid/unmapped, colored accordingly), an optional semantic-type badge (e.g. "parcel boundary," inferred from a DXF layer name or CSV column) with an optional zoning tag, and its source (filename, or the quoted phrase for a key-phrase entity). Clicking a card highlights it in the geometry preview above.
- **Pagination** ("Showing X-Y of Z entities," Previous/Next) — the grid shows up to 200 entities per page for large revisions.
- **"View plan-sheet snippet" button** (appears only once something is highlighted) — re-renders the original source drawing as an image with the highlighted entity outlined in red, so you can see it in context on the original plan sheet. Only works for DXF-sourced entities; anything else shows an error message here instead of an image.

### Calculations

A form to run one deterministic geometric calculation at a time, plus a running results list.

- **Calculation dropdown** — Slope, Distance, Area, or Perimeter. Switching types changes which input fields appear below and resets the "Geometry JSON" field to a matching example.
- **Coordinate unit / Output unit dropdowns** (Feet/Meters/Inches) — the unit your input coordinates are in, and the unit you want the result expressed in; they can differ (the calculation converts).
- **Type-specific fields:**
  - *Slope*: Start elevation, End elevation, Horizontal distance (plain number fields).
  - *Distance*: two "Geometry JSON" text areas (first and second geometry) — each a GeoJSON-like object, e.g. `{"type":"Point","coordinates":[0,0]}`.
  - *Area / Perimeter*: one "Geometry JSON" text area. Perimeter additionally has a LineString-vs-Polygon toggle that changes the example JSON shown. Both also accept a Circle shape, e.g. `{"type":"Circle","center":[100,200],"radius":25}`.
- **"Run calculation" button** — submits the above. On success, a new row appears at the top of the results list below and the status banner confirms it; on invalid JSON, it refuses before even sending the request ("Geometry input must be valid JSON").
- **Results list** — the 5 most recent calculations for this project, each showing its type, result, the formula used, and (on the line below) the actual input values that produced that result — full geometry JSON if applicable, never truncated. **Clicking a result row** highlights whatever site-model geometry it referenced, switching the Revision-geometry section above to the right revision if needed; if the calculation used no site-model geometry (e.g. manually typed coordinates that don't match any extracted entity), the status banner says so instead.

### Site intelligence — Summarize and ask questions

- **"Request site summary" button** — generates a structured, deterministic AI summary (grading/drainage/utilities sections plus attention flags) and replaces whatever summary card is currently shown. Disabled until at least one revision exists. Only the single most recently generated summary is ever shown on screen — generating a new one hides the previous one from view (it isn't deleted from the database, just no longer displayed here).
- **Scope panel** — a checkbox list of every accepted revision in the project. Leave everything unchecked to use the default: the whole project (the single latest revision of every document). Check one or more specific revisions to limit both "Request site summary" and "Ask a question" to only those. The panel's own label ("Whole project..." / "Selected revisions only.") reflects your current choice.
- **Summary card** (once generated) — the summary text, grading/drainage/utilities details, any attention flags, and a footer naming which revisions it actually drew on (its resolved scope) plus its stated limitations.
- **"Ask a question" field + Ask button** — type a question (e.g. "What is the setback distance?") and submit. The answer is computed deterministically where possible (routed to the same calculation engine as above) or retrieved from extracted source text; it never invents a number. Every question and answer is appended to the history list below (not replaced), each showing its own resolved scope, method, confidence, and any limitations or "insufficient data"/"ambiguous" refusal.

## Confirmation Dialogs

Four modal dialogs interrupt the flow for destructive-ish actions, each with Cancel and a confirm button:

- **Archive file** — triggered by a file row's Delete button.
- **Permanent purge (file)** — triggered by the Admin archive panel's Purge button.
- **Archive project** — triggered by the "Archive project" button on the active project.
- **Permanent purge (project)** — triggered by the Archived projects panel's Purge button.

---

## Suggested structure for a task-oriented user guide built from this reference

- How to create a project
- How to upload a file (and what happens if you upload the same content twice)
- How to process a file and read its status/warnings
- How to accept a revision, and what a "revision" actually is
- How to replace a file with a newer version
- How to browse extracted geometry and view a plan-sheet snippet
- How to run a calculation and read its result
- How to generate a site summary and choose its scope
- How to ask a question and interpret confidence/limitations
- How to archive, restore, and permanently delete a file
- How to archive, restore, and permanently delete a project
