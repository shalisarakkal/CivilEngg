"use client";

import { FormEvent, useEffect, useState } from "react";

type Project = { id: string; name: string; description: string | null; default_unit_system: string };
type SourceFile = { id: string; original_name: string; size_bytes: number; status: string; checksum: string; error_message: string | null };
type ProcessingJob = { id: string; source_file_id: string; status: string };
type Revision = { id: string; revision_number: number; created_at: string; source_job_ids: string[] | null; notes: string | null };
type Entity = { id: string; entity_type: string; geometry: Record<string, unknown> | null; properties: Record<string, unknown> | null; validation_status: string; source_reference: Record<string, unknown> | null };
type Calculation = { id: string; calculation_type: string; result: number; unit: string; formula: string; assumptions: unknown[] | null; revision_id: string | null; inputs: Record<string, unknown> };
type SummaryContent = { summary: string; grading: string; drainage: string; utilities: string; attention_flags: string[]; limitations: string[] };
type Summary = { id: string; content: SummaryContent; created_at: string };
type Answer = { answer: string; method: string; confidence: number; result?: number; unit?: string; formula?: string; limitations?: string[]; source_references?: (Record<string, unknown> | null)[]; source_excerpts?: string[] };
type QuestionAnswerRecord = { id: string; question: string; intent: string; answer: Answer; created_at: string };

type CalculationType = "slope" | "distance" | "area" | "perimeter";
type PerimeterGeometryType = "LineString" | "Polygon";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const defaultGeometry = '{"type":"Point","coordinates":[0,0]}';
const areaGeometry = '{"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}';
const perimeterGeometry = '{"type":"LineString","coordinates":[[0,0],[10,0],[10,10],[0,10],[0,0]]}';
const polygonPerimeterGeometry = '{"type":"Polygon","coordinates":[[[20,0],[0,0],[0,10],[20,10],[20,0]]]}'

function coordinatesEqual(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((value, index) => coordinatesEqual(value, b[index]));
  }
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-6;
  return a === b;
}

function geometriesEqual(a: Record<string, unknown>, b: Record<string, unknown> | null): boolean {
  if (!b || a.type !== b.type) return false;
  return coordinatesEqual(a.coordinates, b.coordinates);
}

function calculationGeometries(inputs: Record<string, unknown>): Record<string, unknown>[] {
  return ["geometry", "first_geometry", "second_geometry"]
    .map((key) => inputs[key])
    .filter((value): value is Record<string, unknown> => typeof value === "object" && value !== null);
}

function processingStatusLabel(status: string) {
  if (status === "completed") return "Processing completed";
  if (status === "failed") return "Processing failed";
  if (status === "processing") return "Processing...";
  if (status === "queued") return "Ready to process";
  return status;
}

function GeometryPreview({
  entities,
  highlightedIds,
  onSelect,
}: {
  entities: Entity[];
  highlightedIds: string[];
  onSelect: (entity: Entity) => void;
}) {
  const geometries = entities.flatMap((entity) => {
    const geometry = entity.geometry;
    if (!geometry || typeof geometry.type !== "string") return [];
    const coordinates = geometry.coordinates;
    const points = Array.isArray(coordinates)
      ? geometry.type === "Point"
        ? [coordinates]
        : geometry.type === "LineString"
          ? coordinates
          : Array.isArray(coordinates[0])
            ? coordinates[0]
            : []
      : [];
    return points.every((point) => Array.isArray(point) && point.length >= 2)
      ? [{ entity, type: geometry.type, points: points as number[][] }]
      : [];
  });
  const allPoints = geometries.flatMap((item) => item.points);
  if (allPoints.length === 0) return <p className="muted">No plottable geometry in this revision.</p>;
  const xs = allPoints.map((point) => point[0]);
  const ys = allPoints.map((point) => point[1]);
  const minX = xs.reduce((min, value) => (value < min ? value : min), xs[0]);
  const maxX = xs.reduce((max, value) => (value > max ? value : max), xs[0]);
  const minY = ys.reduce((min, value) => (value < min ? value : min), ys[0]);
  const maxY = ys.reduce((max, value) => (value > max ? value : max), ys[0]);
  const scaleX = (value: number) => 24 + ((value - minX) / (maxX - minX || 1)) * 452;
  const scaleY = (value: number) => 196 - ((value - minY) / (maxY - minY || 1)) * 172;
  return <svg className="geometry-preview" viewBox="0 0 500 220" role="img" aria-label="Site model geometry preview">
    {geometries.map(({ entity, type, points }) => {
      const selected = highlightedIds.includes(entity.id);
      const plotted = points.map((point) => `${scaleX(point[0])},${scaleY(point[1])}`).join(" ");
      if (type === "Point") return <circle key={entity.id} cx={scaleX(points[0][0])} cy={scaleY(points[0][1])} r={selected ? 7 : 5} className={selected ? "geometry-selected" : "geometry-point"} onClick={() => onSelect(entity)} />;
      return <polyline key={entity.id} points={plotted} className={selected ? "geometry-selected" : "geometry-line"} onClick={() => onSelect(entity)} />;
    })}
  </svg>;
}

export default function ProjectWorkspace() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [processingJobs, setProcessingJobs] = useState<ProcessingJob[]>([]);
  const [archivedFiles, setArchivedFiles] = useState<SourceFile[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [calculations, setCalculations] = useState<Calculation[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [questionText, setQuestionText] = useState("");
  const [questionHistory, setQuestionHistory] = useState<QuestionAnswerRecord[]>([]);
  const [projectName, setProjectName] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [calculationType, setCalculationType] = useState<CalculationType>("slope");
  const [perimeterGeometryType, setPerimeterGeometryType] = useState<PerimeterGeometryType>("LineString");
  const [coordinateUnit, setCoordinateUnit] = useState("ft");
  const [calculationUnit, setCalculationUnit] = useState("ft");
  const [startElevation, setStartElevation] = useState("100");
  const [endElevation, setEndElevation] = useState("104");
  const [horizontalDistance, setHorizontalDistance] = useState("100");
  const [geometry, setGeometry] = useState(defaultGeometry);
  const [secondGeometry, setSecondGeometry] = useState('{"type":"Point","coordinates":[3,4]}');
  const [message, setMessage] = useState("Ready for your first project.");
  const [loading, setLoading] = useState(false);
  const [filePendingDelete, setFilePendingDelete] = useState<SourceFile | null>(null);
  const [filePendingPurge, setFilePendingPurge] = useState<SourceFile | null>(null);
  const [acceptingFileId, setAcceptingFileId] = useState<string | null>(null);
  const [acceptedFileIds, setAcceptedFileIds] = useState<string[]>([]);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [highlightedEntityIds, setHighlightedEntityIds] = useState<string[]>([]);
  const [selectedCalculationId, setSelectedCalculationId] = useState<string | null>(null);
  const [selectedRevisionId, setSelectedRevisionId] = useState<string | null>(null);
  const [entityPage, setEntityPage] = useState(0);
  const entityPageSize = 200;
  const entityPageCount = Math.max(1, Math.ceil(entities.length / entityPageSize));
  const entityPageStart = entityPage * entityPageSize;
  const visibleEntities = entities.slice(entityPageStart, entityPageStart + entityPageSize);

  function revisionSourceFile(revision: Revision) {
    const sourceJobId = revision.source_job_ids?.[0];
    const job = processingJobs.find((item) => item.id === sourceJobId);
    return files.find((file) => file.id === job?.source_file_id);
  }

  async function loadProjectData(project: Project) {
    const [fileResponse, revisionResponse, calculationResponse, processingResponse] = await Promise.all([
      fetch(`${apiUrl}/projects/${project.id}/files`),
      fetch(`${apiUrl}/projects/${project.id}/site-model/revisions`),
      fetch(`${apiUrl}/projects/${project.id}/calculations`),
      fetch(`${apiUrl}/projects/${project.id}/processing`),
    ]);
    if (fileResponse.ok) setFiles(await fileResponse.json());
    const jobs = processingResponse.ok ? ((await processingResponse.json()) as ProcessingJob[]) : [];
    setProcessingJobs(jobs);
    if (revisionResponse.ok) {
      const data: Revision[] = await revisionResponse.json();
      setRevisions(data);
      if (data[0]) {
        setSelectedRevisionId(data[0].id);
        await loadEntities(project.id, data[0].id);
      } else {
        setSelectedRevisionId(null);
        setEntities([]);
      }
      const acceptedJobIds = new Set(data.flatMap((revision) => revision.source_job_ids ?? []));
      setAcceptedFileIds(jobs.filter((job) => acceptedJobIds.has(job.id)).map((job) => job.source_file_id));
    }
    if (calculationResponse.ok) setCalculations(await calculationResponse.json());
  }

  async function loadArchivedFiles() {
    const response = await fetch(`${apiUrl}/admin/files/archived`);
    if (response.ok) setArchivedFiles(await response.json());
  }

  async function selectProject(project: Project) {
    setSelectedProject(project);
    setEntities([]);
    setSummary(null);
    setQuestionHistory([]);
    await loadProjectData(project);
  }

  async function loadEntities(projectId: string, revisionId: string): Promise<Entity[]> {
    const response = await fetch(
      `${apiUrl}/projects/${projectId}/site-model/revisions/${revisionId}/entities?limit=500`,
    );
    if (!response.ok) return [];
    const data: Entity[] = await response.json();
    setEntities(data);
    setEntityPage(0);
    return data;
  }

  async function selectRevision(revisionId: string) {
    if (!selectedProject) return;
    setSelectedRevisionId(revisionId);
    setHighlightedEntityIds([]);
    setSelectedCalculationId(null);
    await loadEntities(selectedProject.id, revisionId);
  }

  async function selectCalculationResult(calculation: Calculation) {
    if (!selectedProject) return;
    setSelectedCalculationId(calculation.id);
    const geometries = calculationGeometries(calculation.inputs);
    if (geometries.length === 0) {
      setHighlightedEntityIds([]);
      setMessage(`${calculation.calculation_type} calculations do not reference specific site-model geometry.`);
      return;
    }
    let targetEntities = entities;
    if (calculation.revision_id && calculation.revision_id !== selectedRevisionId) {
      targetEntities = await loadEntities(selectedProject.id, calculation.revision_id);
      setSelectedRevisionId(calculation.revision_id);
    }
    const matches = targetEntities.filter(
      (entity) => entity.geometry && geometries.some((geometry) => geometriesEqual(geometry, entity.geometry)),
    );
    setHighlightedEntityIds(matches.map((entity) => entity.id));
    if (matches.length > 0) {
      const sources = matches.map((entity) => entity.source_reference?.file_name?.toString() ?? "unknown source");
      setMessage(`Highlighting source geometry from ${Array.from(new Set(sources)).join(", ")}.`);
    } else {
      setMessage("No matching source geometry was found in the site model for this calculation.");
    }
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectName.trim()) {
      setMessage("Enter a project name first.");
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(`${apiUrl}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: projectName.trim() }),
      });
      if (response.ok) {
        const project: Project = await response.json();
        setProjects((current) => [...current, project]);
        setProjectName("");
        await selectProject(project);
        setMessage("Project created. Add a source file to begin.");
      } else setMessage("Project could not be created.");
    } catch (error) {
      setMessage(error instanceof Error ? `Project request failed: ${error.message}` : "Project request failed.");
    } finally {
      setLoading(false);
    }
  }

  async function uploadFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject || !selectedFile) return;
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/files`, { method: "POST", body: formData });
      if (response.ok) {
        setSelectedFile(null);
        setMessage("File uploaded and queued for processing.");
        await loadProjectData(selectedProject);
        const input = document.getElementById("source-file") as HTMLInputElement | null;
        if (input) input.value = "";
      } else {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? "File could not be uploaded.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? `Upload request failed: ${error.message}` : "Upload request failed.");
    } finally {
      setLoading(false);
    }
  }

  async function processFile(file: SourceFile) {
    if (!selectedProject || busyAction === `process:${file.id}`) return;
    setBusyAction(`process:${file.id}`);
    setMessage(`Processing ${file.original_name}...`);
    try {
      const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/files/${file.id}/process`, { method: "POST" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `File processing failed (HTTP ${response.status}).`);
        return;
      }
      const job: { status: string } = await response.json();
      setMessage(`${file.original_name} processing status: ${job.status}.`);
      await loadProjectData(selectedProject);
    } catch (error) {
      setMessage(error instanceof Error ? `Processing request failed: ${error.message}` : "Processing request failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function deleteFile(file: SourceFile) {
    if (!selectedProject) return;
    setFilePendingDelete(file);
  }

  async function confirmDeleteFile() {
    if (!selectedProject || !filePendingDelete) return;
    const file = filePendingDelete;
    if (busyAction === `delete:${file.id}`) return;
    setBusyAction(`delete:${file.id}`);
    setMessage(`Archiving ${file.original_name}...`);
    try {
      const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/files/${file.id}`, { method: "DELETE" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `File archive failed (HTTP ${response.status}).`);
        return;
      }
      setFiles((current) => current.filter((item) => item.id !== file.id));
      setMessage(`${file.original_name} was archived.`);
      await loadArchivedFiles();
    } catch (error) {
      setMessage(error instanceof Error ? `Archive request failed: ${error.message}` : "Archive request failed.");
    } finally {
      setBusyAction(null);
      setFilePendingDelete(null);
    }
  }

  async function restoreArchivedFile(file: SourceFile) {
    if (busyAction === `restore:${file.id}`) return;
    setBusyAction(`restore:${file.id}`);
    setMessage(`Restoring ${file.original_name}...`);
    try {
      const response = await fetch(`${apiUrl}/admin/files/${file.id}/restore`, { method: "POST" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `Restore failed (HTTP ${response.status}).`);
        return;
      }
      setArchivedFiles((current) => current.filter((item) => item.id !== file.id));
      setMessage(`${file.original_name} was restored.`);
      if (selectedProject) await loadProjectData(selectedProject);
    } catch (error) {
      setMessage(error instanceof Error ? `Restore request failed: ${error.message}` : "Restore request failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function purgeArchivedFile(file: SourceFile) {
    setFilePendingPurge(file);
  }

  async function confirmPurgeArchivedFile() {
    if (!filePendingPurge) return;
    const file = filePendingPurge;
    if (busyAction === `purge:${file.id}`) return;
    setBusyAction(`purge:${file.id}`);
    setMessage(`Permanently deleting ${file.original_name}...`);
    try {
      const response = await fetch(`${apiUrl}/admin/files/${file.id}`, { method: "DELETE" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `Purge failed (HTTP ${response.status}).`);
        return;
      }
      setArchivedFiles((current) => current.filter((item) => item.id !== file.id));
      setMessage(`${file.original_name} was permanently deleted.`);
    } catch (error) {
      setMessage(error instanceof Error ? `Purge request failed: ${error.message}` : "Purge request failed.");
    } finally {
      setBusyAction(null);
      setFilePendingPurge(null);
    }
  }

  async function acceptRevision(file: SourceFile) {
    if (!selectedProject || acceptingFileId === file.id || acceptedFileIds.includes(file.id)) return;
    setAcceptingFileId(file.id);
    setMessage(`Accepting revision for ${file.original_name}...`);
    try {
      const response = await fetch(
        `${apiUrl}/projects/${selectedProject.id}/site-model/revisions/from-extraction/${file.id}`,
        { method: "POST" },
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `Revision could not be accepted (HTTP ${response.status}).`);
        return;
      }
      const revision: Revision = await response.json();
      setRevisions((current) => [revision, ...current.filter((item) => item.id !== revision.id)]);
      setAcceptedFileIds((current) => current.includes(file.id) ? current : [...current, file.id]);
      setSelectedRevisionId(revision.id);
      await loadEntities(selectedProject.id, revision.id);
      setMessage(`Revision ${revision.revision_number} is ready in the site model.`);
    } catch (error) {
      setMessage(error instanceof Error ? `Revision request failed: ${error.message}` : "Revision request failed.");
    } finally {
      setAcceptingFileId(null);
    }
  }

  async function createCalculation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject) return;
    let inputs: Record<string, unknown>;
    try {
      if (calculationType === "slope") {
        inputs = { start_elevation: Number(startElevation), end_elevation: Number(endElevation), horizontal_distance: Number(horizontalDistance) };
      } else if (calculationType === "distance") {
        inputs = { first_geometry: JSON.parse(geometry), second_geometry: JSON.parse(secondGeometry) };
      } else inputs = { geometry: JSON.parse(geometry) };
    } catch {
      setMessage("Geometry input must be valid JSON.");
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/calculations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ calculation_type: calculationType, inputs, coordinate_unit: coordinateUnit, unit: calculationUnit, revision_id: revisions[0]?.id }),
      });
      if (response.ok) {
        const calculation: Calculation = await response.json();
        setCalculations((current) => [calculation, ...current]);
        setMessage(`${calculationType} calculation completed.`);
      } else {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? "Calculation could not be completed.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? `Calculation request failed: ${error.message}` : "Calculation request failed.");
    } finally {
      setLoading(false);
    }
  }

  async function requestSummary() {
    if (!selectedProject) return;
    setLoading(true);
    try {
      const query = selectedRevisionId ? `?revision_id=${selectedRevisionId}` : "";
      const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/summaries${query}`, { method: "POST" });
      if (response.ok) {
        setSummary(await response.json());
        setMessage("Site summary generated.");
      } else {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? "Summary could not be generated.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? `Summary request failed: ${error.message}` : "Summary request failed.");
    } finally {
      setLoading(false);
    }
  }

  async function askQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject || !questionText.trim()) return;
    setLoading(true);
    try {
      const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: questionText.trim(), revision_id: selectedRevisionId }),
      });
      if (response.ok) {
        const record: QuestionAnswerRecord = await response.json();
        setQuestionHistory((current) => [record, ...current]);
        setQuestionText("");
        setMessage("Question answered.");
      } else {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? "Question could not be answered.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? `Question request failed: ${error.message}` : "Question request failed.");
    } finally {
      setLoading(false);
    }
  }

  function changeCalculationType(type: CalculationType) {
    setCalculationType(type);
    if (type === "area") setGeometry(areaGeometry);
    else if (type === "perimeter") {
      setPerimeterGeometryType("LineString");
      setGeometry(perimeterGeometry);
    }
    else if (type === "distance") setGeometry(defaultGeometry);
  }

  function changePerimeterGeometryType(type: PerimeterGeometryType) {
    setPerimeterGeometryType(type);
    setGeometry(type === "Polygon" ? polygonPerimeterGeometry : perimeterGeometry);
  }

  useEffect(() => {
    async function loadInitialProjects() {
      const response = await fetch(`${apiUrl}/projects`);
      if (!response.ok) {
        setMessage("Could not load projects. Check that the API is running.");
        return;
      }
      const data: Project[] = await response.json();
      setProjects(data);
      if (data.length > 0) {
        const project = data[0];
        setSelectedProject(project);
        const [fileResponse, revisionResponse, calculationResponse, processingResponse] = await Promise.all([
          fetch(`${apiUrl}/projects/${project.id}/files`),
          fetch(`${apiUrl}/projects/${project.id}/site-model/revisions`),
          fetch(`${apiUrl}/projects/${project.id}/calculations`),
          fetch(`${apiUrl}/projects/${project.id}/processing`),
        ]);
        if (fileResponse.ok) setFiles(await fileResponse.json());
        const jobs = processingResponse.ok ? ((await processingResponse.json()) as ProcessingJob[]) : [];
        setProcessingJobs(jobs);
        if (revisionResponse.ok) {
          const revisionData: Revision[] = await revisionResponse.json();
          setRevisions(revisionData);
          if (revisionData[0]) setSelectedRevisionId(revisionData[0].id);
          else setSelectedRevisionId(null);
          const acceptedJobIds = new Set(revisionData.flatMap((revision) => revision.source_job_ids ?? []));
          setAcceptedFileIds(jobs.filter((job) => acceptedJobIds.has(job.id)).map((job) => job.source_file_id));
          if (revisionData[0]) {
            const entityResponse = await fetch(
              `${apiUrl}/projects/${project.id}/site-model/revisions/${revisionData[0].id}/entities?limit=500`,
            );
            if (entityResponse.ok) setEntities(await entityResponse.json());
          } else setEntities([]);
        }
        if (calculationResponse.ok) setCalculations(await calculationResponse.json());
      }
    }

    async function loadInitialData() {
      await loadInitialProjects();
      const archiveResponse = await fetch(`${apiUrl}/admin/files/archived`);
      if (archiveResponse.ok) setArchivedFiles(await archiveResponse.json());
    }

    void loadInitialData();
  }, []);

  return (
    <main className="workspace">
      <header className="topbar">
        <div><p className="eyebrow">Civil engineering intelligence</p><h1>Project workspace</h1></div>
        <span className="status">Phase 6 active</span>
      </header>
      <section className="workspace-grid">
        <aside className="project-panel">
          <p className="eyebrow">Projects</p>
          <form className="create-form" onSubmit={createProject}>
            <label htmlFor="project-name">New project</label>
            <div className="input-row"><input id="project-name" value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Oak Street Site" maxLength={200} /><button type="submit" disabled={loading} aria-label="Create project">+</button></div>
          </form>
          <div className="project-list">
            {projects.length === 0 && <p className="muted">No projects yet.</p>}
            {projects.map((project) => <button className={`project-item ${selectedProject?.id === project.id ? "selected" : ""}`} key={project.id} onClick={() => void selectProject(project)}><span>{project.name}</span><small>{project.default_unit_system}</small></button>)}
          </div>
          <section className="admin-panel"><p className="eyebrow">Admin archive</p><p className="muted">{archivedFiles.length} archived file{archivedFiles.length === 1 ? "" : "s"}</p>{archivedFiles.map((file) => <div className="archive-row" key={file.id}><strong>{file.original_name}</strong><div><button disabled={busyAction === `restore:${file.id}`} onClick={() => void restoreArchivedFile(file)}>{busyAction === `restore:${file.id}` ? "Restoring..." : "Restore"}</button><button className="danger-button" disabled={busyAction === `purge:${file.id}`} onClick={() => void purgeArchivedFile(file)}>{busyAction === `purge:${file.id}` ? "Purging..." : "Purge"}</button></div></div>)}</section>
        </aside>
        <section className="project-detail">
          {selectedProject ? <>
            <div className="detail-heading"><div><p className="eyebrow">Active project</p><h2>{selectedProject.name}</h2></div><span className="project-mark">06</span></div>
            <div className="upload-panel"><div><p className="eyebrow">Source files</p><h3>Bring the plan into focus.</h3><p className="muted">PDF, DXF, CSV, TXT, TIFF, and LandXML files up to 50 MB.</p></div><form className="upload-form" onSubmit={uploadFile}><label className="file-picker" htmlFor="source-file"><span>{selectedFile?.name ?? "Choose a source file"}</span><input id="source-file" type="file" accept=".pdf,.dxf,.csv,.txt,.tif,.tiff,.xml" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} /></label><button type="submit" disabled={loading || selectedFile === null}>Upload file</button></form></div>
            <div className="file-list"><div className="list-heading"><span>File</span><span>Status / actions</span></div>{files.length === 0 && <p className="muted">Uploaded files will appear here.</p>}{files.map((file) => <div className="file-row" key={file.id}><div><strong>{file.original_name}</strong><small>{Math.ceil(file.size_bytes / 1024)} KB · {file.checksum}</small>{file.status === "failed" && file.error_message && <small className="file-error">{file.error_message}</small>}</div><div className="file-status"><span>{processingStatusLabel(file.status)}</span>{file.status === "queued" && <button disabled={busyAction === `process:${file.id}`} onClick={() => void processFile(file)}>{busyAction === `process:${file.id}` ? "Processing..." : "Process"}</button>}{(file.status === "failed" || file.status === "processing") && <button disabled={busyAction === `process:${file.id}`} onClick={() => void processFile(file)}>{busyAction === `process:${file.id}` ? "Processing..." : "Retry"}</button>}{file.status === "completed" && (acceptedFileIds.includes(file.id) ? <button disabled>Revision accepted</button> : <button disabled={acceptingFileId === file.id} onClick={() => void acceptRevision(file)}>{acceptingFileId === file.id ? "Accepting..." : "Accept revision"}</button>)}<button className="danger-button" disabled={busyAction === `delete:${file.id}`} onClick={() => void deleteFile(file)}>Delete</button></div></div>)}</div>
            <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Site model</p><h3>Revision geometry</h3>{revisions.length > 0 && <label className="revision-selector">Revision<select value={selectedRevisionId ?? ""} onChange={(event) => void selectRevision(event.target.value)}>{revisions.map((revision) => { const sourceFile = revisionSourceFile(revision); return <option key={revision.id} value={revision.id}>Revision {revision.revision_number} · {sourceFile?.original_name ?? "Unknown file"} · {sourceFile?.checksum ?? "Unknown identifier"}</option>; })}</select></label>}</div><span className="section-count">{entities.length} entities</span></div>{revisions.length === 0 ? <p className="muted">Process a file and accept a revision to inspect extracted geometry.</p> : <><GeometryPreview entities={entities} highlightedIds={highlightedEntityIds} onSelect={(entity) => { setHighlightedEntityIds([entity.id]); setSelectedCalculationId(null); setMessage(`Selected ${entity.entity_type} from ${entity.source_reference?.file_name?.toString() ?? "unknown source"}.`); }} /><div className="entity-grid">{visibleEntities.map((entity) => <button className={`entity-card ${entity.validation_status} ${highlightedEntityIds.includes(entity.id) ? "entity-selected" : ""}`} key={entity.id} onClick={() => { setHighlightedEntityIds([entity.id]); setSelectedCalculationId(null); }}><strong>{entity.entity_type}</strong><span>{entity.validation_status}</span>{entity.properties?.semantic_type ? <span className="semantic-type">{String(entity.properties.semantic_type).replace(/_/g, " ")}{entity.properties?.zoning ? ` · ${entity.properties.zoning}` : ""}</span> : null}<small>{entity.entity_type === "key_phrase" ? `"${entity.properties?.phrase}"` : entity.source_reference?.file_name?.toString() ?? "No source reference"}</small></button>)}</div>{entities.length > 0 && <div className="entity-pagination"><span className="muted">Showing {entityPageStart + 1}-{Math.min(entityPageStart + entityPageSize, entities.length)} of {entities.length} entities.</span><div className="entity-pagination-controls"><button className="secondary-button" disabled={entityPage === 0} onClick={() => setEntityPage((page) => Math.max(0, page - 1))}><span aria-hidden="true">←</span> Previous</button><span>Page {entityPage + 1} of {entityPageCount}</span><button className="secondary-button" disabled={entityPage >= entityPageCount - 1} onClick={() => setEntityPage((page) => Math.min(entityPageCount - 1, page + 1))}>Next <span aria-hidden="true">→</span></button></div></div>}</>}</section>
            <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Calculations</p><h3>Run a deterministic check.</h3><p className="calculation-help">Distance uses two geometries. Area accepts Polygon, MultiPolygon, or Circle JSON. Perimeter accepts LineString, Polygon, or Circle JSON. A Circle uses center and radius in the selected coordinate unit.</p></div></div><form className="calculation-form" onSubmit={createCalculation}><label>Calculation<select value={calculationType} onChange={(event) => changeCalculationType(event.target.value as CalculationType)}><option value="slope">Slope</option><option value="distance">Distance</option><option value="area">Area</option><option value="perimeter">Perimeter</option></select></label><label>Coordinate unit<select value={coordinateUnit} onChange={(event) => setCoordinateUnit(event.target.value)}><option value="ft">Feet</option><option value="m">Meters</option><option value="in">Inches</option></select></label><label>Output unit<select value={calculationUnit} onChange={(event) => setCalculationUnit(event.target.value)}><option value="ft">Feet</option><option value="m">Meters</option><option value="in">Inches</option></select></label>{calculationType === "slope" ? <div className="calculation-fields"><label>Start elevation<input value={startElevation} onChange={(event) => setStartElevation(event.target.value)} /></label><label>End elevation<input value={endElevation} onChange={(event) => setEndElevation(event.target.value)} /></label><label>Horizontal distance<input value={horizontalDistance} onChange={(event) => setHorizontalDistance(event.target.value)} /></label></div> : <div className="geometry-fields">{calculationType === "perimeter" && <label>Perimeter geometry<select value={perimeterGeometryType} onChange={(event) => changePerimeterGeometryType(event.target.value as PerimeterGeometryType)}><option value="LineString">LineString (open path)</option><option value="Polygon">Polygon (closed boundary)</option></select></label>}<label>Geometry JSON<textarea value={geometry} onChange={(event) => setGeometry(event.target.value)} rows={3} /></label>{calculationType === "distance" && <label>Second geometry JSON<textarea value={secondGeometry} onChange={(event) => setSecondGeometry(event.target.value)} rows={3} /></label>}</div>}<button type="submit" disabled={loading}>Run calculation</button></form>{calculations.length > 0 && <div className="calculation-results">{calculations.slice(0, 5).map((calculation) => <button type="button" className={`result-row ${selectedCalculationId === calculation.id ? "result-selected" : ""}`} key={calculation.id} onClick={() => void selectCalculationResult(calculation)}><strong>{calculation.calculation_type}</strong><span>{calculation.result.toFixed(3)} {calculation.unit}</span><small>{calculation.formula}</small></button>)}</div>}</section>
            <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Site intelligence</p><h3>Summarize and ask questions.</h3><p className="calculation-help">Answers are grounded in the accepted site model and calculations. AI-generated content is clearly labeled and never invents a measurement.</p></div><button type="button" className="secondary-button" disabled={loading || revisions.length === 0} onClick={() => void requestSummary()}>Request site summary</button></div>{summary && <div className="summary-card"><p>{summary.content.summary}</p><dl><div><dt>Grading</dt><dd>{summary.content.grading}</dd></div><div><dt>Drainage</dt><dd>{summary.content.drainage}</dd></div><div><dt>Utilities</dt><dd>{summary.content.utilities}</dd></div></dl>{summary.content.attention_flags.length > 0 && <div className="attention-flags"><strong>Attention</strong><ul>{summary.content.attention_flags.map((flag, index) => <li key={index}>{flag}</li>)}</ul></div>}<p className="ai-label">AI-generated · {summary.content.limitations.join(" ")}</p></div>}<form className="question-form" onSubmit={askQuestion}><label>Ask a question<input value={questionText} onChange={(event) => setQuestionText(event.target.value)} placeholder="What is the setback distance?" maxLength={2000} /></label><button type="submit" className="secondary-button" disabled={loading || !questionText.trim()}>Ask</button></form>{questionHistory.length > 0 && <div className="qa-list">{questionHistory.map((record) => <div className="qa-card" key={record.id}><p className="qa-question">{record.question}</p><p className="qa-answer">{record.answer.answer}</p><small className="ai-label">AI-generated · {record.answer.method} · confidence {record.answer.confidence.toFixed(2)}</small>{record.answer.limitations && record.answer.limitations.length > 0 && <small className="qa-limitations">{record.answer.limitations.join(" ")}</small>}</div>)}</div>}</section>
            {filePendingDelete && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title"><p className="eyebrow">Archive file</p><h3 id="delete-title">Remove {filePendingDelete.original_name}?</h3><p className="muted">The file will be hidden from this workspace and moved to the archive. Accepted revisions and calculations will remain.</p><div className="modal-actions"><button className="secondary-button" disabled={busyAction === `delete:${filePendingDelete.id}`} onClick={() => setFilePendingDelete(null)}>Cancel</button><button className="danger-button" disabled={busyAction === `delete:${filePendingDelete.id}`} onClick={() => void confirmDeleteFile()}>{busyAction === `delete:${filePendingDelete.id}` ? "Archiving..." : "Archive file"}</button></div></section></div>}
            {filePendingPurge && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="purge-title"><p className="eyebrow">Permanent purge</p><h3 id="purge-title">Permanently delete {filePendingPurge.original_name}?</h3><p className="muted">This removes the archived file and its metadata. Accepted revisions and calculations remain, but the original source cannot be restored.</p><div className="modal-actions"><button className="secondary-button" disabled={busyAction === `purge:${filePendingPurge.id}`} onClick={() => setFilePendingPurge(null)}>Cancel</button><button className="danger-button" disabled={busyAction === `purge:${filePendingPurge.id}`} onClick={() => void confirmPurgeArchivedFile()}>{busyAction === `purge:${filePendingPurge.id}` ? "Purging..." : "Permanently delete"}</button></div></section></div>}
          </> : <div className="empty-detail"><p className="eyebrow">Start here</p><h2>Create your first project.</h2><p className="muted">Your project becomes the home for plans, source files, measured results, and site-model revisions.</p></div>}
          <p className="message" role="status">{message}</p>
        </section>
      </section>
    </main>
  );
}
