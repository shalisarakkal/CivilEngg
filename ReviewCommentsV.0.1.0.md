# Code Review — v0.1.0-mvp

**Update (2026-09-16): all 9 findings below have been fixed and committed** as `d8c4164` ("Fix all 9 issues from the whole-project code review"), each via a reproduce-first cycle (a failing test written against the actual bug and confirmed to fail on the pre-fix code, then the fix applied, then the same test confirmed to pass) rather than inference from reading the code alone. See the "Fix applied" note under each finding for the specific change and its regression test. The original finding text is left unedited below for the record.

The `v0.1.0-mvp` tag still points at `356f329` (the pre-fix commit reviewed below) and has deliberately **not** been moved or replaced — more fixes may follow before the next release point is tagged.

Reviewed at commit `356f32926f2bc232b2f1d9bba570f46d05d41d3c` (2026-09-16), the tagged `v0.1.0-mvp` release candidate. This is a whole-project audit, not a single-PR diff review — there was no open pull request to review against, so the full backend, frontend, and documentation were covered.

**Method:** 5 parallel review passes (backend core engineering logic, backend API/routes/models, backend tests and ops scripts, frontend, and documentation accuracy), each checked for compliance with the root `AGENTS.md` coding standards (simplicity, no unnecessary defensive programming, no emojis) and cross-referenced against `RISK_REGISTER.md`/`DECISIONS.md` to exclude already-known, accepted limitations. Every finding below was independently re-verified against the actual current code before being included; candidate findings that didn't hold up on re-check, or that were pre-existing/accepted/style-only, were dropped.

Not checked: build/lint/typecheck signal (assumed to run separately in CI), and general test-coverage opinions not tied to a specific risky, untested code path.

**Severity rubric:**

| Severity | Meaning |
| --- | --- |
| Critical | Silently produces wrong engineering output, or breaks a core calculation, for realistic real-world input |
| High | Silently wrong/inconsistent data or behavior in a fairly common, supported workflow; no error or warning surfaces it |
| Medium | Real bug with a narrower trigger, contained blast radius, or an obvious workaround |
| Low | Documentation/operational accuracy issue with no effect on the running application |

Issues are numbered by severity, most severe first.

---

## Critical

### 1. Closed DXF polylines silently become open LineStrings, breaking area and understating perimeter

- `backend/src/civil_engineering/extraction.py:364-365` — `value = {"points": [list(point[:2]) for point in entity_any.get_points()]}` never checks `entity_any.closed`.
- `backend/src/civil_engineering/site_model.py:49-51` — `_geometry_from_value` decides Polygon vs. LineString purely by `points[0] == points[-1]`.

**Failure scenario:** AutoCAD/Civil3D commonly mark a closed polyline (a building footprint, a parcel boundary) via the DXF `closed` flag rather than by literally duplicating the first vertex as the last. `ezdxf`'s `get_points()` (`backend/.venv/Lib/site-packages/ezdxf/entities/lwpolyline.py:320`) does not append a synthetic closing point even when `closed=True` (confirmed against the installed library — `closed`/`is_closed` are a separate property). So `points[0] != points[-1]`, and the site model builds a `LineString` instead of a `Polygon` for what the drawing intended as a closed shape. Downstream, `calculate_area` then rejects it outright ("LineString geometry cannot be used for area"), and `calculate_perimeter` silently understates the real perimeter by the length of the missing closing segment — this is exactly the kind of silently-wrong engineering number ADR-003 (deterministic, auditable calculations) is meant to prevent.

**Not caught by:** no test in `backend/tests` creates an `LWPOLYLINE` at all.

**Fix:** in `parse_dxf`, when `entity_any.closed` is true, append the first point to the end of the points list before building the geometry.

**Fix applied:** `extraction.py`'s `LWPOLYLINE` branch now closes the ring when `entity_any.closed` is set. Regression test: `backend/tests/test_dxf_site_model.py::test_closed_lwpolyline_becomes_a_polygon_not_a_linestring` (also confirms an open polyline still correctly becomes a `LineString`, and that area/perimeter compute correctly — 100 and 40 for a 10×10 square).

---

## High

### 2. Reprocessing a file makes "latest extraction" non-deterministic

`ExtractedDocument.revision_number` defaults to `1` and is never incremented:

- `backend/src/civil_engineering/models.py:132`
- `backend/src/civil_engineering/routes.py:517-522` (`process_file` creates `ExtractedDocument` without setting `revision_number`)
- `backend/src/civil_engineering/routes.py:643-647` (`read_extraction` — `order_by(ExtractedDocument.revision_number.desc())` with no tiebreaker)

**Failure scenario:** the UI's "Retry" button (`frontend/app/ProjectWorkspace.tsx:1212`) calls `POST /files/{id}/process` again on a file that already has an extraction. This inserts a second `ExtractedDocument` row, tied at `revision_number=1` with the first. `GET /projects/{id}/files/{id}/extraction` then has no way to know which of the two tied rows is actually newest — the result depends on unspecified database tie-break order, not recency. A user who fixes something and retries can be shown the stale extraction. The correct pattern already exists in the same file for `ProjectRevision` (`routes.py:679-688`, `max(revision_number) + 1`) but wasn't applied here.

**Not caught by:** no test calls `/process` twice on the same file and checks `/extraction` afterward (`test_processing_resilience.py`'s retry test only covers a job that never completed, so only one row is ever created).

**Fix:** either compute `revision_number` the same way `ProjectRevision` does, or drop it from the sort key and use `ExtractedDocument.created_at.desc(), ExtractedDocument.id.desc()` instead.

**Fix applied:** the properly-fixed version, not the sort-key workaround — `process_file` now computes `revision_number` via the same `max(...)+1` retry-on-conflict pattern as `ProjectRevision`, backed by a new unique constraint (`backend/migrations/versions/0016_unique_extraction_revision.py`, applied to the real database) and the model's incorrect `default=1` removed. Regression test: `backend/tests/test_processing_resilience.py::test_reprocessing_a_file_produces_a_correctly_ordered_new_extraction`.

### 3. Archiving a file doesn't remove it from the default summary/question scope

`_resolve_revision_ids` (`backend/src/civil_engineering/routes.py:1140-1182`, used by `create_summary` and `ask_question`) selects source files with no `deleted_at` filter:

```python
files = (
    {file.id: file for file in database.scalars(select(SourceFile).where(SourceFile.id.in_(file_ids)))}
    if file_ids else {}
)
```

Compare `list_site_model_revisions` (`backend/src/civil_engineering/routes.py:886-908`), which explicitly filters `SourceFile.deleted_at.is_(None)` before deciding which revisions are "active."

**Failure scenario:** upload → process → accept a revision → archive that file. `GET /projects/{id}/site-model/revisions` correctly returns `[]`. But `POST /projects/{id}/summaries` or `/questions` with no explicit `revision_ids` will still resolve to that archived file's revision as "the latest for its document lineage" and include it in the answer — contradicting what the revisions list (and the UI) shows the user.

**Not caught by:** `test_question_answering.py` tests the *supersession* exclusion path (via `replace_file`) but nothing tests deleting a file and then asking a default-scope question.

**Fix:** filter `files`/`latest_by_group` by `SourceFile.deleted_at.is_(None)` in `_resolve_revision_ids`, mirroring `list_site_model_revisions`.

**Fix applied:** exactly as recommended. Regression test: `backend/tests/test_question_answering.py::test_archiving_a_file_excludes_its_revision_from_project_boundary`.

### 4. Polygon centroid used for directional questions double-counts the closing vertex

`backend/src/civil_engineering/ai_service.py:328-331`:

```python
if geom_type == "Polygon":
    ring = coordinates[0]
    xs, ys = zip(*[(point[0], point[1]) for point in ring], strict=True)
    return (sum(xs) / len(xs), sum(ys) / len(ys))
```

GeoJSON/Shapely polygon rings are closed (first coordinate repeats as the last), so this average counts that one vertex twice. Example: rectangle `[[0,0],[10,0],[10,4],[0,4],[0,0]]` — true centroid is `(5, 2)`, this computes `(4.0, 1.6)`.

**Failure scenario:** `_answer_directional` (`ai_service.py:335-371`) uses this centroid to pick "the north/south/east/west building/parcel/etc." among same-type candidates. A skewed centroid can bias which entity is chosen, especially for polygons with few vertices, or produce a biased distance in the resulting answer — silently, with no warning.

**Not caught by:** `test_directional_questions.py` and `test_semantic_classification.py` only exercise `LineString`/`Point` entities, never a closed `Polygon` through `_answer_directional`.

**Fix:** exclude the ring's final (duplicate) point before averaging, e.g. `ring[:-1]` when `ring[0] == ring[-1]`.

**Fix applied:** exactly as recommended (unconditional `ring[:-1]`, since this app's own geometry construction always closes rings). Regression test: `backend/tests/test_directional_questions.py::test_directional_question_picks_the_correct_polygon_by_true_centroid`, hand-verified to flip the "north" selection between two specific polygons designed so the bug and the fix disagree.

---

## Medium

### 5. Switching projects leaves a stale Q&A revision-scope filter active

`selectProject` (`frontend/app/ProjectWorkspace.tsx:430-437`) resets `entities`, `summaryHistory`, `questionHistory`, and `selectedFileIds`, but never resets `qaRevisionIds` (state declared at line 262, consumed at lines 1047 and 1075).

**Failure scenario:** in Project A, the user checks specific revisions under "Scope" to narrow a question/summary. They switch to Project B. The checkboxes won't visually appear checked (IDs don't match B's revisions), but the scope label still reads "Selected revisions only" (since `qaRevisionIds.length !== 0`), and "Request site summary"/"Ask" sends Project A's revision UUIDs as `revision_ids` to Project B's endpoints — neither "whole project" nor what the UI implies. At best this no-ops/errors server-side; at worst it returns an answer whose displayed scope doesn't match what was actually requested. (The same root cause also leaves `highlightedEntityIds`/`planSnippetUrl` stale across a project switch — worth clearing alongside this fix.)

**Fix:** add `setQaRevisionIds([])` to `selectProject`'s reset list.

**Fix applied:** `selectProject` now also resets `qaRevisionIds`, `highlightedEntityIds`, `planSnippetUrl`, and `planSnippetError`. Regression test: `frontend/tests/e2e/workspace.spec.ts` — "site intelligence: switching projects clears a selected revision-scope filter".

### 6. Staging a new file while a previous upload is in flight can silently discard it

- `frontend/app/ProjectWorkspace.tsx:541-589` (`uploadFiles`, race resolves in the `finally` at 583-588)
- `frontend/app/ProjectWorkspace.tsx:594-602` (`stageFiles`)
- `frontend/app/ProjectWorkspace.tsx:1195` (the file `<input>` — has no `disabled` while `loading`, unlike the submit/cancel buttons on the same form)

**Failure scenario:** user selects file A, clicks "Upload file" (sets `loading=true`). Nothing disables the file picker or the drop target during the request. While A is still uploading, the user picks or drops file B; `stageFiles` immediately calls `setPendingFiles([B])`. When A's request resolves, `uploadFiles`'s `finally` block runs `setPendingFiles(filesToUpload.filter(...))` using its own closed-over `filesToUpload`/`uploadResults` from when A started — which evaluates to `[]` since A succeeded — unconditionally overwriting `pendingFiles` and silently wiping out B. B is never uploaded and no message explains why it disappeared.

**Fix:** disable the file input and drop target while `loading` is true (matching the existing button guards), or have the `finally` block remove only the specific files it uploaded via a functional update instead of replacing `pendingFiles` wholesale.

**Fix applied, revised from the original recommendation above:** guarding on the shared `loading` flag (as first recommended, and as the existing submit/cancel buttons already do) turned out to be wrong — `loading` is shared across five unrelated actions (create project, upload, calculate, summarize, ask), so reusing it here blocked staging a file any time any of those was in flight, e.g. immediately after creating a project (`selectProject`/`loadProjectData` keeps `loading` true past project creation itself). This was caught because the fix broke real e2e tests (`full-workflow.spec.ts`, which creates a project and immediately uploads a file) once verified against the full suite, not by inspection. Fixed properly with a new, dedicated `uploading` state set only around `uploadFiles`, used to guard `stageFiles` and disable the file input — `loading` and the existing buttons are untouched. Regression test: `frontend/tests/e2e/workspace.spec.ts` — "upload state: the file picker rejects new selections while an upload is in flight".

### 7. DXF `TEXT` annotations are never scanned for key phrases, unlike PDF/TXT

`parse_dxf` (`backend/src/civil_engineering/extraction.py:344-378`) stores DXF text via `document.text.append(entity.dxf.text)` (line 369) but never calls `_key_phrase_items` on it. `parse_text` and `parse_pdf` both do call it for their text content.

**Failure scenario:** a DXF site plan with an annotation like "25' REAR SETBACK" on a `TEXT` entity produces no `key_phrase` entity, while the identical wording in a PDF or TXT file would be surfaced and become a searchable site-model annotation. This is inconsistent, silently-dropped data specific to the DXF path — not one of the DXF gaps already listed in `RISK_REGISTER.md` (those cover vocabulary breadth and label-to-geometry proximity, not this).

**Not caught by:** `test_extraction.py`'s DXF test uses `add_text("FF=102.50", ...)`, which contains no key phrase from the current vocabulary, so the missing call never surfaces.

**Fix:** call `_key_phrase_items` on DXF `TEXT` content the same way `parse_text`/`parse_pdf` do.

**Fix applied:** `parse_dxf`'s `TEXT` branch now scans its content with `_find_key_phrases` and appends matching `key_phrase` items, attributed to the same DXF entity (layer/entity_type/entity_id) as the text item itself. Regression test: `backend/tests/test_extraction.py::test_dxf_text_is_scanned_for_key_phrases`.

---

## Low

### 8. VERIFY.md's migration-head check is six migrations stale

`VERIFY.md:110` tells a verifier to expect:

```
0009_unique_source_file_checksum (head)
```

The actual head, per `backend/migrations/versions/`, is `0015_add_purge_history` (chain verified unbroken 0001→0015). Someone following this runbook today would see a mismatch and could reasonably think something is broken or they're on the wrong branch.

**Fix:** update the expected output to `0015_add_purge_history (head)` (and keep this in mind as a recurring maintenance item — it will go stale again after the next migration).

**Fix applied:** updated to `0016_unique_extraction_revision (head)` — the true current head, since fixing finding #2 above added that migration in the same pass.

### 9. API.md incorrectly claims summaries have no list route

`API.md:97`: *"There is no list route for summaries or past questions; the frontend keeps them in local state as they're created within a session."*

This is only true for questions. `GET /projects/{project_id}/summaries` exists (`backend/src/civil_engineering/routes.py:1213`, `list_summaries`), returns persisted `ProjectSummary` rows, and is what the frontend now uses for its summary history list (Phase 11 — see `PLAN.md`/`CHANGELOG.md`). The route is also missing from `API.md`'s endpoint list at line 92 (only the `POST` is listed). A reader relying on `API.md` would wrongly conclude summary history isn't persisted server-side.

**Fix:** add `GET /projects/{project_id}/summaries` to the endpoint list, and narrow the "no list route" sentence to just past questions.

**Fix applied:** exactly as recommended.

---

## Minor (noted, not counted as a primary finding)

- **No test coverage for the file-level branch of the auto-purge sweep.** `_sweep_expired_archives`'s project branch (`backend/src/civil_engineering/routes.py:157-165`) is fully tested (`test_archive_auto_purge_retention_and_history`), but the structurally-identical file branch (lines 167-175, which permanently deletes `SourceFile` rows and their on-disk storage) has no equivalent test. This is a coverage gap on a destructive path rather than a confirmed bug — worth a follow-up test analogous to the existing one, but not flagged as a defect since no actual incorrect behavior was found.

---

## Not flagged (considered and ruled out)

- `backup.py`/`restore.py`: traced every branch of the safety guards (non-PostgreSQL check, `--force` gate, conditional `PGPASSWORD` handling) — all sound, and the restore path has been verified against a real production backup (`DEPLOYMENT.md` section 6).
- `storage.py` path-traversal guards: correct in all cases checked.
- All 15 Alembic migrations: correct and appropriately irreversible only where the data itself is inherently gone (e.g. `purge_history` has no FKs by design, documented in its own docstring).
- Frontend `globals.css` and Playwright e2e specs: no high-confidence issues; existing regression tests (batch-toolbar stuck state, sequential accept-revision numbering) genuinely exercise what they claim to.
- The `react-hooks/exhaustive-deps` suppression in the initial-load effect: a deliberate, explained decision, not flagged.
- Lack of authentication: a deliberate, documented decision (`DECISIONS.md` ADR-005), not flagged.
- The already-known, accepted limitations in `RISK_REGISTER.md` (LandXML coordinate order/curves, OCR gaps, label-linking scope, semantic classification coverage, etc.) were not re-reported.

---

## Summary

| # | Severity | Issue | Status |
| --- | --- | --- | --- |
| 1 | Critical | Closed DXF polylines become open LineStrings — breaks area, understates perimeter | Fixed |
| 2 | High | Reprocessing a file makes "latest extraction" non-deterministic | Fixed |
| 3 | High | Archived files aren't excluded from default summary/question scope | Fixed |
| 4 | High | Polygon centroid double-counts closing vertex, skews directional answers | Fixed |
| 5 | Medium | Stale Q&A revision-scope filter carries across project switches | Fixed |
| 6 | Medium | Upload race can silently discard a newly staged file | Fixed |
| 7 | Medium | DXF TEXT annotations never scanned for key phrases | Fixed |
| 8 | Low | VERIFY.md migration-head check is stale | Fixed |
| 9 | Low | API.md wrongly claims summaries have no list route | Fixed |

All 9 fixes are covered by new regression tests (5 backend, 2 frontend Playwright); the full backend suite (98 tests) and the mocked frontend e2e suite pass. One unrelated, pre-existing issue was found while verifying: `full-workflow.spec.ts` and `phase9.spec.ts` have 5 tests that fail against the real backend even on the original, unmodified code (confirmed via `git stash`) — the webServer log shows "Slow filesystem detected... is a network drive," suggesting these are environment-timeout flakiness on this machine's `S:` drive rather than an application defect. Not fixed here since it's outside the scope of this review's findings and predates all of the above changes.

---

# Code Review — Phase 14 / Phase 15 Follow-Up (2026-09-19)

**Update (2026-09-19): all 6 findings below have been fixed and committed**, each via the same reproduce-first cycle as the original review (a regression test confirmed to fail on the pre-fix code, verified by temporarily reverting each fix and re-running its test, then confirmed to pass after fixing). See the "Fix applied" note under each finding.

Reviewed the code-touching commits landed since the `v0.1.0-mvp` review above: `b16537d` (Phase 15 — roles, ownership, session-cookie authentication; 49 files, roughly 3,200 lines, the largest and most security-sensitive change since the last review), `c8ddc6a` and `b62ec67` (geographic-CRS validation and a unit-aware label-link cutoff), and `f45a6e7` (Phase 14 — Question-Answering Coverage Expansion: count/dimensions/orientation/setback-compliance/drainage/utility/elevation-lookup question intents). Phase 15 in particular had not been through this whole-project review process before, despite being the biggest change to the trust boundary the app has ever made (ADR-009).

**Method:** four parallel review passes: (1) Phase 15 backend authorization/session logic against every permission dependency in `routes.py`/`auth.py`; (2) Phase 15 frontend role-gating against what the backend actually enforces; (3) an adversarial pass on the Phase 14/CRS diff, explicitly instructed not to assume the code is correct just because it has tests; (4) `AGENTS.md` coding-standard compliance and a cross-check against this same file's prior nine findings for recurring bug shapes (a filter present in one function but forgotten in a sibling, stale state not reset on a transition, non-deterministic ordering, documentation drift). Every finding below was independently re-verified by direct code reading and, for the ones fixed, by executing the actual code before being included. Findings a reviewing pass itself rated low-confidence, or that were already-accepted/intentional/pre-existing, were dropped; see "Noted, not fixed" and "Not flagged" below.

**Severity rubric:** same as above.

---

## Critical

### 10. Setback-compliance silently compared a raw coordinate-unit distance against a threshold converted to true metres

- `backend/src/civil_engineering/ai_service.py`, `_answer_setback_compliance` (added in `f45a6e7`).

```python
clearance = shape(building_entity["geometry"]).boundary.distance(...)      # raw project-coordinate units
threshold_meters = convert_distance(threshold_value, threshold_unit, "m")  # always TRUE metres
compliant = clearance >= threshold_meters
```

**Failure scenario:** this app's own default unit system is imperial and every `TestQuestions` worked example is in feet. A project with feet-based coordinates and a real 20 ft clearance, asked "Is the building's setback at least 25 ft?", converted the *threshold* (25 ft to 7.62, true metres) but left `clearance` unconverted (20, in feet) and compared `20 >= 7.62`, reporting "compliant" — the opposite of the correct answer (20 ft is less than the 25 ft required). Reproduced directly against the function before fixing.

**Fix applied:** the one-sided conversion is removed; `clearance` and the stated threshold are now compared directly, on the explicit, honest assumption already used everywhere else in this file (e.g. `_answer_distance`'s "assumes both geometries share the same coordinate unit") — the project's raw coordinates are taken to already be in whatever unit the question stated its setback in, since this function has no way to know the project's true coordinate unit. The reported unit now reflects what was actually compared instead of unconditionally claiming "m". Regression test: `backend/tests/test_qa_coverage_expansion.py::test_setback_compliance_does_not_convert_the_stated_threshold_to_a_different_unit`.

### 11. `_resolve_revision_ids` returned caller-supplied revision ids with no check they belong to the requesting project (cross-project IDOR)

- `backend/src/civil_engineering/routes.py`, `_resolve_revision_ids`, used by `create_summary` and `ask_question`.

```python
if requested:
    return requested
```

**Failure scenario:** `require_project_member` only checks membership on the `project_id` path parameter — it never touches `revision_ids`. A Power User who is a member of Project A only, and who obtains a revision id from unrelated Project B, could call `POST /projects/A/questions` (or `/summaries`) with `revision_ids: ["<Project B's revision>"]`. Project B's site-model entities — geometry, properties, source references — would be pulled into the answer given back to a caller with zero relationship to Project B, and **persisted** on Project A's own `QuestionAnswer`/`ProjectSummary` row, retrievable later via `GET /projects/A/summaries`. This defeats the per-project membership boundary the rest of the file enforces everywhere else — every other project-scoped lookup (calculations, revision compare, entity listing) explicitly filters by `project_id`; these two call sites were the only exceptions.

**Not caught by:** no existing test passed a revision id across two different projects.

**Fix applied:** `_resolve_revision_ids` now filters any caller-supplied ids down to ones that actually belong to `project_id` (`ProjectRevision.id.in_(requested), ProjectRevision.project_id == project_id`), silently dropping any that don't — the same as a stale/nonexistent id would already be silently ignored. Regression test: `backend/tests/test_auth.py::test_revision_ids_are_scoped_to_the_requesting_project` (two Power Users, each owning their own project; confirmed the id is dropped and no cross-project revision is ever recorded against the other project's question/summary).

---

## High

### 12. Substring-collision bug in the new role/semantic-type keyword matching (recurrence of the same bug shape fixed elsewhere in the same commit)

- `backend/src/civil_engineering/ai_service.py`, `ROLE_TO_SEMANTIC_TYPE`/`_question_role`
- `backend/src/civil_engineering/routes.py`, `_semantic_type_from_text`

Both added bare single-word keywords ("tree", and briefly "lot") matched via a plain substring check. "tree" is a literal substring of "street"; "lot" is a substring of the ordinary English phrase "a lot of". Reproduced directly: `_question_role("What is the distance to the street?")` returned "tree", and `_semantic_type_from_text("STREET")`/`_semantic_type_from_text("MAIN STREET")` — a very ordinary CAD layer name for road infrastructure — returned "tree" instead of "driveway_road".

**Why High, not Medium:** this is the exact same bug shape this same commit's own fix (the compass-direction "east" substring of "least") explicitly identified and fixed with word-boundary matching, but the fix wasn't applied to the sibling role/keyword lookups introduced in the same diff — and a real DXF layer literally named "STREET"/"MAIN STREET" would have silently misclassified real site-model geometry, not just misrouted an occasional question.

**Fix applied:** both functions now match keywords with word-boundary-anchored regex instead of a bare substring, mirroring the existing direction-word fix. This alone would have broken ordinary plurals (a strict word-boundary pattern does not match "trees" — there is no boundary between "tree" and its own trailing "s" — confirmed, and would have been a real regression against a plan layer literally named "TREES"), so the pattern allows an optional trailing "s". The bare "lot" role phrase (never actually required by `TestQuestions`, which only ever uses "lot" inside "parking lot") is dropped entirely rather than patched, since "a lot of" is a genuine standalone English word no word-boundary regex can disambiguate from the site-plan sense. Regression tests: `backend/tests/test_ai_service.py::test_question_role_does_not_misfire_on_substring_or_break_on_plurals`; `routes.py`'s side uses the same fix pattern (`_contains_keyword`) and is exercised by the existing semantic-classification suite.

### 13. Demoting a project owner to `user` role didn't strip their owner-level permissions

- `backend/src/civil_engineering/routes.py`, `update_user`.

```python
if payload.role is not None:
    if user.role == ROLE_ADMIN and payload.role != ROLE_ADMIN:
        _require_not_last_active_admin(database, user)
    user.role = payload.role   # no _require_no_owned_projects check
```

`_require_no_owned_projects` is called on the `disabled=True` branch immediately above and in `delete_user`, but not here. `require_project_owner` (`auth.py`) only checks `project.owner_id == user.id`, never the owner's current role.

**Failure scenario:** an admin demotes a Power User who still owns an active project straight to `role="user"`. `require_project_owner` still passes for that account on that project — it can still archive it, permanently purge it, manage its members, and reassign its ownership, directly contradicting ADR-009's "a project's owner must be a power_user" and the `user` role never having archive/purge rights "anywhere".

**Fix applied:** the role-change branch now also calls `_require_no_owned_projects` whenever the target role is `user` (covering both a Power-User-to-user and an Admin-to-user demotion, the two paths that can leave an invalid owner). Regression test: `backend/tests/test_auth.py::test_demoting_a_project_owner_to_user_role_is_blocked`.

---

## Medium

### 14. Reassigning project ownership locked the previous owner out of the project entirely

- `backend/src/civil_engineering/routes.py`, `reassign_project_owner`.

The function's own comment claimed the old owner keeps their membership unless explicitly removed, same as any collaborator — but no code path ever granted the outgoing owner a membership row (an owner never has one to begin with; `add_project_member` explicitly rejects adding the current owner as a member). The frontend's confirmation dialog states the same claim: ownership moves immediately, and you keep your own access unless removed separately.

**Failure scenario:** a non-admin Power User who owns a project reassigns ownership to a collaborator. Immediately afterward they have neither `owner_id` nor a membership row, so `is_project_member`/`require_project_member` return not-found for them — they lose all access to a project the UI just told them they'd keep working on. (Admins performing the same action are unaffected, since `is_project_member`/`is_project_owner` special-case the admin role.)

**Fix applied:** `reassign_project_owner` now grants the previous (non-admin) owner an explicit `ProjectMembership` row, so they retain collaborator-level access exactly as the comment and UI copy already claimed — skipped for an admin (already has universal access) or a no-op reassignment to the same user. Regression test: `backend/tests/test_auth.py::test_reassigning_ownership_does_not_lock_out_the_previous_owner`.

### 15. Duplicate spot-elevation labels resolved silently instead of flagging ambiguity, unlike every sibling resolver added in the same phase

- `backend/src/civil_engineering/ai_service.py`, `_find_labeled_elevation` (used by the new `elevation_lookup` intent).

```python
return next((entity for label_value, entity in _label_elevation_entities(entities)
             if math.isclose(label_value, value, abs_tol=0.01)), None)
```

`_answer_area`, `_answer_perimeter`, `_answer_dimensions`, `_answer_orientation`, and `_answer_setback_compliance` — all touched or added in the same Phase 14 commit — explicitly detect more than one matching candidate and return a clarification-needed response. This resolver instead silently took the first match via `next()`.

**Failure scenario:** a real plan repeating the same rounded benchmark elevation (two separate "EL 100.00" callouts is plausible) would silently resolve "Where is EL 100.00 located?" to whichever label happens to come first in extraction order, with no indication to the caller that the match wasn't unique.

**Fix applied:** renamed to `_find_labeled_elevations` (plural), now returning every match; both the single-label and elevation-difference branches of `_answer_elevation_lookup` check for more than one match and return the same ambiguous response the sibling resolvers use. Regression test: `backend/tests/test_qa_coverage_expansion.py::test_elevation_lookup_flags_ambiguity_instead_of_silently_picking_a_duplicate_label`.

---

## Noted, not fixed in this pass

Real findings judged lower-severity, lower-certainty, or a larger change than this review's scope — left open rather than guessed at:

- **Sessions are not revoked on password change** (`change_own_password` and `update_user`'s password-reset branch, `routes.py`). A stolen session cookie remains valid for up to `session_ttl_days` (7 days) after the victim changes their password, since nothing ties an issued session to the password hash it was created under.
- **The session cookie has no `Secure` flag** (`auth.py`'s `set_session_cookie`), and `DEPLOYMENT.md`/`CLIENT_INSTALL.md` give no guidance requiring TLS termination for a real client-site install — a real risk given ADR-009 itself cites "changes the trust boundary" as this phase's motivation, but a deployment-configuration question rather than a pure code defect.
- **Deleting a user who owns an archived (not active) project raises an unhandled 500** instead of the clean 422 `_require_no_owned_projects` gives for an *active* owned project — `Project.owner_id`'s foreign key has no `ondelete=`, and the check only queries for `archived_at.is_(None)`. A real gap in the exact ownership-integrity logic this phase introduced, but narrow (requires an archived-but-not-purged owned project) and not a security issue.
- **`route_question` ordering hazard between `count` and `dimensions`**: "How many feet wide is the building?" contains both "how many" (checked first) and a role, so it resolves to `count` instead of `dimensions`/width. Not a phrasing `TestQuestions` actually uses — a latent hazard, not a confirmed regression against this app's own test corpus.
- **`AuthContext.tsx` re-implements the 401-redirect `api.ts`'s `apiFetch` already handles globally** (its own doc comment says this is precisely so call sites don't have to). Functionally harmless (both paths land on `/login`), flagged only because it's the kind of redundant defensive code `AGENTS.md`'s "no unnecessary defensive programming" line calls out.

## Not flagged (considered and ruled out)

- Login timing side-channel (a nonexistent username short-circuits before the expensive bcrypt check): common, low-severity, frequently an accepted risk industry-wide.
- `GET /users/lookup` returning more than a bare existence check to any authenticated caller: the route's own docstring documents this as a deliberate trade-off (exact-match-only, not directory enumeration).
- `PATCH /projects/{id}` gated on membership only (a `user`-role collaborator can edit project metadata, including `coordinate_reference_system`): ADR-009 doesn't explicitly forbid this for the `user` role, and this route predates Phase 15's permission matrix — plausibly an intentional scope decision, not a clear contradiction of anything documented.
- An admin changing/disabling their own role from their own row in the admin user list, leaving stale cached `currentUser` state client-side: real but narrow, self-inflicted, no security exposure (the backend re-validates role from the database on every request).
- No emoji found in any of the four reviewed commits' diffs.
- All ADR-009 permission dependencies (`require_admin`/`require_project_member`/`require_project_archive_rights`/`require_project_owner`) checked against every route in `routes.py`: correctly applied everywhere else, matching the documented owner-vs-any-power-user split for project- vs. file-level archive/purge.
- The oriented-bounding-rectangle width/length/orientation math, the unit-aware label-link cutoff, and the geographic-CRS rejection wiring: all independently verified correct (hand-checked geometry, and against this file's own regression tests).
- The original "east" substring-of-"least" fix from earlier the same day: verified correct.
- Frontend role-gating (archive/purge/restore/reassign/add-collaborator buttons) checked against the actual backend dependency for each action: no case found where a button is shown to a role the backend forbids, or hidden from a role the backend allows.

## Summary

| # | Severity | Issue | Status |
| --- | --- | --- | --- |
| 10 | Critical | Setback-compliance compared unconverted clearance against a metres-converted threshold | Fixed |
| 11 | Critical | Cross-project revision_ids IDOR in `_resolve_revision_ids` | Fixed |
| 12 | High | Substring collision in new role/keyword matching ("tree" in "street") | Fixed |
| 13 | High | Demoting a project owner to `user` role didn't strip owner-level permissions | Fixed |
| 14 | Medium | Reassigning ownership locked out the previous owner entirely | Fixed |
| 15 | Medium | Duplicate elevation labels resolved silently instead of flagging ambiguity | Fixed |

All 6 fixes are covered by new regression tests, each independently confirmed to fail on the pre-fix code (via temporary revert) and pass after fixing. The full backend suite (131 tests) passes; ruff and mypy are clean except the same three pre-existing, unrelated `extraction.py` errors noted throughout this project's history. Two stale documentation lines found during the `AGENTS.md`-compliance pass (`AGENTS.md`'s own historical note, and `PLAN.md`'s MVP-scope list, both still listing authentication as unimplemented/deferred after Phase 15 shipped it) were corrected alongside these fixes.
