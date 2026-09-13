"use client";

import { FormEvent, useEffect, useState } from "react";

type Project = {
  id: string;
  name: string;
  description: string | null;
  default_unit_system: string;
};

type SourceFile = {
  id: string;
  original_name: string;
  size_bytes: number;
  status: string;
  checksum: string;
};

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function ProjectWorkspace() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [projectName, setProjectName] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [message, setMessage] = useState("Ready for your first project.");
  const [loading, setLoading] = useState(false);

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
        setSelectedProject(data[0]);
        const filesResponse = await fetch(`${apiUrl}/projects/${data[0].id}/files`);
        if (filesResponse.ok) setFiles(await filesResponse.json());
      }
    }

    void loadInitialProjects();
  }, []);

  async function selectProject(project: Project) {
    setSelectedProject(project);
    const response = await fetch(`${apiUrl}/projects/${project.id}/files`);
    if (response.ok) {
      setFiles(await response.json());
    }
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
    } else {
      setMessage("Project could not be created.");
    }
    setLoading(false);
  }

  async function uploadFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject || !selectedFile) return;
    setLoading(true);
    const formData = new FormData();
    formData.append("file", selectedFile);
    const response = await fetch(`${apiUrl}/projects/${selectedProject.id}/files`, {
      method: "POST",
      body: formData,
    });
    if (response.ok) {
      const uploadedFile: SourceFile = await response.json();
      setFiles((current) => [...current, uploadedFile]);
      setSelectedFile(null);
      setMessage("File uploaded and queued for processing.");
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
    const response = await fetch(
      `${apiUrl}/projects/${selectedProject.id}/files/${file.id}/process`,
      { method: "POST" },
    );
    if (response.ok) {
      const job: { status: string } = await response.json();
      setFiles((current) =>
        current.map((item) => (item.id === file.id ? { ...item, status: job.status } : item)),
      );
      setMessage(`${file.original_name} processing status: ${job.status}.`);
    }
  }

  return (
    <main className="workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">Civil engineering intelligence</p>
          <h1>Project workspace</h1>
        </div>
        <span className="status">Phase 2 active</span>
      </header>

      <section className="workspace-grid">
        <aside className="project-panel">
          <p className="eyebrow">Projects</p>
          <form className="create-form" onSubmit={createProject}>
            <label htmlFor="project-name">New project</label>
            <div className="input-row">
              <input
                id="project-name"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                placeholder="Oak Street Site"
                maxLength={200}
              />
              <button type="submit" disabled={loading} aria-label="Create project">
                +
              </button>
            </div>
          </form>
          <div className="project-list">
            {projects.length === 0 && <p className="muted">No projects yet.</p>}
            {projects.map((project) => (
              <button
                className={`project-item ${selectedProject?.id === project.id ? "selected" : ""}`}
                key={project.id}
                onClick={() => void selectProject(project)}
              >
                <span>{project.name}</span>
                <small>{project.default_unit_system}</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="project-detail">
          {selectedProject ? (
            <>
              <div className="detail-heading">
                <div>
                  <p className="eyebrow">Active project</p>
                  <h2>{selectedProject.name}</h2>
                </div>
                <span className="project-mark">01</span>
              </div>
              <div className="upload-panel">
                <div>
                  <p className="eyebrow">Source files</p>
                  <h3>Bring the plan into focus.</h3>
                  <p className="muted">PDF, DXF, CSV, TXT, and TIFF files up to 50 MB.</p>
                </div>
                <form className="upload-form" onSubmit={uploadFile}>
                  <label className="file-picker" htmlFor="source-file">
                    <span>{selectedFile?.name ?? "Choose a source file"}</span>
                    <input
                      id="source-file"
                      type="file"
                      accept=".pdf,.dxf,.csv,.txt,.tif,.tiff"
                      onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                    />
                  </label>
                  <button type="submit" disabled={loading || selectedFile === null}>
                    Upload file
                  </button>
                </form>
              </div>
              <div className="file-list">
                <div className="list-heading">
                  <span>File</span>
                  <span>Status</span>
                </div>
                {files.length === 0 && <p className="muted">Uploaded files will appear here.</p>}
                {files.map((file) => (
                  <div className="file-row" key={file.id}>
                    <div>
                      <strong>{file.original_name}</strong>
                      <small>{Math.ceil(file.size_bytes / 1024)} KB</small>
                    </div>
                    <div className="file-status">
                      <span>{file.status}</span>
                      {file.status === "queued" && (
                        <button onClick={() => void processFile(file)}>Process</button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <p className="message" role="status">{message}</p>
            </>
          ) : (
            <div className="empty-detail">
              <p className="eyebrow">Start here</p>
              <h2>Create your first project.</h2>
              <p className="muted">Your project becomes the home for plans, source files, and measured results.</p>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}
