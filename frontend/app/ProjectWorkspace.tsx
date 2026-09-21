"use client";

import { DragEvent, FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { apiFetch, apiUrl, errorMessage } from "./api";
import { useAuth } from "./AuthContext";

type Project = { id: string; name: string; description: string | null; default_unit_system: string; owner_id: string | null };
type ProjectMember = { id: string; user_id: string; username: string; role: "admin" | "power_user" | "user" };
type SourceFile = { id: string; original_name: string; size_bytes: number; status: string; checksum: string; error_message: string | null; document_group_id: string; superseded_by_id: string | null; uploaded_at: string };
// An archived project/file is auto-purged once purge_scheduled_at passes,
// unless it's restored or manually purged first; purge_warning is true once
// that's within the server's configured warning window.
type ArchivedProject = Project & { purge_scheduled_at: string; purge_warning: boolean };
type ArchivedSourceFile = SourceFile & { purge_scheduled_at: string; purge_warning: boolean };
type ProcessingJob = { id: string; source_file_id: string; status: string; warnings: string[] | null };
type Revision = { id: string; revision_number: number; created_at: string; source_job_ids: string[] | null; notes: string | null };
type Entity = { id: string; entity_type: string; geometry: Record<string, unknown> | null; properties: Record<string, unknown> | null; validation_status: string; source_reference: Record<string, unknown> | null };
type Calculation = { id: string; calculation_type: string; result: number; unit: string; formula: string; assumptions: unknown[] | null; revision_id: string | null; inputs: Record<string, unknown> };
type SummaryContent = { summary: string; grading: string; drainage: string; utilities: string; attention_flags: string[]; limitations: string[] };
type Summary = { id: string; content: SummaryContent; created_at: string; revision_ids: string[] | null };
type Answer = { answer: string; method: string; confidence: number; result?: number; unit?: string; formula?: string; limitations?: string[]; source_references?: (Record<string, unknown> | null)[]; source_excerpts?: string[] };
type QuestionAnswerRecord = { id: string; question: string; intent: string; answer: Answer; created_at: string; revision_ids: string[] | null };

type CalculationType = "slope" | "distance" | "area" | "perimeter";
type PerimeterGeometryType = "LineString" | "Polygon";

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

function processingStatusLabel(status: string, hasWarnings: boolean) {
  if (status === "completed") return hasWarnings ? "Processing completed with warnings" : "Processing completed";
  if (status === "failed") return "Processing failed";
  if (status === "processing") return "Processing...";
  if (status === "queued") return "Ready to process";
  return status;
}

function latestJobWarnings(jobs: ProcessingJob[], fileId: string): string[] {
  return jobs.find((job) => job.source_file_id === fileId)?.warnings ?? [];
}

const MAX_DISPLAYED_WARNINGS = 3;

function summarizeWarnings(warnings: string[]): string[] {
  const unique = Array.from(new Set(warnings));
  if (unique.length <= MAX_DISPLAYED_WARNINGS) return unique;
  const shown = unique.slice(0, MAX_DISPLAYED_WARNINGS);
  return [...shown, `+${unique.length - MAX_DISPLAYED_WARNINGS} more warning(s)`];
}

const ALLOWED_UPLOAD_EXTENSIONS = new Set(["pdf", "dxf", "csv", "txt", "tif", "tiff", "xml"]);

function fileExtension(name: string): string {
  const parts = name.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

function fileTypeGroup(name: string): string {
  const extension = fileExtension(name);
  return extension === "tiff" ? "tif" : extension;
}

type BatchResult = { name: string; ok: boolean; detail: string; retryable?: boolean; reason?: "duplicate" | "rejected"; size?: number; skipped?: boolean };

// Phase 12: every setMessage() call also becomes one of these. This is what
// actually fixes the reported bug: a later action's status no longer
// erases an earlier one's, since both remain visible in the log instead of
// only the single most recent line. Kept locally for instant, no-round-trip
// feedback; also persisted server-side (POST/GET .../activity-events) when
// a project is selected, so the history survives a reload and is visible
// to any other member of the project -- an actual audit trail, not just a
// per-tab convenience. Before a project exists (e.g. "Ready for your first
// project.", a failed project-list load), there's nothing to attach it to,
// so it stays local-only, same as before persistence existed.
type ActivityEvent = { id: string; timestamp: number; text: string; details: BatchResult[] | null; successLabel: string };

// The shape ActivityEventResponse (schemas.py) actually returns.
type PersistedActivityEvent = {
  id: string;
  text: string;
  details: BatchResult[] | null;
  success_label: string;
  created_at: string;
};

function activityEventFromPersisted(event: PersistedActivityEvent): ActivityEvent {
  return {
    id: event.id,
    timestamp: new Date(event.created_at).getTime(),
    text: event.text,
    details: event.details,
    successLabel: event.success_label,
  };
}

const ACTIVITY_LOG_LIMIT = 50;

function formatEventTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Module-level, not a component-local helper: Date.now() is impure, and the
// react-hooks/purity lint rule flags an impure call found anywhere inside a
// component's own function body (including a nested function declaration
// like setMessage), even though setMessage itself only ever runs from event
// handlers, never during render.
function makeActivityEvent(
  text: string,
  details: BatchResult[] | null,
  successLabel: string,
  sequence: number
): ActivityEvent {
  const timestamp = Date.now();
  return { id: `${timestamp}-${sequence}`, timestamp, text, details, successLabel };
}

// Browsers deliberately never expose a selected/dropped file's filesystem
// path (only its name) as a privacy/security measure, so this is the most
// specific per-file detail available to show alongside the name.
function formatFileSize(bytes: number): string {
  return `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}

function formatPurgeCountdown(purgeScheduledAt: string): string {
  const msRemaining = new Date(purgeScheduledAt).getTime() - Date.now();
  const daysRemaining = Math.ceil(msRemaining / (24 * 60 * 60 * 1000));
  if (daysRemaining <= 0) return "Auto-deletes very soon";
  if (daysRemaining === 1) return "Auto-deletes in 1 day";
  return `Auto-deletes in ${daysRemaining} days`;
}

function summarizeBatchResult(verb: string, results: BatchResult[]): string {
  if (results.length === 1) {
    const [only] = results;
    if (only.skipped) return `${only.name} skipped: ${only.detail}`;
    return only.ok ? `${only.name} ${verb}.` : `${only.name} could not be ${verb}: ${only.detail}`;
  }
  const skipped = results.filter((result) => result.skipped).length;
  const succeeded = results.filter((result) => result.ok && !result.skipped).length;
  const failed = results.length - succeeded - skipped;
  if (skipped === 0) {
    // Unchanged from before "skipped" existed (no caller other than batch
    // accept-revision ever produces a skipped result).
    if (failed === 0) return `${succeeded} file(s) ${verb}.`;
    if (succeeded === 0) return `All ${failed} file(s) failed to be ${verb}.`;
    return `${succeeded} of ${results.length} file(s) ${verb}, ${failed} failed.`;
  }
  const clauses: string[] = [];
  if (succeeded > 0) clauses.push(`${succeeded} ${verb}`);
  if (skipped > 0) clauses.push(`${skipped} skipped`);
  if (failed > 0) clauses.push(`${failed} failed`);
  return `${results.length} file(s): ${clauses.join(", ")}.`;
}

// Selecting files (via the picker or a drop) is not itself an upload attempt,
// so it gets its own wording rather than reusing summarizeBatchResult's
// "succeeded/failed" language.
function summarizeSelection(results: BatchResult[]): string {
  if (results.length === 1) {
    const [only] = results;
    return only.ok ? `${only.name} selected for upload.` : `${only.name} rejected (unsupported type).`;
  }
  const selected = results.filter((result) => result.ok).length;
  const rejected = results.length - selected;
  if (rejected === 0) return `${selected} file(s) selected for upload.`;
  if (selected === 0) return `All ${rejected} file(s) rejected (unsupported type).`;
  return `${selected} file(s) selected for upload, ${rejected} rejected (unsupported type).`;
}

function groupBatchResults(results: BatchResult[], successLabel: string): { label: string; items: BatchResult[] }[] {
  const groups: { label: string; items: BatchResult[] }[] = [
    { label: successLabel, items: results.filter((result) => result.ok && !result.skipped) },
    { label: "Skipped", items: results.filter((result) => result.skipped) },
    { label: "Duplicate file", items: results.filter((result) => !result.ok && !result.skipped && result.reason === "duplicate") },
    { label: "Not supported", items: results.filter((result) => !result.ok && !result.skipped && result.reason === "rejected") },
    { label: "Failed", items: results.filter((result) => !result.ok && !result.skipped && !result.reason) },
  ];
  return groups.filter((group) => group.items.length > 0);
}

function formatCalculationInputs(inputs: Record<string, unknown>): string {
  return Object.entries(inputs)
    .map(([key, value]) => {
      const text = typeof value === "object" && value !== null ? JSON.stringify(value) : String(value);
      return `${key}: ${text}`;
    })
    .join(", ");
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
  const { currentUser, logout } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [processingJobs, setProcessingJobs] = useState<ProcessingJob[]>([]);
  const [archivedFiles, setArchivedFiles] = useState<ArchivedSourceFile[]>([]);
  const [archivedProjects, setArchivedProjects] = useState<ArchivedProject[]>([]);
  const [apiStatus, setApiStatus] = useState<{ ok: boolean; environment?: string } | null>(null);
  const [projectPendingArchive, setProjectPendingArchive] = useState<Project | null>(null);
  const [projectPendingPurge, setProjectPendingPurge] = useState<Project | null>(null);
  const [ownerReassignProject, setOwnerReassignProject] = useState<Project | null>(null);
  const [ownerReassignCandidates, setOwnerReassignCandidates] = useState<ProjectMember[]>([]);
  const [newOwnerId, setNewOwnerId] = useState("");
  const [reassigningOwner, setReassigningOwner] = useState(false);
  const [addCollaboratorProject, setAddCollaboratorProject] = useState<Project | null>(null);
  const [newCollaboratorUsername, setNewCollaboratorUsername] = useState("");
  const [addingCollaborator, setAddingCollaborator] = useState(false);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [calculations, setCalculations] = useState<Calculation[]>([]);
  const [summaryHistory, setSummaryHistory] = useState<Summary[]>([]);
  const [questionText, setQuestionText] = useState("");
  const [questionHistory, setQuestionHistory] = useState<QuestionAnswerRecord[]>([]);
  const [projectName, setProjectName] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [selectedArchivedFileIds, setSelectedArchivedFileIds] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState<string | null>(null);
  const [filesPendingBatchDelete, setFilesPendingBatchDelete] = useState<SourceFile[] | null>(null);
  const [archivedFilesPendingBatchPurge, setArchivedFilesPendingBatchPurge] = useState<SourceFile[] | null>(null);
  const [fileSort, setFileSort] = useState<"date" | "name" | "status">("date");
  const [fileStatusFilter, setFileStatusFilter] = useState("all");
  const [fileTypeFilter, setFileTypeFilter] = useState("all");
  const [calculationType, setCalculationType] = useState<CalculationType>("slope");
  const [perimeterGeometryType, setPerimeterGeometryType] = useState<PerimeterGeometryType>("LineString");
  const [coordinateUnit, setCoordinateUnit] = useState("ft");
  const [calculationUnit, setCalculationUnit] = useState("ft");
  const [startElevation, setStartElevation] = useState("100");
  const [endElevation, setEndElevation] = useState("104");
  const [horizontalDistance, setHorizontalDistance] = useState("100");
  const [geometry, setGeometry] = useState(defaultGeometry);
  const [secondGeometry, setSecondGeometry] = useState('{"type":"Point","coordinates":[3,4]}');
  const [message, setMessageText] = useState("Ready for your first project.");
  const [messageDetails, setMessageDetails] = useState<BatchResult[] | null>(null);
  const [messageSuccessLabel, setMessageSuccessLabel] = useState("Successful");
  const [showMessageDetails, setShowMessageDetails] = useState(false);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [showActivityLog, setShowActivityLog] = useState(false);
  const eventIdCounter = useRef(0);

  function setMessage(text: string, details: BatchResult[] | null = null, successLabel = "Successful") {
    setMessageText(text);
    setMessageDetails(details);
    setMessageSuccessLabel(successLabel);
    setShowMessageDetails(false);
    eventIdCounter.current += 1;
    const event = makeActivityEvent(text, details, successLabel, eventIdCounter.current);
    setEvents((current) => [event, ...current].slice(0, ACTIVITY_LOG_LIMIT));
    if (selectedProject) {
      // Fire-and-forget, plain fetch (not apiFetch): apiFetch redirects the
      // whole page to /login on a 401, which is right for a foreground data
      // load but wrong for a background audit write -- a stale/expired
      // session shouldn't yank the user away from what they were doing just
      // because the persisted copy of a status message couldn't be saved.
      fetch(`${apiUrl}/projects/${selectedProject.id}/activity-events`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, details, success_label: successLabel }),
      }).catch(() => {});
    }
  }
  const [loading, setLoading] = useState(false);
  // Dedicated to gating the file picker specifically while an upload request
  // is in flight. `loading` is shared across unrelated actions (creating a
  // project, calculations, summaries, questions), so using it here would
  // also block staging a file during any of those -- e.g. right after
  // creating a project, since selectProject/loadProjectData keeps `loading`
  // true well past project creation itself.
  const [uploading, setUploading] = useState(false);
  const [filePendingDelete, setFilePendingDelete] = useState<SourceFile | null>(null);
  const [filePendingPurge, setFilePendingPurge] = useState<SourceFile | null>(null);
  const [acceptingFileId, setAcceptingFileId] = useState<string | null>(null);
  const [acceptedFileIds, setAcceptedFileIds] = useState<string[]>([]);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [highlightedEntityIds, setHighlightedEntityIds] = useState<string[]>([]);
  const [selectedCalculationId, setSelectedCalculationId] = useState<string | null>(null);
  const [planSnippetUrl, setPlanSnippetUrl] = useState<string | null>(null);
  const [planSnippetError, setPlanSnippetError] = useState<string | null>(null);
  const [planSnippetLoading, setPlanSnippetLoading] = useState(false);
  const [selectedRevisionId, setSelectedRevisionId] = useState<string | null>(null);
  const [qaRevisionIds, setQaRevisionIds] = useState<string[]>([]);
  const [replacingFileId, setReplacingFileId] = useState<string | null>(null);
  const [replacementFile, setReplacementFile] = useState<File | null>(null);
  const [entityPage, setEntityPage] = useState(0);
  const entityPageSize = 200;
  const entityPageCount = Math.max(1, Math.ceil(entities.length / entityPageSize));
  const entityPageStart = entityPage * entityPageSize;
  const visibleEntities = entities.slice(entityPageStart, entityPageStart + entityPageSize);
  const visibleFiles = files
    .filter((file) => fileStatusFilter === "all" || file.status === fileStatusFilter)
    .filter((file) => fileTypeFilter === "all" || fileTypeGroup(file.original_name) === fileTypeFilter)
    .sort((a, b) => {
      if (fileSort === "name") return a.original_name.localeCompare(b.original_name);
      if (fileSort === "status") return a.status.localeCompare(b.status);
      return new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime();
    });

  function revisionSourceFile(revision: Revision) {
    const sourceJobId = revision.source_job_ids?.[0];
    const job = processingJobs.find((item) => item.id === sourceJobId);
    return files.find((file) => file.id === job?.source_file_id);
  }

  function toggleQaRevision(revisionId: string) {
    setQaRevisionIds((current) =>
      current.includes(revisionId)
        ? current.filter((id) => id !== revisionId)
        : [...current, revisionId]
    );
  }

  function qaScopeLabel(revisionIds: string[] | null): string {
    if (!revisionIds || revisionIds.length === 0) return "Whole project";
    return revisionIds
      .map((id) => {
        const revision = revisions.find((item) => item.id === id);
        const sourceFile = revision ? revisionSourceFile(revision) : undefined;
        return revision
          ? `Revision ${revision.revision_number} · ${sourceFile?.original_name ?? "Unknown file"}`
          : "Unknown revision";
      })
      .join(", ");
  }

  async function loadProjectData(project: Project) {
    const [fileResponse, revisionResponse, calculationResponse, processingResponse, summaryResponse, activityResponse] = await Promise.all([
      apiFetch(`${apiUrl}/projects/${project.id}/files`),
      apiFetch(`${apiUrl}/projects/${project.id}/site-model/revisions`),
      apiFetch(`${apiUrl}/projects/${project.id}/calculations`),
      apiFetch(`${apiUrl}/projects/${project.id}/processing`),
      apiFetch(`${apiUrl}/projects/${project.id}/summaries`),
      apiFetch(`${apiUrl}/projects/${project.id}/activity-events`),
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
    if (summaryResponse.ok) setSummaryHistory(await summaryResponse.json());
    // Phase 12's persisted audit trail: this project's own durable history,
    // replacing whatever local-only events an earlier project's selection
    // left behind. Not fatal if it 404s/fails -- the workspace still works,
    // just without a history to show until the next successful load.
    if (activityResponse.ok) {
      const persisted: PersistedActivityEvent[] = await activityResponse.json();
      setEvents(persisted.map(activityEventFromPersisted));
    } else {
      setEvents([]);
    }
  }

  async function loadArchivedFiles() {
    const response = await apiFetch(`${apiUrl}/admin/files/archived`);
    if (response.ok) setArchivedFiles(await response.json());
  }

  async function loadArchivedProjects() {
    const response = await apiFetch(`${apiUrl}/admin/projects/archived`);
    if (response.ok) setArchivedProjects(await response.json());
  }

  async function confirmArchiveProject() {
    if (!projectPendingArchive) return;
    const project = projectPendingArchive;
    if (busyAction === `project-archive:${project.id}`) return;
    setBusyAction(`project-archive:${project.id}`);
    setMessage(`Archiving ${project.name}...`);
    try {
      const response = await apiFetch(`${apiUrl}/projects/${project.id}/archive`, { method: "POST" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `Project archive failed (HTTP ${response.status}).`);
        return;
      }
      const remainingProjects = projects.filter((item) => item.id !== project.id);
      setProjects(remainingProjects);
      if (selectedProject?.id === project.id) {
        if (remainingProjects.length === 1) {
          // Exactly one project is left, so there's nothing ambiguous about
          // which one to show next -- select it instead of dropping to the
          // empty state even though other projects exist.
          await selectProject(remainingProjects[0]);
        } else {
          setSelectedProject(null);
          setFiles([]);
          setRevisions([]);
          setEntities([]);
          setCalculations([]);
          setSummaryHistory([]);
          setQuestionHistory([]);
        }
      }
      setMessage(`${project.name} was archived.`);
      await loadArchivedProjects();
    } catch (error) {
      setMessage(error instanceof Error ? `Archive request failed: ${error.message}` : "Archive request failed.");
    } finally {
      setBusyAction(null);
      setProjectPendingArchive(null);
    }
  }

  async function openOwnerReassign(project: Project) {
    setNewOwnerId("");
    setOwnerReassignCandidates([]);
    setOwnerReassignProject(project);
    const response = await apiFetch(`${apiUrl}/projects/${project.id}/members`);
    if (response.ok) {
      const members: ProjectMember[] = await response.json();
      setOwnerReassignCandidates(members.filter((member) => member.role === "power_user"));
    }
  }

  async function confirmReassignOwner(event: FormEvent) {
    event.preventDefault();
    if (!ownerReassignProject || !newOwnerId) return;
    const project = ownerReassignProject;
    setReassigningOwner(true);
    try {
      const response = await apiFetch(`${apiUrl}/projects/${project.id}/owner`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ owner_id: newOwnerId }),
      });
      if (response.ok) {
        const updated: Project = await response.json();
        setProjects(projects.map((item) => (item.id === updated.id ? updated : item)));
        if (selectedProject?.id === updated.id) setSelectedProject(updated);
        setMessage(`${project.name}'s owner was changed.`);
        setOwnerReassignProject(null);
      } else {
        const body = await response.json().catch(() => null);
        setMessage(errorMessage(body, "Could not change the project owner."));
      }
    } finally {
      setReassigningOwner(false);
    }
  }

  async function confirmAddCollaborator(event: FormEvent) {
    event.preventDefault();
    if (!addCollaboratorProject || !newCollaboratorUsername.trim()) return;
    const project = addCollaboratorProject;
    setAddingCollaborator(true);
    try {
      const lookup = await apiFetch(
        `${apiUrl}/users/lookup?${new URLSearchParams({ username: newCollaboratorUsername.trim() })}`,
      );
      if (!lookup.ok) {
        const body = await lookup.json().catch(() => null);
        setMessage(lookup.status === 404 ? `No user named "${newCollaboratorUsername.trim()}".` : errorMessage(body, "Could not look up that user."));
        return;
      }
      const found: { id: string; username: string } = await lookup.json();
      const response = await apiFetch(`${apiUrl}/projects/${project.id}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: found.id }),
      });
      if (response.ok) {
        setMessage(`${found.username} was added to ${project.name}.`);
        setAddCollaboratorProject(null);
        setNewCollaboratorUsername("");
      } else {
        const body = await response.json().catch(() => null);
        setMessage(errorMessage(body, "Could not add that collaborator."));
      }
    } finally {
      setAddingCollaborator(false);
    }
  }

  async function restoreArchivedProject(project: Project) {
    if (busyAction === `project-restore:${project.id}`) return;
    setBusyAction(`project-restore:${project.id}`);
    setMessage(`Restoring ${project.name}...`);
    try {
      const response = await apiFetch(`${apiUrl}/admin/projects/${project.id}/restore`, { method: "POST" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `Restore failed (HTTP ${response.status}).`);
        return;
      }
      const restored: Project = await response.json();
      setArchivedProjects((current) => current.filter((item) => item.id !== project.id));
      setProjects((current) => [...current, restored]);
      setMessage(`${project.name} was restored.`);
    } catch (error) {
      setMessage(error instanceof Error ? `Restore request failed: ${error.message}` : "Restore request failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function confirmPurgeArchivedProject() {
    if (!projectPendingPurge) return;
    const project = projectPendingPurge;
    if (busyAction === `project-purge:${project.id}`) return;
    setBusyAction(`project-purge:${project.id}`);
    setMessage(`Permanently deleting ${project.name}...`);
    try {
      const response = await apiFetch(`${apiUrl}/admin/projects/${project.id}`, { method: "DELETE" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `Purge failed (HTTP ${response.status}).`);
        return;
      }
      setArchivedProjects((current) => current.filter((item) => item.id !== project.id));
      setMessage(`${project.name} was permanently deleted.`);
    } catch (error) {
      setMessage(error instanceof Error ? `Purge request failed: ${error.message}` : "Purge request failed.");
    } finally {
      setBusyAction(null);
      setProjectPendingPurge(null);
    }
  }

  async function selectProject(project: Project) {
    setSelectedProject(project);
    setEntities([]);
    setSummaryHistory([]);
    setQuestionHistory([]);
    setSelectedFileIds(new Set());
    setQaRevisionIds([]);
    setHighlightedEntityIds([]);
    setPlanSnippetUrl(null);
    setPlanSnippetError(null);
    setEvents([]);
    setShowActivityLog(false);
    await loadProjectData(project);
  }

  async function loadEntities(projectId: string, revisionId: string): Promise<Entity[]> {
    const response = await apiFetch(
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

  async function requestPlanSnippet() {
    if (!selectedProject || highlightedEntityIds.length === 0) return;
    setPlanSnippetLoading(true);
    setPlanSnippetError(null);
    try {
      const response = await apiFetch(
        `${apiUrl}/projects/${selectedProject.id}/site-model/entities/${highlightedEntityIds[0]}/snippet`,
      );
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        setPlanSnippetUrl((current) => {
          if (current) URL.revokeObjectURL(current);
          return null;
        });
        setPlanSnippetError(detail?.detail ?? "Plan-sheet snippet could not be generated.");
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      setPlanSnippetUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return url;
      });
    } catch (error) {
      setPlanSnippetError(error instanceof Error ? error.message : "Plan-sheet snippet request failed.");
    } finally {
      setPlanSnippetLoading(false);
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
      const response = await apiFetch(`${apiUrl}/projects`, {
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

  async function uploadFiles(filesToUpload: File[], clientRejected: File[] = []) {
    if (!selectedProject || (filesToUpload.length === 0 && clientRejected.length === 0)) return;
    setLoading(true);
    setUploading(true);
    // Files rejected client-side (e.g. an unsupported extension dropped onto the
    // panel) never reach the server, but still need to appear in the same
    // summary/details breakdown as the ones that were actually uploaded.
    const rejectedResults: BatchResult[] = clientRejected.map((file) => ({
      name: file.name,
      ok: false,
      detail: "Unsupported file type",
      retryable: false,
      reason: "rejected",
    }));
    const uploadResults: BatchResult[] = [];
    try {
      for (const file of filesToUpload) {
        try {
          const formData = new FormData();
          formData.append("file", file);
          const response = await apiFetch(`${apiUrl}/projects/${selectedProject.id}/files`, { method: "POST", body: formData });
          if (response.ok) {
            uploadResults.push({ name: file.name, ok: true, detail: "" });
          } else {
            const error = await response.json().catch(() => ({}));
            // A duplicate-content (409) or validation (400: unsupported type, too
            // large, empty, invalid filename) rejection would only fail the same
            // way again on retry, so neither is kept selected for one.
            uploadResults.push({
              name: file.name,
              ok: false,
              detail: error.detail ?? `HTTP ${response.status}`,
              retryable: response.status !== 409 && response.status !== 400,
              reason: response.status === 409 ? "duplicate" : response.status === 400 ? "rejected" : undefined,
            });
          }
        } catch (error) {
          uploadResults.push({ name: file.name, ok: false, detail: error instanceof Error ? error.message : "request failed", retryable: true });
        }
      }
      if (filesToUpload.length > 0) await loadProjectData(selectedProject);
      const allResults = [...rejectedResults, ...uploadResults];
      setMessage(summarizeBatchResult("uploaded and queued for processing", allResults), allResults.length > 1 ? allResults : null);
    } finally {
      setLoading(false);
      setUploading(false);
      setPendingFiles(filesToUpload.filter((_, index) => uploadResults[index] && !uploadResults[index].ok && uploadResults[index].retryable !== false));
      const input = document.getElementById("source-file") as HTMLInputElement | null;
      if (input) input.value = "";
    }
  }

  // Stages files for upload (replacing whatever was previously staged) rather
  // than uploading them immediately, so the picker and drag-and-drop behave
  // the same way: select/drop, review, then click "Upload file(s)".
  function stageFiles(accepted: File[], rejected: File[] = []) {
    // While an upload is in flight, uploadFiles' finally block will replace
    // pendingFiles with its own closed-over result once it resolves; staging
    // something new here in the meantime would just be silently overwritten.
    if (uploading) return;
    setPendingFiles(accepted);
    const results: BatchResult[] = [
      ...accepted.map((file): BatchResult => ({ name: file.name, ok: true, detail: "", size: file.size })),
      ...rejected.map((file): BatchResult => ({ name: file.name, ok: false, detail: "Unsupported file type", reason: "rejected", size: file.size })),
    ];
    if (results.length === 0) return;
    setMessage(summarizeSelection(results), results.length > 1 ? results : null, "Selected for upload");
  }

  function cancelFileSelection() {
    const count = pendingFiles.length;
    setPendingFiles([]);
    const input = document.getElementById("source-file") as HTMLInputElement | null;
    if (input) input.value = "";
    setMessage(`${count} file${count === 1 ? "" : "s"} cleared. Nothing was uploaded.`);
  }

  function handleUploadDragOver(event: DragEvent<HTMLDivElement>) {
    if (!selectedProject) return;
    event.preventDefault();
    if (event.dataTransfer.types.includes("Files")) setIsDraggingFiles(true);
  }

  function handleUploadDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDraggingFiles(false);
  }

  function handleUploadDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDraggingFiles(false);
    if (!selectedProject) return;
    const dropped = Array.from(event.dataTransfer.files ?? []);
    if (dropped.length === 0) return;
    const accepted = dropped.filter((file) => ALLOWED_UPLOAD_EXTENSIONS.has(fileExtension(file.name)));
    const rejected = dropped.filter((file) => !ALLOWED_UPLOAD_EXTENSIONS.has(fileExtension(file.name)));
    stageFiles(accepted, rejected);
  }

  async function replaceFile(file: SourceFile) {
    if (!selectedProject || !replacementFile || busyAction !== null) return;
    const fileName = replacementFile.name;
    setBusyAction(`replace:${file.id}`);
    setMessage(`Uploading ${fileName} as a new version of ${file.original_name}...`);
    try {
      const formData = new FormData();
      formData.append("file", replacementFile);
      const response = await apiFetch(
        `${apiUrl}/projects/${selectedProject.id}/files/${file.id}/replace`,
        { method: "POST", body: formData }
      );
      if (response.ok) {
        setMessage(`${fileName} uploaded as a new version of ${file.original_name}.`);
        setReplacingFileId(null);
        setReplacementFile(null);
        await loadProjectData(selectedProject);
      } else {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `${fileName} could not be uploaded as a replacement.`);
      }
    } catch (error) {
      setMessage(
        error instanceof Error
          ? `Replace request failed: ${error.message}`
          : "Replace request failed."
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function processFile(file: SourceFile) {
    if (!selectedProject || busyAction === `process:${file.id}`) return;
    setBusyAction(`process:${file.id}`);
    setMessage(`Processing ${file.original_name}...`);
    try {
      const response = await apiFetch(`${apiUrl}/projects/${selectedProject.id}/files/${file.id}/process`, { method: "POST" });
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
      const response = await apiFetch(`${apiUrl}/projects/${selectedProject.id}/files/${file.id}`, { method: "DELETE" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `File archive failed (HTTP ${response.status}).`);
        return;
      }
      setFiles((current) => current.filter((item) => item.id !== file.id));
      setSelectedFileIds((current) => { if (!current.has(file.id)) return current; const next = new Set(current); next.delete(file.id); return next; });
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
      const response = await apiFetch(`${apiUrl}/admin/files/${file.id}/restore`, { method: "POST" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `Restore failed (HTTP ${response.status}).`);
        return;
      }
      setArchivedFiles((current) => current.filter((item) => item.id !== file.id));
      setSelectedArchivedFileIds((current) => { if (!current.has(file.id)) return current; const next = new Set(current); next.delete(file.id); return next; });
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
      const response = await apiFetch(`${apiUrl}/admin/files/${file.id}`, { method: "DELETE" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setMessage(error.detail ?? `Purge failed (HTTP ${response.status}).`);
        return;
      }
      setArchivedFiles((current) => current.filter((item) => item.id !== file.id));
      setSelectedArchivedFileIds((current) => { if (!current.has(file.id)) return current; const next = new Set(current); next.delete(file.id); return next; });
      setMessage(`${file.original_name} was permanently deleted.`);
    } catch (error) {
      setMessage(error instanceof Error ? `Purge request failed: ${error.message}` : "Purge request failed.");
    } finally {
      setBusyAction(null);
      setFilePendingPurge(null);
    }
  }

  function toggleFileSelection(fileId: string) {
    setSelectedFileIds((current) => {
      const next = new Set(current);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  }

  function toggleArchivedFileSelection(fileId: string) {
    setSelectedArchivedFileIds((current) => {
      const next = new Set(current);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  }

  function toggleSelectAllFiles(visible: SourceFile[]) {
    setSelectedFileIds((current) => {
      const allSelected = visible.length > 0 && visible.every((file) => current.has(file.id));
      if (allSelected) return new Set([...current].filter((id) => !visible.some((file) => file.id === id)));
      const next = new Set(current);
      visible.forEach((file) => next.add(file.id));
      return next;
    });
  }

  function toggleSelectAllArchivedFiles() {
    setSelectedArchivedFileIds((current) => {
      const allSelected = archivedFiles.length > 0 && archivedFiles.every((file) => current.has(file.id));
      return allSelected ? new Set() : new Set(archivedFiles.map((file) => file.id));
    });
  }

  async function processSelectedFiles() {
    if (!selectedProject || selectedFileIds.size === 0 || batchBusy !== null) return;
    const targets = files.filter((file) => selectedFileIds.has(file.id));
    setBatchBusy("process");
    setMessage(`Processing ${targets.length} file(s)...`);
    try {
      const results = await Promise.all(
        targets.map(async (file): Promise<BatchResult> => {
          try {
            const response = await apiFetch(`${apiUrl}/projects/${selectedProject.id}/files/${file.id}/process`, { method: "POST" });
            if (response.ok) return { name: file.original_name, ok: true, detail: "" };
            const error = await response.json().catch(() => ({}));
            return { name: file.original_name, ok: false, detail: error.detail ?? `HTTP ${response.status}` };
          } catch (error) {
            return { name: file.original_name, ok: false, detail: error instanceof Error ? error.message : "request failed" };
          }
        }),
      );
      await loadProjectData(selectedProject);
      setMessage(summarizeBatchResult("processed", results), results.length > 1 ? results : null);
    } catch (error) {
      setMessage(error instanceof Error ? `Batch processing failed: ${error.message}` : "Batch processing failed.");
    } finally {
      setSelectedFileIds(new Set());
      setBatchBusy(null);
    }
  }

  async function confirmBatchDeleteFiles() {
    if (!selectedProject || !filesPendingBatchDelete || batchBusy !== null) return;
    const targets = filesPendingBatchDelete;
    setBatchBusy("archive");
    setMessage(`Archiving ${targets.length} file(s)...`);
    try {
      const results = await Promise.all(
        targets.map(async (file): Promise<BatchResult> => {
          try {
            const response = await apiFetch(`${apiUrl}/projects/${selectedProject.id}/files/${file.id}`, { method: "DELETE" });
            if (response.ok) return { name: file.original_name, ok: true, detail: "" };
            const error = await response.json().catch(() => ({}));
            return { name: file.original_name, ok: false, detail: error.detail ?? `HTTP ${response.status}` };
          } catch (error) {
            return { name: file.original_name, ok: false, detail: error instanceof Error ? error.message : "request failed" };
          }
        }),
      );
      const archivedIds = new Set(targets.filter((_, index) => results[index].ok).map((file) => file.id));
      setFiles((current) => current.filter((file) => !archivedIds.has(file.id)));
      await loadArchivedFiles();
      setMessage(summarizeBatchResult("archived", results), results.length > 1 ? results : null);
    } catch (error) {
      setMessage(error instanceof Error ? `Batch archive failed: ${error.message}` : "Batch archive failed.");
    } finally {
      setSelectedFileIds(new Set());
      setBatchBusy(null);
      setFilesPendingBatchDelete(null);
    }
  }

  async function restoreSelectedArchivedFiles() {
    if (selectedArchivedFileIds.size === 0 || batchBusy !== null) return;
    const targets = archivedFiles.filter((file) => selectedArchivedFileIds.has(file.id));
    setBatchBusy("restore");
    setMessage(`Restoring ${targets.length} file(s)...`);
    try {
      const results = await Promise.all(
        targets.map(async (file): Promise<BatchResult> => {
          try {
            const response = await apiFetch(`${apiUrl}/admin/files/${file.id}/restore`, { method: "POST" });
            if (response.ok) return { name: file.original_name, ok: true, detail: "" };
            const error = await response.json().catch(() => ({}));
            return { name: file.original_name, ok: false, detail: error.detail ?? `HTTP ${response.status}` };
          } catch (error) {
            return { name: file.original_name, ok: false, detail: error instanceof Error ? error.message : "request failed" };
          }
        }),
      );
      const restoredIds = new Set(targets.filter((_, index) => results[index].ok).map((file) => file.id));
      setArchivedFiles((current) => current.filter((file) => !restoredIds.has(file.id)));
      if (selectedProject) await loadProjectData(selectedProject);
      setMessage(summarizeBatchResult("restored", results), results.length > 1 ? results : null);
    } catch (error) {
      setMessage(error instanceof Error ? `Batch restore failed: ${error.message}` : "Batch restore failed.");
    } finally {
      setSelectedArchivedFileIds(new Set());
      setBatchBusy(null);
    }
  }

  async function confirmBatchPurgeArchivedFiles() {
    if (!archivedFilesPendingBatchPurge || batchBusy !== null) return;
    const targets = archivedFilesPendingBatchPurge;
    setBatchBusy("purge");
    setMessage(`Permanently deleting ${targets.length} file(s)...`);
    try {
      const results = await Promise.all(
        targets.map(async (file): Promise<BatchResult> => {
          try {
            const response = await apiFetch(`${apiUrl}/admin/files/${file.id}`, { method: "DELETE" });
            if (response.ok) return { name: file.original_name, ok: true, detail: "" };
            const error = await response.json().catch(() => ({}));
            return { name: file.original_name, ok: false, detail: error.detail ?? `HTTP ${response.status}` };
          } catch (error) {
            return { name: file.original_name, ok: false, detail: error instanceof Error ? error.message : "request failed" };
          }
        }),
      );
      const purgedIds = new Set(targets.filter((_, index) => results[index].ok).map((file) => file.id));
      setArchivedFiles((current) => current.filter((file) => !purgedIds.has(file.id)));
      setMessage(summarizeBatchResult("permanently deleted", results), results.length > 1 ? results : null);
    } catch (error) {
      setMessage(error instanceof Error ? `Batch purge failed: ${error.message}` : "Batch purge failed.");
    } finally {
      setSelectedArchivedFileIds(new Set());
      setBatchBusy(null);
      setArchivedFilesPendingBatchPurge(null);
    }
  }

  async function acceptRevision(file: SourceFile) {
    if (!selectedProject || acceptingFileId !== null || acceptedFileIds.includes(file.id)) return;
    setAcceptingFileId(file.id);
    setMessage(`Accepting revision for ${file.original_name}...`);
    try {
      const response = await apiFetch(
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

  async function acceptSelectedFiles() {
    if (!selectedProject || selectedFileIds.size === 0 || batchBusy !== null || acceptingFileId !== null) return;
    const targets = files.filter((file) => selectedFileIds.has(file.id));
    setBatchBusy("accept");
    setMessage(`Accepting revisions for ${targets.length} file(s)...`);
    const results: BatchResult[] = [];
    let firstAcceptedRevisionId: string | null = null;
    try {
      // Sequential on purpose, unlike the other batch actions' Promise.all:
      // accepting assigns the next revision_number for the project, and the
      // backend already has retry-on-conflict handling for the case where
      // two accepts race for the same number (a real bug once). Running
      // these one at a time avoids relying on that retry path under real
      // concurrency instead of just not creating the race in the first place.
      for (const file of targets) {
        if (acceptedFileIds.includes(file.id)) {
          results.push({ name: file.original_name, ok: true, skipped: true, detail: "Revision already accepted" });
          continue;
        }
        if (file.status !== "completed") {
          results.push({ name: file.original_name, ok: true, skipped: true, detail: `File is not completed (status: ${file.status})` });
          continue;
        }
        try {
          const response = await apiFetch(
            `${apiUrl}/projects/${selectedProject.id}/site-model/revisions/from-extraction/${file.id}`,
            { method: "POST" },
          );
          if (response.ok) {
            const revision: Revision = await response.json();
            setRevisions((current) => [revision, ...current.filter((item) => item.id !== revision.id)]);
            setAcceptedFileIds((current) => (current.includes(file.id) ? current : [...current, file.id]));
            if (firstAcceptedRevisionId === null) firstAcceptedRevisionId = revision.id;
            results.push({ name: file.original_name, ok: true, detail: "" });
          } else {
            const error = await response.json().catch(() => ({}));
            results.push({ name: file.original_name, ok: false, detail: error.detail ?? `HTTP ${response.status}` });
          }
        } catch (error) {
          results.push({ name: file.original_name, ok: false, detail: error instanceof Error ? error.message : "request failed" });
        }
      }
      // Only navigate the Site model section to a newly-accepted revision if
      // nothing was already selected there; a batch action shouldn't yank
      // the view away from whatever the user was already looking at.
      if (firstAcceptedRevisionId && !selectedRevisionId) {
        setSelectedRevisionId(firstAcceptedRevisionId);
        await loadEntities(selectedProject.id, firstAcceptedRevisionId);
      }
      setMessage(summarizeBatchResult("accepted", results), results.length > 1 ? results : null, "Accepted");
    } catch (error) {
      setMessage(error instanceof Error ? `Batch accept failed: ${error.message}` : "Batch accept failed.");
    } finally {
      setSelectedFileIds(new Set());
      setBatchBusy(null);
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
      const response = await apiFetch(`${apiUrl}/projects/${selectedProject.id}/calculations`, {
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
      const params = new URLSearchParams();
      qaRevisionIds.forEach((id) => params.append("revision_ids", id));
      const query = params.toString() ? `?${params.toString()}` : "";
      const response = await apiFetch(`${apiUrl}/projects/${selectedProject.id}/summaries${query}`, { method: "POST" });
      if (response.ok) {
        const created: Summary = await response.json();
        setSummaryHistory((current) => [created, ...current]);
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
      const response = await apiFetch(`${apiUrl}/projects/${selectedProject.id}/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: questionText.trim(),
          revision_ids: qaRevisionIds.length > 0 ? qaRevisionIds : null,
        }),
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
      const response = await apiFetch(`${apiUrl}/projects`);
      if (!response.ok) {
        setMessage("Could not load projects. Check that the API is running.");
        return;
      }
      const data: Project[] = await response.json();
      setProjects(data);
      if (data.length > 0) {
        const project = data[0];
        setSelectedProject(project);
        await loadProjectData(project);
      }
    }

    async function loadApiStatus() {
      try {
        const response = await apiFetch(`${apiUrl}/health`);
        if (!response.ok) {
          setApiStatus({ ok: false });
          return;
        }
        const health: { status: string; environment: string } = await response.json();
        setApiStatus({ ok: health.status === "ok", environment: health.environment });
      } catch {
        setApiStatus({ ok: false });
      }
    }

    async function loadInitialData() {
      await Promise.all([loadInitialProjects(), loadApiStatus()]);
      // Both endpoints 403 for a plain "user" role (no archive/purge rights
      // anywhere) -- skip the request rather than let it fail silently and
      // show a misleading "0 archived" empty state.
      if (currentUser.role === "user") return;
      const archiveResponse = await apiFetch(`${apiUrl}/admin/files/archived`);
      if (archiveResponse.ok) setArchivedFiles(await archiveResponse.json());
      const archivedProjectsResponse = await apiFetch(`${apiUrl}/admin/projects/archived`);
      if (archivedProjectsResponse.ok) setArchivedProjects(await archivedProjectsResponse.json());
    }

    void loadInitialData();
    // Intentionally mount-only: loadProjectData is a plain function
    // recreated every render, so adding it here would re-run this on every
    // state update it triggers instead of once on load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="workspace">
      <header className="topbar">
        <div><p className="eyebrow">Civil engineering intelligence</p><h1>Project workspace</h1></div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span className={`status ${apiStatus && !apiStatus.ok ? "status-error" : ""}`}>{apiStatus === null ? "Checking API..." : apiStatus.ok ? `API connected · ${apiStatus.environment}` : "API unreachable"}</span>
          <span className="muted">{currentUser.username} · {currentUser.role.replace("_", " ")}</span>
          <Link href="/account" className="secondary-button">Change password</Link>
          {currentUser.role === "admin" && (
            <Link href="/admin/users" className="secondary-button">Manage users</Link>
          )}
          <button type="button" className="secondary-button" onClick={() => void logout()}>Sign out</button>
        </div>
      </header>
      <p className="message" role="status">
        {message}
        {messageDetails && messageDetails.length > 1 && (
          <button type="button" className="message-details-toggle" onClick={() => setShowMessageDetails((current) => !current)}>
            {showMessageDetails ? "Hide details" : "Show details"}
          </button>
        )}
      </p>
      {messageDetails && messageDetails.length > 1 && showMessageDetails && (
        <div className="batch-details" role="status">
          {groupBatchResults(messageDetails, messageSuccessLabel).map((group) => (
            <div className="batch-details-group" key={group.label}>
              <strong>{group.label} ({group.items.length})</strong>
              <ul>{group.items.map((item) => <li key={item.name}>{item.name}{item.size !== undefined ? ` (${formatFileSize(item.size)})` : ""}{item.detail ? ` — ${item.detail}` : ""}</li>)}</ul>
            </div>
          ))}
        </div>
      )}
      {events.length > 1 && (
        <div className="activity-log-wrap">
          <button type="button" className="activity-log-toggle" onClick={() => setShowActivityLog((current) => !current)}>
            {showActivityLog ? "Hide activity log" : `Activity log (${events.length})`}
          </button>
          {showActivityLog && (
            <ul className="activity-log">
              {events.map((event) => (
                <li key={event.id} className="activity-log-item">
                  <span className="activity-log-time">{formatEventTime(event.timestamp)}</span>
                  <span className="activity-log-text">{event.text}</span>
                  {event.details && event.details.length > 1 && (
                    <div className="activity-log-item-details">
                      {groupBatchResults(event.details, event.successLabel).map((group) => (
                        <div className="batch-details-group" key={group.label}>
                          <strong>{group.label} ({group.items.length})</strong>
                          <ul>{group.items.map((item) => <li key={item.name}>{item.name}{item.size !== undefined ? ` (${formatFileSize(item.size)})` : ""}{item.detail ? ` — ${item.detail}` : ""}</li>)}</ul>
                        </div>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
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
          {currentUser.role !== "user" && <section className="admin-panel"><p className="eyebrow">Archived files</p><p className="muted">{archivedFiles.length} archived file{archivedFiles.length === 1 ? "" : "s"}</p>{archivedFiles.length > 0 && <div className="archive-controls"><label className="select-all"><input type="checkbox" checked={archivedFiles.length > 0 && archivedFiles.every((file) => selectedArchivedFileIds.has(file.id))} onChange={toggleSelectAllArchivedFiles} disabled={batchBusy !== null} /><span>Select all</span></label>{selectedArchivedFileIds.size > 0 && <div className="batch-toolbar-mini"><button disabled={batchBusy !== null} onClick={() => void restoreSelectedArchivedFiles()}>{batchBusy === "restore" ? "Restoring..." : `Restore (${selectedArchivedFileIds.size})`}</button><button className="danger-button" disabled={batchBusy !== null} onClick={() => setArchivedFilesPendingBatchPurge(archivedFiles.filter((file) => selectedArchivedFileIds.has(file.id)))}>{`Purge (${selectedArchivedFileIds.size})`}</button></div>}</div>}{archivedFiles.map((file) => <div className="archive-row" key={file.id}><div className="archive-row-top"><input type="checkbox" checked={selectedArchivedFileIds.has(file.id)} onChange={() => toggleArchivedFileSelection(file.id)} disabled={batchBusy !== null} /><strong>{file.original_name}</strong></div><small className={file.purge_warning ? "purge-countdown purge-countdown-warning" : "purge-countdown"}>{formatPurgeCountdown(file.purge_scheduled_at)}</small><div><button disabled={busyAction === `restore:${file.id}` || batchBusy !== null} onClick={() => void restoreArchivedFile(file)}>{busyAction === `restore:${file.id}` ? "Restoring..." : "Restore"}</button><button className="danger-button" disabled={busyAction === `purge:${file.id}` || batchBusy !== null} onClick={() => void purgeArchivedFile(file)}>{busyAction === `purge:${file.id}` ? "Purging..." : "Purge"}</button></div></div>)}</section>}
          {currentUser.role !== "user" && <section className="admin-panel"><p className="eyebrow">Archived projects</p><p className="muted">{archivedProjects.length} archived project{archivedProjects.length === 1 ? "" : "s"}</p>{archivedProjects.map((project) => <div className="archive-row" key={project.id}><strong>{project.name}</strong><small className={project.purge_warning ? "purge-countdown purge-countdown-warning" : "purge-countdown"}>{formatPurgeCountdown(project.purge_scheduled_at)}</small>{(currentUser.role === "admin" || currentUser.id === project.owner_id) && <div><button disabled={busyAction === `project-restore:${project.id}`} onClick={() => void restoreArchivedProject(project)}>{busyAction === `project-restore:${project.id}` ? "Restoring..." : "Restore"}</button><button className="danger-button" disabled={busyAction === `project-purge:${project.id}`} onClick={() => setProjectPendingPurge(project)}>{busyAction === `project-purge:${project.id}` ? "Purging..." : "Purge"}</button></div>}</div>)}</section>}
        </aside>
        <section className="project-detail">
          {selectedProject ? <>
            <div className="detail-heading"><div><p className="eyebrow">Active project</p><h2>{selectedProject.name}</h2></div><div style={{ display: "flex", gap: 12 }}>{(currentUser.role === "admin" || currentUser.id === selectedProject.owner_id) && <button className="secondary-button" onClick={() => { setNewCollaboratorUsername(""); setAddCollaboratorProject(selectedProject); }}>Add collaborator</button>}{(currentUser.role === "admin" || currentUser.id === selectedProject.owner_id) && <button className="secondary-button" onClick={() => void openOwnerReassign(selectedProject)}>Reassign owner</button>}{(currentUser.role === "admin" || currentUser.id === selectedProject.owner_id) && <button className="danger-button" onClick={() => setProjectPendingArchive(selectedProject)}>Archive project</button>}</div></div>
            <div className={`upload-panel ${isDraggingFiles ? "drag-active" : ""}`} onDragOver={handleUploadDragOver} onDragLeave={handleUploadDragLeave} onDrop={handleUploadDrop}><div><p className="eyebrow">Source files</p><h3>Bring the plan into focus.</h3><p className="muted">PDF, DXF, CSV, TXT, TIFF, and LandXML files up to 50 MB. Select several at once, or drag and drop them here.</p>{isDraggingFiles && <p className="drag-hint">Drop files to add them for upload...</p>}</div><form className="upload-form" onSubmit={(event) => { event.preventDefault(); void uploadFiles(pendingFiles); }}><label className="file-picker" htmlFor="source-file"><span>{pendingFiles.length > 0 ? `${pendingFiles.length} file${pendingFiles.length === 1 ? "" : "s"} selected` : "Choose source file(s)"}</span><input id="source-file" type="file" multiple accept=".pdf,.dxf,.csv,.txt,.tif,.tiff,.xml" disabled={uploading} onChange={(event) => stageFiles(Array.from(event.target.files ?? []))} /></label><div className="upload-form-actions"><button type="submit" disabled={loading || pendingFiles.length === 0}>{`Upload file${pendingFiles.length === 1 ? "" : "s"}`}</button>{pendingFiles.length > 0 && <button type="button" className="secondary-button" disabled={loading} onClick={cancelFileSelection}>Cancel</button>}</div></form></div>
            <div className="file-list">
              <div className="list-heading"><span className="select-all"><input type="checkbox" checked={visibleFiles.length > 0 && visibleFiles.every((file) => selectedFileIds.has(file.id))} onChange={() => toggleSelectAllFiles(visibleFiles)} disabled={batchBusy !== null || visibleFiles.length === 0} /><span>File</span></span><span>Status / actions</span></div>
              {files.length > 0 && <div className="file-list-controls">
                <label>Sort<select value={fileSort} onChange={(event) => setFileSort(event.target.value as "date" | "name" | "status")}><option value="date">Upload date</option><option value="name">Name</option><option value="status">Status</option></select></label>
                <label>Status<select value={fileStatusFilter} onChange={(event) => setFileStatusFilter(event.target.value)}><option value="all">All statuses</option><option value="queued">Ready to process</option><option value="processing">Processing</option><option value="completed">Completed</option><option value="failed">Failed</option></select></label>
                <label>Type<select value={fileTypeFilter} onChange={(event) => setFileTypeFilter(event.target.value)}><option value="all">All types</option><option value="pdf">PDF</option><option value="dxf">DXF</option><option value="csv">CSV</option><option value="txt">TXT</option><option value="tif">TIFF</option><option value="xml">LandXML</option></select></label>
              </div>}
              {selectedFileIds.size > 0 && <div className="batch-toolbar">
                <span>{selectedFileIds.size} selected</span>
                <button type="button" className="secondary-button" disabled={batchBusy !== null} onClick={() => void processSelectedFiles()}>{batchBusy === "process" ? "Processing..." : "Process selected"}</button>
                <button type="button" className="secondary-button" disabled={batchBusy !== null || acceptingFileId !== null} onClick={() => void acceptSelectedFiles()}>{batchBusy === "accept" ? "Accepting..." : "Accept selected"}</button>
                {currentUser.role !== "user" && <button type="button" className="danger-button" disabled={batchBusy !== null} onClick={() => setFilesPendingBatchDelete(files.filter((file) => selectedFileIds.has(file.id)))}>Archive selected</button>}
                <button type="button" className="secondary-button" disabled={batchBusy !== null} onClick={() => setSelectedFileIds(new Set())}>Clear selection</button>
              </div>}
              {files.length === 0 && <p className="muted">Uploaded files will appear here.</p>}
              {files.length > 0 && visibleFiles.length === 0 && <p className="muted">No files match the current filter.</p>}
              {visibleFiles.map((file) => { const fileWarnings = latestJobWarnings(processingJobs, file.id); const isSuperseded = file.superseded_by_id !== null; return <div className="file-row" key={file.id}><label className="file-select"><input type="checkbox" checked={selectedFileIds.has(file.id)} onChange={() => toggleFileSelection(file.id)} disabled={batchBusy !== null} /></label><div className="file-info"><strong>{file.original_name}</strong><small>{Math.ceil(file.size_bytes / 1024)} KB · {file.checksum}</small>{isSuperseded && <small className="file-superseded">Replaced by a newer version</small>}{file.status === "failed" && file.error_message && <small className="file-error">{file.error_message}</small>}{file.status === "completed" && fileWarnings.length > 0 && summarizeWarnings(fileWarnings).map((warning, index) => <small className="file-warning" key={index}>{warning}</small>)}{replacingFileId === file.id && <div className="replace-row"><label className="file-picker" htmlFor={`replace-${file.id}`}><span>{replacementFile?.name ?? "Choose a replacement file"}</span><input id={`replace-${file.id}`} type="file" accept=".pdf,.dxf,.csv,.txt,.tif,.tiff,.xml" onChange={(event) => setReplacementFile(event.target.files?.[0] ?? null)} /></label><button disabled={busyAction !== null || replacementFile === null} onClick={() => void replaceFile(file)}>{busyAction === `replace:${file.id}` ? "Uploading..." : "Upload replacement"}</button><button className="secondary-button" onClick={() => { setReplacingFileId(null); setReplacementFile(null); }}>Cancel</button></div>}</div><div className="file-status"><span>{processingStatusLabel(file.status, fileWarnings.length > 0)}</span>{file.status === "queued" && <button disabled={busyAction === `process:${file.id}` || batchBusy !== null} onClick={() => void processFile(file)}>{busyAction === `process:${file.id}` ? "Processing..." : "Process"}</button>}{(file.status === "failed" || file.status === "processing") && <button disabled={busyAction === `process:${file.id}` || batchBusy !== null} onClick={() => void processFile(file)}>{busyAction === `process:${file.id}` ? "Processing..." : "Retry"}</button>}{file.status === "completed" && (acceptedFileIds.includes(file.id) ? <button disabled>Revision accepted</button> : <button disabled={acceptingFileId !== null || batchBusy !== null} onClick={() => void acceptRevision(file)}>{acceptingFileId === file.id ? "Accepting..." : "Accept revision"}</button>)}{!isSuperseded && replacingFileId !== file.id && <button className="secondary-button" disabled={batchBusy !== null} onClick={() => { setReplacingFileId(file.id); setReplacementFile(null); }}>Replace</button>}{currentUser.role !== "user" && <button className="danger-button" disabled={busyAction === `delete:${file.id}` || batchBusy !== null} onClick={() => void deleteFile(file)}>Archive</button>}</div></div>; })}
            </div>
            <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Site model</p><h3>Revision geometry</h3>{revisions.length > 0 && <label className="revision-selector">Revision<select value={selectedRevisionId ?? ""} onChange={(event) => void selectRevision(event.target.value)}>{revisions.map((revision) => { const sourceFile = revisionSourceFile(revision); return <option key={revision.id} value={revision.id}>Revision {revision.revision_number} · {sourceFile?.original_name ?? "Unknown file"} · {sourceFile?.checksum ?? "Unknown identifier"}</option>; })}</select></label>}</div><span className="section-count">{entities.length} entities</span></div>{revisions.length === 0 ? <p className="muted">Process a file and accept a revision to inspect extracted geometry.</p> : <><GeometryPreview entities={entities} highlightedIds={highlightedEntityIds} onSelect={(entity) => { setHighlightedEntityIds([entity.id]); setSelectedCalculationId(null); setMessage(`Selected ${entity.entity_type} from ${entity.source_reference?.file_name?.toString() ?? "unknown source"}.`); }} /><div className="entity-grid">{visibleEntities.map((entity) => <button className={`entity-card ${entity.validation_status} ${highlightedEntityIds.includes(entity.id) ? "entity-selected" : ""}`} key={entity.id} onClick={() => { setHighlightedEntityIds([entity.id]); setSelectedCalculationId(null); }}><strong>{entity.entity_type}</strong><span>{entity.validation_status}</span>{entity.properties?.semantic_type ? <span className="semantic-type">{String(entity.properties.semantic_type).replace(/_/g, " ")}{entity.properties?.zoning ? ` · ${entity.properties.zoning}` : ""}</span> : null}<small>{entity.entity_type === "key_phrase" ? `"${entity.properties?.phrase}"` : entity.source_reference?.file_name?.toString() ?? "No source reference"}</small></button>)}</div>{entities.length > 0 && <div className="entity-pagination"><span className="muted">Showing {entityPageStart + 1}-{Math.min(entityPageStart + entityPageSize, entities.length)} of {entities.length} entities.</span><div className="entity-pagination-controls"><button className="secondary-button" disabled={entityPage === 0} onClick={() => setEntityPage((page) => Math.max(0, page - 1))}><span aria-hidden="true">←</span> Previous</button><span>Page {entityPage + 1} of {entityPageCount}</span><button className="secondary-button" disabled={entityPage >= entityPageCount - 1} onClick={() => setEntityPage((page) => Math.min(entityPageCount - 1, page + 1))}>Next <span aria-hidden="true">→</span></button></div></div>}{highlightedEntityIds.length > 0 && <div className="plan-snippet"><button type="button" className="secondary-button" disabled={planSnippetLoading} onClick={() => void requestPlanSnippet()}>{planSnippetLoading ? "Loading snippet..." : "View plan-sheet snippet"}</button><p className="muted">Renders the source DXF with the selected entity highlighted in red; only available for DXF-sourced entities.</p>{planSnippetError && <p className="muted">{planSnippetError}</p>}{planSnippetUrl && <img className="plan-snippet-image" src={planSnippetUrl} alt="Highlighted plan-sheet snippet" />}</div>}</>}</section>
            <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Calculations</p><h3>Run a deterministic check.</h3><p className="calculation-help">Distance uses two geometries. Area accepts Polygon, MultiPolygon, or Circle JSON. Perimeter accepts LineString, Polygon, or Circle JSON. A Circle uses center and radius in the selected coordinate unit.</p></div></div><form className="calculation-form" onSubmit={createCalculation}><label>Calculation<select value={calculationType} onChange={(event) => changeCalculationType(event.target.value as CalculationType)}><option value="slope">Slope</option><option value="distance">Distance</option><option value="area">Area</option><option value="perimeter">Perimeter</option></select></label><label>Coordinate unit<select value={coordinateUnit} onChange={(event) => setCoordinateUnit(event.target.value)}><option value="ft">Feet</option><option value="m">Meters</option><option value="in">Inches</option></select></label><label>Output unit<select value={calculationUnit} onChange={(event) => setCalculationUnit(event.target.value)}><option value="ft">Feet</option><option value="m">Meters</option><option value="in">Inches</option></select></label>{calculationType === "slope" ? <div className="calculation-fields"><label>Start elevation<input value={startElevation} onChange={(event) => setStartElevation(event.target.value)} /></label><label>End elevation<input value={endElevation} onChange={(event) => setEndElevation(event.target.value)} /></label><label>Horizontal distance<input value={horizontalDistance} onChange={(event) => setHorizontalDistance(event.target.value)} /></label></div> : <div className="geometry-fields">{calculationType === "perimeter" && <label>Perimeter geometry<select value={perimeterGeometryType} onChange={(event) => changePerimeterGeometryType(event.target.value as PerimeterGeometryType)}><option value="LineString">LineString (open path)</option><option value="Polygon">Polygon (closed boundary)</option></select></label>}<label>Geometry JSON<textarea value={geometry} onChange={(event) => setGeometry(event.target.value)} rows={3} /></label>{calculationType === "distance" && <label>Second geometry JSON<textarea value={secondGeometry} onChange={(event) => setSecondGeometry(event.target.value)} rows={3} /></label>}</div>}<button type="submit" disabled={loading}>Run calculation</button></form>{calculations.length > 0 && <div className="calculation-results">{calculations.slice(0, 5).map((calculation) => <button type="button" className={`result-row ${selectedCalculationId === calculation.id ? "result-selected" : ""}`} key={calculation.id} onClick={() => void selectCalculationResult(calculation)}><strong>{calculation.calculation_type}</strong><span>{calculation.result.toFixed(3)} {calculation.unit}</span><small>{calculation.formula}<span className="result-inputs">{formatCalculationInputs(calculation.inputs)}</span></small></button>)}</div>}</section>
            <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Site intelligence</p><h3>Summarize and ask questions.</h3><p className="calculation-help">Answers are grounded in the accepted site model and calculations. AI-generated content is clearly labeled and never invents a measurement.</p></div><button type="button" className="secondary-button" disabled={loading || revisions.length === 0} onClick={() => void requestSummary()}>Request site summary</button></div>{revisions.length > 0 && <div className="qa-scope"><p className="eyebrow">Scope</p><p className="muted">{qaRevisionIds.length === 0 ? "Whole project (every accepted document's latest revision)." : "Selected revisions only."}</p><div className="qa-scope-options">{revisions.map((revision) => { const sourceFile = revisionSourceFile(revision); return <label key={revision.id} className="qa-scope-option"><input type="checkbox" checked={qaRevisionIds.includes(revision.id)} onChange={() => toggleQaRevision(revision.id)} /><span>Revision {revision.revision_number} · {sourceFile?.original_name ?? "Unknown file"}</span></label>; })}</div></div>}{summaryHistory.length > 0 && <div className="summary-list">{summaryHistory.map((item) => <div className="summary-card" key={item.id}><p>{item.content.summary}</p><dl><div><dt>Grading</dt><dd>{item.content.grading}</dd></div><div><dt>Drainage</dt><dd>{item.content.drainage}</dd></div><div><dt>Utilities</dt><dd>{item.content.utilities}</dd></div></dl>{item.content.attention_flags.length > 0 && <div className="attention-flags"><strong>Attention</strong><ul>{item.content.attention_flags.map((flag, index) => <li key={index}>{flag}</li>)}</ul></div>}<p className="ai-label">AI-generated · {new Date(item.created_at).toLocaleString()} · scope: {qaScopeLabel(item.revision_ids)} · {item.content.limitations.join(" ")}</p></div>)}</div>}<form className="question-form" onSubmit={askQuestion}><label>Ask a question<input value={questionText} onChange={(event) => setQuestionText(event.target.value)} placeholder="What is the setback distance?" maxLength={2000} /></label><button type="submit" className="secondary-button" disabled={loading || !questionText.trim()}>Ask</button></form>{questionHistory.length > 0 && <div className="qa-list">{questionHistory.map((record) => <div className="qa-card" key={record.id}><p className="qa-question">{record.question}</p><p className="qa-answer">{record.answer.answer}</p><small className="ai-label">AI-generated · {record.answer.method} · confidence {record.answer.confidence.toFixed(2)} · scope: {qaScopeLabel(record.revision_ids)}</small>{record.answer.limitations && record.answer.limitations.length > 0 && <small className="qa-limitations">{record.answer.limitations.join(" ")}</small>}</div>)}</div>}</section>
            {filePendingDelete && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title"><p className="eyebrow">Archive file</p><h3 id="delete-title">Remove {filePendingDelete.original_name}?</h3><p className="muted">The file will be hidden from this workspace and moved to the archive. Accepted revisions and calculations will remain.</p><div className="modal-actions"><button className="secondary-button" disabled={busyAction === `delete:${filePendingDelete.id}`} onClick={() => setFilePendingDelete(null)}>Cancel</button><button className="danger-button" disabled={busyAction === `delete:${filePendingDelete.id}`} onClick={() => void confirmDeleteFile()}>{busyAction === `delete:${filePendingDelete.id}` ? "Archiving..." : "Archive file"}</button></div></section></div>}
            {filePendingPurge && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="purge-title"><p className="eyebrow">Permanent purge</p><h3 id="purge-title">Permanently delete {filePendingPurge.original_name}?</h3><p className="muted">This removes the archived file and its metadata. Accepted revisions and calculations remain, but the original source cannot be restored.</p><div className="modal-actions"><button className="secondary-button" disabled={busyAction === `purge:${filePendingPurge.id}`} onClick={() => setFilePendingPurge(null)}>Cancel</button><button className="danger-button" disabled={busyAction === `purge:${filePendingPurge.id}`} onClick={() => void confirmPurgeArchivedFile()}>{busyAction === `purge:${filePendingPurge.id}` ? "Purging..." : "Permanently delete"}</button></div></section></div>}
            {filesPendingBatchDelete && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="batch-delete-title"><p className="eyebrow">Archive files</p><h3 id="batch-delete-title">Archive {filesPendingBatchDelete.length} file{filesPendingBatchDelete.length === 1 ? "" : "s"}?</h3><p className="muted">{filesPendingBatchDelete.map((file) => file.original_name).join(", ")}</p><p className="muted">Each file will be hidden from this workspace and moved to the archive. Accepted revisions and calculations will remain.</p><div className="modal-actions"><button className="secondary-button" disabled={batchBusy !== null} onClick={() => setFilesPendingBatchDelete(null)}>Cancel</button><button className="danger-button" disabled={batchBusy !== null} onClick={() => void confirmBatchDeleteFiles()}>{batchBusy === "archive" ? "Archiving..." : "Archive files"}</button></div></section></div>}
          </> : <div className="empty-detail"><p className="eyebrow">Start here</p>{projects.length > 0 ? <><h2>Select your project.</h2><p className="muted">Choose a project from the list on the left to see its files, revisions, and calculations.</p></> : <><h2>Create your first project.</h2><p className="muted">Your project becomes the home for plans, source files, measured results, and site-model revisions.</p></>}</div>}
        </section>
      </section>
      {projectPendingArchive && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="project-archive-title"><p className="eyebrow">Archive project</p><h3 id="project-archive-title">Archive {projectPendingArchive.name}?</h3><p className="muted">The project will be hidden from the workspace and moved to the admin archive, along with everything in it — its files, revisions, calculations, summaries, and questions become inaccessible until you restore it. Nothing is deleted; restoring brings it all back exactly as it was.</p><div className="modal-actions"><button className="secondary-button" disabled={busyAction === `project-archive:${projectPendingArchive.id}`} onClick={() => setProjectPendingArchive(null)}>Cancel</button><button className="danger-button" disabled={busyAction === `project-archive:${projectPendingArchive.id}`} onClick={() => void confirmArchiveProject()}>{busyAction === `project-archive:${projectPendingArchive.id}` ? "Archiving..." : "Archive project"}</button></div></section></div>}
      {addCollaboratorProject && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="add-collaborator-title"><p className="eyebrow">Add collaborator</p><h3 id="add-collaborator-title">Add a collaborator to {addCollaboratorProject.name}?</h3><p className="muted">They get full working access (upload, process, calculate, ask questions); a Power User also gets archive/purge rights. Enter their exact username.</p><form onSubmit={confirmAddCollaborator}><label htmlFor="new-collaborator-username">Username</label><input id="new-collaborator-username" value={newCollaboratorUsername} onChange={(event) => setNewCollaboratorUsername(event.target.value)} required autoFocus /><div className="modal-actions"><button type="button" className="secondary-button" disabled={addingCollaborator} onClick={() => setAddCollaboratorProject(null)}>Cancel</button><button type="submit" className="danger-button" disabled={addingCollaborator || !newCollaboratorUsername.trim()}>{addingCollaborator ? "Adding..." : "Add collaborator"}</button></div></form></section></div>}
      {ownerReassignProject && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="owner-reassign-title"><p className="eyebrow">Reassign owner</p><h3 id="owner-reassign-title">Change the owner of {ownerReassignProject.name}?</h3><p className="muted">The new owner must be a Power User already collaborating on this project. Ownership moves to them immediately; you keep your own access unless removed separately.</p>{ownerReassignCandidates.length === 0 ? <p className="muted">No Power User collaborators on this project yet — use &quot;Add collaborator&quot; first.</p> : <form onSubmit={confirmReassignOwner}><label htmlFor="new-owner">New owner</label><select id="new-owner" value={newOwnerId} onChange={(event) => setNewOwnerId(event.target.value)} required><option value="" disabled>Choose a Power User</option>{ownerReassignCandidates.map((member) => <option key={member.user_id} value={member.user_id}>{member.username}</option>)}</select><div className="modal-actions"><button type="button" className="secondary-button" disabled={reassigningOwner} onClick={() => setOwnerReassignProject(null)}>Cancel</button><button type="submit" className="danger-button" disabled={reassigningOwner || !newOwnerId}>{reassigningOwner ? "Changing..." : "Change owner"}</button></div></form>}{ownerReassignCandidates.length === 0 && <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setOwnerReassignProject(null)}>Close</button></div>}</section></div>}
      {projectPendingPurge && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="project-purge-title"><p className="eyebrow">Permanent purge</p><h3 id="project-purge-title">Permanently delete {projectPendingPurge.name}?</h3><p className="muted">This removes the project, all its files, revisions, calculations, summaries, and questions, and its on-disk storage — permanently. This cannot be undone.</p><div className="modal-actions"><button className="secondary-button" disabled={busyAction === `project-purge:${projectPendingPurge.id}`} onClick={() => setProjectPendingPurge(null)}>Cancel</button><button className="danger-button" disabled={busyAction === `project-purge:${projectPendingPurge.id}`} onClick={() => void confirmPurgeArchivedProject()}>{busyAction === `project-purge:${projectPendingPurge.id}` ? "Purging..." : "Permanently delete"}</button></div></section></div>}
      {archivedFilesPendingBatchPurge && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="batch-purge-title"><p className="eyebrow">Permanent purge</p><h3 id="batch-purge-title">Permanently delete {archivedFilesPendingBatchPurge.length} file{archivedFilesPendingBatchPurge.length === 1 ? "" : "s"}?</h3><p className="muted">{archivedFilesPendingBatchPurge.map((file) => file.original_name).join(", ")}</p><p className="muted">This removes each archived file and its metadata. Accepted revisions and calculations remain, but the original sources cannot be restored.</p><div className="modal-actions"><button className="secondary-button" disabled={batchBusy !== null} onClick={() => setArchivedFilesPendingBatchPurge(null)}>Cancel</button><button className="danger-button" disabled={batchBusy !== null} onClick={() => void confirmBatchPurgeArchivedFiles()}>{batchBusy === "purge" ? "Purging..." : "Permanently delete"}</button></div></section></div>}
    </main>
  );
}
