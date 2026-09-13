# Testing Strategy

## Objectives

Verify that source data is processed predictably, engineering calculations are reproducible, and user-visible answers remain traceable to source material.

## Test Layers

### Unit Tests

Cover:

- File type and metadata validation
- PDF, CSV, TXT, DXF, and TIFF/TIF parsing
- Normalization and unit conversion
- Coordinate transformations
- Geometry validation
- Distance, elevation, slope, and area calculations
- Site-model validation
- Question intent routing
- AI response formatting and limitation handling

### Integration Tests

Cover:

- API and database persistence
- Local file storage
- Upload and processing status transitions
- Extraction to site-model revision
- Site model to calculation result
- Mock AI provider and source references

### End-to-End Tests

Use Playwright to cover:

1. Create a project.
2. Upload a supported file.
3. Observe processing status.
4. Inspect extracted geometry or text.
5. Run a calculation.
6. Ask a geometry-backed question.
7. Verify the displayed result and source reference.

## Test Data

- Use synthetic or sanitized civil-engineering fixtures.
- Do not commit confidential project plans or client information.
- Include valid, empty, malformed, unsupported, and duplicate files.
- Include files with missing units and missing coordinate systems.

## Engineering Assertions

- Use hand-verified expected values for sample distances, elevations, slopes, and areas.
- Use tolerances for floating-point calculations.
- Verify that slope uses `change in elevation / horizontal distance * 100`.
- Verify unit labels and conversions in every calculation response.
- Verify that missing source data produces `insufficient_data`, not an invented answer.

## Quality Gates

Every implementation phase should pass:

- Formatting
- Linting
- Type checking
- Unit tests
- Relevant integration tests
- Relevant Playwright tests for user-facing changes

The full suite must pass before MVP release. Test failures should be fixed or explicitly documented as known limitations; they should not be ignored.
