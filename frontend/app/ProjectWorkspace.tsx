"use client";

import { FormEvent, useEffect, useState } from "react";

type Project = { id: string; name: string; description: string | null; default_unit_system: string };
type SourceFile = { id: string; original_name: string; size_bytes: number; status: string; checksum: string };
type Revision = { id: string; revision_number: number; notes: string | null };
type Entity = { id: string; entity_type: string; geometry: Record<string, unknown> | null; validation_status: string; source_reference: Record<string, unknown> | null };
type Calculation = { id: string; calculation_type: string; result: number; unit: string; formula: string; assumptions: unknown[] | null };

type CalculationType = "slope" | "distance" | "area" | "perimeter";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const defaultGeometry = '{"type":"Point","coordinates":[0,0]}';

function GeometryPreview({
  entities,
  selectedId,
  onSelect,
}: {
  entities: Entity[];
  selectedId: string | null;
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
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const scaleX = (value: number) => 24 + ((value - minX) / (maxX - minX || 1)) * 452;
  const scaleY = (value: number) => 196 - ((value - minY) / (maxY - minY || 1)) * 172;
  return <svg className="geometry-preview" viewBox="0 0 500 220" role="img" aria-label="Site model geometry preview">
    {geometries.map(({ entity, type, points }) => {
      const selected = entity.id === selectedId;
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
  const [archivedFiles, setArchivedFiles] = useState<SourceFile[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [calculations, setCalculations] = useState<Calculation[]>([]);
  const [projectName, setProjectName] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [calculationType, setCalculationType] = useState<CalculationType>("slope");
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
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);

  async function loadProjectData(project: Project) {
    const [fileResponse, revisionResponse, calculationResponse] = await Promise.all([
      fetch(`${apiUrl}/projects/${project.id}/files`),
      fetch(`${apiUrl}/projects/${project.id}/site-model/revisions`),
      fetch(`${apiUrl}/projects/${project.id}/calculations`),
    ]);
    if (fileResponse.ok) setFiles(await fileResponse.json());
    if (revisionResponse.ok) {
      const data: Revision[] = await revisionResponse.json();
      setRevisions(data);
      if (data[0]) await loadEntities(project.id, data[0].id);
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
    await loadProjectData(project);
  }

  async function loadEntities(projectId: string, revisionId: string) {
    const response = await fetch(`${apiUrl}/projects/${projectId}/site-model/revisions/${revisionId}/entities`);
    if (response.ok) setEntities(await response.json());
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectName.trim()) {
      setMessage("Enter a project name first.");
      return;
    }
    setLoading(true);
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
    setLoading(false);
  }

  async function uploadFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject || !selectedFile) return;
    setLoading(true);
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
    setLoading(false);
  }

  async function processFile(file: SourceFile) {
    if (!selectedProject) return;
    const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/files/${file.id}/process`, { method: "POST" });
    if (response.ok) {
      const job: { status: string } = await response.json();
      setMessage(`${file.original_name} processing status: ${job.status}.`);
      await loadProjectData(selectedProject);
    } else setMessage("File processing failed to start.");
  }

  async function deleteFile(file: SourceFile) {
    if (!selectedProject) return;
    setFilePendingDelete(file);
  }

  async function confirmDeleteFile() {
    if (!selectedProject || !filePendingDelete) return;
    const file = filePendingDelete;
    const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/files/${file.id}`, { method: "DELETE" });
    if (response.ok) {
      setFiles((current) => current.filter((item) => item.id !== file.id));
      setMessage(`${file.original_name} was deleted.`);
    } else setMessage("File could not be deleted.");
    setFilePendingDelete(null);
    await loadArchivedFiles();
  }

  async function restoreArchivedFile(file: SourceFile) {
    const response = await fetch(`${apiUrl}/admin/files/${file.id}/restore`, { method: "POST" });
    if (response.ok) {
      setArchivedFiles((current) => current.filter((item) => item.id !== file.id));
      setMessage(`${file.original_name} was restored.`);
      if (selectedProject) await loadProjectData(selectedProject);
    }
  }

  async function purgeArchivedFile(file: SourceFile) {
    setFilePendingPurge(file);
  }

  async function confirmPurgeArchivedFile() {
    if (!filePendingPurge) return;
    const file = filePendingPurge;
    const response = await fetch(`${apiUrl}/admin/files/${file.id}`, { method: "DELETE" });
    if (response.ok) setArchivedFiles((current) => current.filter((item) => item.id !== file.id));
    setFilePendingPurge(null);
  }

  async function acceptRevision(file: SourceFile) {
    if (!selectedProject) return;
    const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/site-model/revisions/from-extraction/${file.id}`, { method: "POST" });
    if (response.ok) {
      const revision: Revision = await response.json();
      setRevisions((current) => [revision, ...current]);
      await loadEntities(selectedProject.id, revision.id);
      setMessage(`Revision ${revision.revision_number} accepted into the site model.`);
    } else setMessage("Process the file successfully before accepting a revision.");
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
    setLoading(false);
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
        const [fileResponse, revisionResponse, calculationResponse] = await Promise.all([
          fetch(`${apiUrl}/projects/${project.id}/files`),
          fetch(`${apiUrl}/projects/${project.id}/site-model/revisions`),
          fetch(`${apiUrl}/projects/${project.id}/calculations`),
        ]);
        if (fileResponse.ok) setFiles(await fileResponse.json());
        if (revisionResponse.ok) {
          const revisionData: Revision[] = await revisionResponse.json();
          setRevisions(revisionData);
          if (revisionData[0]) {
            const entityResponse = await fetch(
              `${apiUrl}/projects/${project.id}/site-model/revisions/${revisionData[0].id}/entities`,
            );
            if (entityResponse.ok) setEntities(await entityResponse.json());
          }
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
          <section className="admin-panel"><p className="eyebrow">Admin archive</p><p className="muted">{archivedFiles.length} archived file{archivedFiles.length === 1 ? "" : "s"}</p>{archivedFiles.map((file) => <div className="archive-row" key={file.id}><strong>{file.original_name}</strong><div><button onClick={() => void restoreArchivedFile(file)}>Restore</button><button className="danger-button" onClick={() => void purgeArchivedFile(file)}>Purge</button></div></div>)}</section>
        </aside>
        <section className="project-detail">
          {selectedProject ? <>
            <div className="detail-heading"><div><p className="eyebrow">Active project</p><h2>{selectedProject.name}</h2></div><span className="project-mark">06</span></div>
            <div className="upload-panel"><div><p className="eyebrow">Source files</p><h3>Bring the plan into focus.</h3><p className="muted">PDF, DXF, CSV, TXT, and TIFF files up to 50 MB.</p></div><form className="upload-form" onSubmit={uploadFile}><label className="file-picker" htmlFor="source-file"><span>{selectedFile?.name ?? "Choose a source file"}</span><input id="source-file" type="file" accept=".pdf,.dxf,.csv,.txt,.tif,.tiff" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} /></label><button type="submit" disabled={loading || selectedFile === null}>Upload file</button></form></div>
            <div className="file-list"><div className="list-heading"><span>File</span><span>Status / actions</span></div>{files.length === 0 && <p className="muted">Uploaded files will appear here.</p>}{files.map((file) => <div className="file-row" key={file.id}><div><strong>{file.original_name}</strong><small>{Math.ceil(file.size_bytes / 1024)} KB · {file.checksum.slice(0, 10)}...</small></div><div className="file-status"><span>{file.status}</span>{file.status === "queued" && <button onClick={() => void processFile(file)}>Process</button>}{file.status === "completed" && <button onClick={() => void acceptRevision(file)}>Accept revision</button>}<button className="danger-button" onClick={() => void deleteFile(file)}>Delete</button></div></div>)}</div>
            <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Site model</p><h3>Revision geometry</h3></div><span className="section-count">{entities.length} entities</span></div>{revisions.length === 0 ? <p className="muted">Process a file and accept a revision to inspect extracted geometry.</p> : <><GeometryPreview entities={entities} selectedId={selectedEntityId} onSelect={(entity) => { setSelectedEntityId(entity.id); setMessage(`Selected ${entity.entity_type} from ${entity.source_reference?.file_name?.toString() ?? "unknown source"}.`); }} /><div className="entity-grid">{entities.map((entity) => <button className={`entity-card ${entity.validation_status} ${selectedEntityId === entity.id ? "entity-selected" : ""}`} key={entity.id} onClick={() => setSelectedEntityId(entity.id)}><strong>{entity.entity_type}</strong><span>{entity.validation_status}</span><small>{entity.source_reference?.file_name?.toString() ?? "No source reference"}</small></button>)}</div></>}</section>
            <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Calculations</p><h3>Run a deterministic check.</h3><p className="calculation-help">Distance uses two geometries. Area accepts Polygon, MultiPolygon, or Circle JSON. Perimeter accepts LineString, Polygon, or Circle JSON. A Circle uses center and radius in the selected coordinate unit.</p></div></div><form className="calculation-form" onSubmit={createCalculation}><label>Calculation<select value={calculationType} onChange={(event) => setCalculationType(event.target.value as CalculationType)}><option value="slope">Slope</option><option value="distance">Distance</option><option value="area">Area</option><option value="perimeter">Perimeter</option></select></label><label>Coordinate unit<select value={coordinateUnit} onChange={(event) => setCoordinateUnit(event.target.value)}><option value="ft">Feet</option><option value="m">Meters</option><option value="in">Inches</option></select></label><label>Output unit<select value={calculationUnit} onChange={(event) => setCalculationUnit(event.target.value)}><option value="ft">Feet</option><option value="m">Meters</option><option value="in">Inches</option></select></label>{calculationType === "slope" ? <div className="calculation-fields"><label>Start elevation<input value={startElevation} onChange={(event) => setStartElevation(event.target.value)} /></label><label>End elevation<input value={endElevation} onChange={(event) => setEndElevation(event.target.value)} /></label><label>Horizontal distance<input value={horizontalDistance} onChange={(event) => setHorizontalDistance(event.target.value)} /></label></div> : <div className="geometry-fields"><label>Geometry JSON<textarea value={geometry} onChange={(event) => setGeometry(event.target.value)} rows={3} /></label>{calculationType === "distance" && <label>Second geometry JSON<textarea value={secondGeometry} onChange={(event) => setSecondGeometry(event.target.value)} rows={3} /></label>}</div>}<button type="submit" disabled={loading}>Run calculation</button></form>{calculations.length > 0 && <div className="calculation-results">{calculations.slice(0, 5).map((calculation) => <div className="result-row" key={calculation.id}><strong>{calculation.calculation_type}</strong><span>{calculation.result.toFixed(3)} {calculation.unit}</span><small>{calculation.formula}</small></div>)}</div>}</section>
            <p className="message" role="status">{message}</p>
            {filePendingDelete && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title"><p className="eyebrow">Archive file</p><h3 id="delete-title">Remove {filePendingDelete.original_name}?</h3><p className="muted">The file will be hidden from this workspace and moved to the archive. Accepted revisions and calculations will remain.</p><div className="modal-actions"><button className="secondary-button" onClick={() => setFilePendingDelete(null)}>Cancel</button><button className="danger-button" onClick={() => void confirmDeleteFile()}>Archive file</button></div></section></div>}
            {filePendingPurge && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="purge-title"><p className="eyebrow">Permanent purge</p><h3 id="purge-title">Permanently delete {filePendingPurge.original_name}?</h3><p className="muted">This removes the archived file and its metadata. Accepted revisions and calculations remain, but the original source cannot be restored.</p><div className="modal-actions"><button className="secondary-button" onClick={() => setFilePendingPurge(null)}>Cancel</button><button className="danger-button" onClick={() => void confirmPurgeArchivedFile()}>Permanently delete</button></div></section></div>}
          </> : <div className="empty-detail"><p className="eyebrow">Start here</p><h2>Create your first project.</h2><p className="muted">Your project becomes the home for plans, source files, measured results, and site-model revisions.</p></div>}
        </section>
      </section>
    </main>
  );
}
