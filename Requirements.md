# Core capabilities mapped to your bullets
AI Tool for Civil Engineering Firms
Build a tool that:
•	Reads CAD drawings, PDFs, survey reports
•	Extracts measurements, slopes, elevations
•	Summarizes site plans
•	Answers questions (“What is the setback distance?”

## Read CAD drawings, PDFs, survey reports

### Inputs:

DWG/DXF (Civil 3D, standard CAD)

2D PDF plan sets (site, grading, utility, drainage, profiles)

TIFF/TIF raster plan and survey images

Survey reports (PDF, DOCX, TXT), CSV point files, LandXML

### Modules:

File normalizer: converts everything to a common internal format.

CAD parser: reads layers, blocks, polylines, text, dimensions, COGO points.

PDF plan reader: uses vision+OCR to detect title blocks, viewports, callouts, dimensions.

Raster image reader: records TIFF/TIF image metadata and provides the source for future OCR and vision extraction.

Text document parser: extracts narrative, tables, and key phrases (e.g., “setback”, “finished floor elevation”).

## Extract measurements, slopes, elevations

### Geometry engine:

Build a project coordinate system and unify CAD + survey data.

Identify:

    Property boundaries (parcel lines, bearings/distances).

    Contours and spot elevations (TIN surface or contour polylines).

    Roads, driveways, pads (by layer, block, or pattern).

Compute:

    Distances: between any two entities (e.g., building footprint to property line).

    Slopes:

    slope = (Δelevation/horizontal distance) X 100%

### Elevations: at points, along alignments, or over areas (min/max/average).

Metadata extraction:

    Read dimension strings, labels (“FF=102.50”, “Top of curb 101.80”), and tie them to geometry.

## Summarize site plans

### Site model builder:

Create a structured representation:

    Parcels: boundaries, area, zoning tags.
    Structures: building footprints, pads, parking areas.
    Access: driveways, roads, curb cuts.
    Grading: slopes, high/low points, drainage paths.
    Utilities: water, sewer, storm, electric (if layers/legends are available).

### Summarization engine (LLM-based):

Generate:

High-level site summary (use, access, grading concept).

Discipline-specific summaries (grading, drainage, utilities).

Risk/attention flags (steep slopes, tight setbacks, unusual elevations).

### Answer questions (“What is the setback distance?”)

Semantic query layer:

    User asks in natural language.

System:

    Interprets intent (“setback distance”, “north property line”).
    Maps to site model entities (parcel boundary, building footprint).
    Runs geometric computation (shortest distance, along a specified direction).

Returns:

    Numeric answer (e.g., “25.0 ft”).
    How it was computed (sheet reference, entities used).
    Optional screenshot/snippet of the plan with highlighted geometry.