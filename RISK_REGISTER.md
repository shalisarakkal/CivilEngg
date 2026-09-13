# MVP Risk Register

| Risk | Impact | Mitigation | Status |
| --- | --- | --- | --- |
| Parser extraction is incomplete | Incorrect or missing site data | Preserve warnings/source references and expose failed status | Active |
| Missing or incorrect CRS | Incorrect geometry distances/areas | Require coordinate units, preserve CRS metadata, report transformation failures | Active |
| TIFF OCR is unavailable | Raster plans provide metadata only | Defer OCR to the vision phase and show a warning | Accepted limitation |
| AI could invent engineering facts | Unsafe or unauditable answers | Route computable questions to deterministic calculations and require provenance | Planned in Phase 7 |
| Large or malformed uploads | Resource exhaustion or failed processing | 50 MB limit, MIME/extension validation, isolated failures | Mitigated |
| Accidental file deletion | Loss of source evidence | Archive files, preserve metadata, support restore and admin purge | Mitigated |
| Duplicate source files | Confusing project history | SHA-256 checksum detection within project, including archived records | Mitigated |
| Local storage failure | Unavailable source documents | Document backup/restore and retain checksums/metadata | Operational follow-up |
| Unauthenticated local API | Unauthorized access if exposed | Keep local-only until authentication is implemented | Accepted limitation |
