# MVP Risk Register

| Risk | Impact | Mitigation | Status |
| --- | --- | --- | --- |
| Parser extraction is incomplete | Incorrect or missing site data | Preserve warnings/source references and expose failed status | Active |
| Missing or incorrect CRS | Incorrect geometry distances/areas | Require coordinate units, preserve CRS metadata, report transformation failures | Active |
| Calculations assume planar (projected) coordinates | If a project's CRS is geographic (lat/lon degrees), distance/area/perimeter formulas (Euclidean, via Shapely) would silently compute nonsense values labeled with the chosen linear unit, since degrees are not a linear measure | Not yet enforced: found during the Phase 8 calculation review (VERIFY.md section 12). Document that supported project CRSs must be projected; validating/rejecting a geographic CRS at calculation time is still open | Open |
| TIFF OCR is unavailable | Raster plans provide metadata only | Defer OCR to the vision phase and show a warning | Accepted limitation |
| AI could invent engineering facts | Unsafe or unauditable answers | Route computable questions to deterministic calculations and require provenance; refuse with an explicit insufficient-data/ambiguous response otherwise | Mitigated |
| Large or malformed uploads | Resource exhaustion or failed processing | 50 MB limit, MIME/extension validation, isolated failures | Mitigated |
| Accidental file deletion | Loss of source evidence | Archive files, preserve metadata, support restore and admin purge | Mitigated |
| Duplicate source files | Confusing project history | SHA-256 checksum detection within project, including archived records | Mitigated |
| Concurrent duplicate uploads | A race between the duplicate check and insert could let two identical files through | Database-level unique constraint on (project, checksum); the route treats the resulting integrity error as a duplicate-content conflict | Mitigated (Phase 8) |
| Local storage failure | Unavailable source documents | Document backup/restore and retain checksums/metadata | Operational follow-up |
| Unauthenticated local API | Unauthorized access if exposed | Keep local-only, single-user until authentication is implemented (ADR-005) | Accepted limitation |
| A real network-calling AI provider could hang or fail slowly | Slow or stuck requests once a live provider is connected | The current MockAIProvider makes no network calls; timeout/retry handling is deferred until a real provider (e.g. OpenAI) is integrated post-MVP | Deferred to post-MVP |
| Oversized or malicious request bodies | Resource exhaustion on non-upload endpoints | 2 MB request-body limit on non-multipart requests | Mitigated (Phase 8) |
| LandXML coordinate order varies by producer | The parser assumes the common "northing easting [elevation]" order; a file that instead uses "easting northing" would silently swap X/Y | Documented assumption in `extraction.py`; not detected or validated at parse time since there is no reliable in-file signal to distinguish the two orders | Open (Phase 9) |
| LandXML curved alignments (Curve/Spiral) are not extracted | Corridor/parcel geometry defined by arcs is invisible to the site model rather than approximated incorrectly | Explicit warning naming the skipped segment; only straight Line segments are extracted | Accepted limitation (Phase 9) |
