# MVP Risk Register

| Risk | Impact | Mitigation | Status |
| --- | --- | --- | --- |
| Parser extraction is incomplete | Incorrect or missing site data | Preserve warnings/source references and expose failed status | Active |
| Missing or incorrect CRS | Incorrect geometry distances/areas | Require coordinate units, preserve CRS metadata, report transformation failures | Active |
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
