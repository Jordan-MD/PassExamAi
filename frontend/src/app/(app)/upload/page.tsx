"use client";
import { useState, useRef, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { getSupabaseClient } from "@/lib/supabase";
import { projectsApi, documentsApi, sourcesApi } from "@/lib/api";
import type { DocumentStatus, UserSource } from "@/types";
import Icon from "@/components/ui/Icon";

type Step = "project" | "files" | "done";

export default function UploadPage() {
  const [step, setStep] = useState<Step>("project");
  const [project, setProject] = useState({
    title: "", subject: "", target_exam_type: "",
    deadline: "", hours_per_day: "2", days_per_week: "5",
  });
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null);
  const [examFiles, setExamFiles] = useState<File[]>([]);
  const [sourceFiles, setSourceFiles] = useState<File[]>([]);
  const [links, setLinks] = useState<string[]>([""]);
  const [uploading, setUploading] = useState(false);
  const [tracking, setTracking] = useState(false);
  const [uploadedDocs, setUploadedDocs] = useState<
    { id: string; filename: string; kind: "exam" | "source"; status: DocumentStatus; error?: string }[]
  >([]);
  const [uploadedLinks, setUploadedLinks] = useState<
    { id: string; url: string; status: string; error?: string }[]
  >([]);
  const [error, setError] = useState("");
  const [dragExam, setDragExam] = useState(false);
  const [dragSource, setDragSource] = useState(false);
  const examFileInputRef = useRef<HTMLInputElement>(null);
  const sourceFileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const terminalDocumentStatuses: DocumentStatus[] = ["ready", "failed"];

  const isDoneTracking = useMemo(() => {
    const docsDone = uploadedDocs.every((d) => terminalDocumentStatuses.includes(d.status));
    const linksDone = uploadedLinks.every((s) => ["ready", "failed"].includes(s.status));
    return uploadedDocs.length + uploadedLinks.length > 0 && docsDone && linksDone;
  }, [uploadedDocs, uploadedLinks]);

  // ── Step 1: Create project ──
  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const p = await projectsApi.create({
        title: project.title,
        subject: project.subject || undefined,
        target_exam_type: project.target_exam_type || undefined,
        deadline: project.deadline || undefined,
        hours_per_day: project.hours_per_day ? parseFloat(project.hours_per_day) : undefined,
        days_per_week: project.days_per_week ? parseInt(project.days_per_week) : undefined,
      });
      setCreatedProjectId(p.id);
      setStep("files");
    } catch (e: any) {
      setError(e.message);
    }
  };

  // ── Step 2: Upload files ──
  const filterAcceptedFiles = (items: File[]) =>
    items.filter((f) => f.type === "application/pdf" || f.type === "text/plain");

  const handleDrop = (e: React.DragEvent, kind: "exam" | "source") => {
    e.preventDefault();
    const dropped = filterAcceptedFiles(Array.from(e.dataTransfer.files));
    if (kind === "exam") {
      setDragExam(false);
      setExamFiles((prev) => [...prev, ...dropped]);
      return;
    }
    setDragSource(false);
    setSourceFiles((prev) => [...prev, ...dropped]);
  };

  const handleFilePick = (e: React.ChangeEvent<HTMLInputElement>, kind: "exam" | "source") => {
    const picked = filterAcceptedFiles(Array.from(e.target.files || []));
    if (kind === "exam") {
      setExamFiles((prev) => [...prev, ...picked]);
      return;
    }
    setSourceFiles((prev) => [...prev, ...picked]);
  };

  const handleUploadAll = async () => {
    if (!createdProjectId) return;
    if (examFiles.length === 0) {
      setError("You must upload at least one reference exam before continuing.");
      return;
    }
    setUploading(true);
    setError("");
    setTracking(false);
    setUploadedDocs([]);
    setUploadedLinks([]);

    try {
      const supabase = getSupabaseClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Not authenticated");

      // Upload exam files first (mandatory)
      for (const file of examFiles) {
        const path = `${user.id}/${createdProjectId}/${Date.now()}_${file.name}`;
        const { error: storageError } = await supabase.storage
          .from("documents")
          .upload(path, file, { upsert: false });
        if (storageError) throw storageError;

        const { data: signedData, error: signedError } = await supabase.storage
          .from("documents")
          .createSignedUrl(path, 3600);
        if (signedError) throw signedError;

        const res = await documentsApi.ingest({
          storage_url: signedData.signedUrl,
          filename: file.name,
          project_id: createdProjectId,
          source_type: "exam",
        });
        setUploadedDocs((prev) => [
          ...prev,
          { id: res.document_id, filename: file.name, kind: "exam", status: res.status },
        ]);
      }

      // Upload optional source files
      for (const file of sourceFiles) {
        const path = `${user.id}/${createdProjectId}/${Date.now()}_${file.name}`;
        const { error: storageError } = await supabase.storage
          .from("documents")
          .upload(path, file, { upsert: false });
        if (storageError) throw storageError;

        const { data: signedData, error: signedError } = await supabase.storage
          .from("documents")
          .createSignedUrl(path, 3600);
        if (signedError) throw signedError;

        const res = await documentsApi.ingest({
          storage_url: signedData.signedUrl,
          filename: file.name,
          project_id: createdProjectId,
          source_type: "reference",
        });
        setUploadedDocs((prev) => [
          ...prev,
          { id: res.document_id, filename: file.name, kind: "source", status: res.status },
        ]);
      }

      // Add optional links
      for (const link of links.filter((l) => l.trim())) {
        const source = await sourcesApi.add({ url: link.trim(), project_id: createdProjectId });
        setUploadedLinks((prev) => [...prev, { id: source.source_id, url: link.trim(), status: source.status }]);
      }

      setStep("done");
      setTracking(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    if (!tracking || !createdProjectId) return;

    const poll = async () => {
      try {
        if (uploadedDocs.length > 0) {
          const updated = await Promise.all(
            uploadedDocs.map(async (doc) => {
              const res = await documentsApi.getStatus(doc.id);
              return {
                ...doc,
                status: res.status,
                error: res.error_message,
              };
            })
          );
          setUploadedDocs(updated);
        }

        if (uploadedLinks.length > 0) {
          const updatedLinks = await Promise.all(
            uploadedLinks.map(async (src) => {
              const res = await sourcesApi.getStatus(src.id);
              const typed = res as UserSource;
              return {
                ...src,
                status: typed.status,
                error: typed.error_message,
              };
            })
          );
          setUploadedLinks(updatedLinks);
        }
      } catch (e: any) {
        setError(e.message || "Unable to refresh ingestion status.");
      }
    };

    void poll();
    const interval = setInterval(() => void poll(), 2500);
    return () => clearInterval(interval);
  }, [tracking, createdProjectId, uploadedDocs, uploadedLinks]);

  if (step === "done") {
    const inProgressCount =
      uploadedDocs.filter((d) => !terminalDocumentStatuses.includes(d.status)).length +
      uploadedLinks.filter((s) => !["ready", "failed"].includes(s.status)).length;

    return (
      <div className="max-w-[600px] mx-auto animate-fade-up">
        <div className="card py-10">
          <div className="w-16 h-16 rounded-full bg-success-dim flex items-center justify-center mx-auto mb-5">
            <Icon name="check" size={32} className="text-success" />
          </div>
          <h2 className="font-display text-[26px] font-bold mb-2 text-center">
            Upload completed
          </h2>
          <p className="text-txt-muted text-sm mb-6 leading-[1.6] text-center">
            We are tracking each ingestion step in real time. You can open the roadmap now, but generation is only available once your reference exam is ready.
          </p>

          <div className="flex flex-col gap-2 mb-7">
            {uploadedDocs.map((doc) => (
              <div key={doc.id} className="bg-bg-surf border border-[rgba(255,255,255,0.07)] rounded-[10px] px-4 py-3">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-txt truncate">
                    {doc.kind === "exam" ? "Reference exam: " : "Source file: "}
                    {doc.filename}
                  </span>
                  <span className="text-txt-muted">{doc.status}</span>
                </div>
                {doc.error && <p className="text-danger text-xs mt-1">{doc.error}</p>}
              </div>
            ))}
            {uploadedLinks.map((source) => (
              <div key={source.id} className="bg-bg-surf border border-[rgba(255,255,255,0.07)] rounded-[10px] px-4 py-3">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-txt truncate">Web source: {source.url}</span>
                  <span className="text-txt-muted">{source.status}</span>
                </div>
                {source.error && <p className="text-danger text-xs mt-1">{source.error}</p>}
              </div>
            ))}
          </div>

          {inProgressCount > 0 && (
            <div className="flex items-center gap-2 text-sm text-txt-muted mb-6 justify-center">
              <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              {inProgressCount} item(s) still processing...
            </div>
          )}

          <div className="flex gap-3 justify-center flex-wrap">
            <button
              onClick={() => router.push(`/roadmap?projectId=${createdProjectId}`)}
              className="btn btn-primary btn-lg"
            >
              <Icon name="map" size={16} /> Generate roadmap
            </button>
            <button onClick={() => router.push("/dashboard")} className="btn btn-outline btn-lg">
              Dashboard
            </button>
            {!isDoneTracking && (
              <button onClick={() => setTracking(true)} className="btn btn-ghost btn-lg">
                Refresh status
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (step === "files") {
    return (
      <div className="max-w-[640px] mx-auto animate-fade-up">
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-1">
            <span className="badge badge-success">Step 2 of 2</span>
          </div>
          <h2 className="font-display text-[24px] font-bold">Add your study materials</h2>
          <p className="text-txt-muted text-sm mt-1">
            Add at least one reference exam, then optionally add extra sources.
          </p>
        </div>

        <div className="mb-2">
          <label className="label">Reference exam (required)</label>
          <p className="text-xs text-txt-sub mb-3">
            Mandatory: upload one or more exam papers used as the primary roadmap reference.
          </p>
        </div>

        {/* Exam dropzone */}
        <div
          className={`dropzone mb-5 ${dragExam ? "drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragExam(true);
          }}
          onDragLeave={() => setDragExam(false)}
          onDrop={(e) => handleDrop(e, "exam")}
          onClick={() => examFileInputRef.current?.click()}
        >
          <div className="text-[40px] mb-3">📄</div>
          <h3 className="font-display text-xl mb-[6px] text-txt">
            Drop reference exam files here
          </h3>
          <p className="text-[13px] text-txt-muted">
            PDF or TXT only
          </p>
          <input
            ref={examFileInputRef}
            type="file"
            accept=".pdf,.txt"
            multiple
            className="hidden"
            onChange={(e) => handleFilePick(e, "exam")}
          />
        </div>

        {examFiles.length > 0 && (
          <div className="flex flex-col gap-2 mb-5">
            {examFiles.map((f, i) => (
              <div key={i} className="flex items-center gap-3 bg-bg-surf border border-[rgba(255,255,255,0.07)] rounded-[10px] px-4 py-3">
                <Icon name="file" size={16} className="text-primary flex-shrink-0" />
                <span className="text-sm text-txt flex-1 truncate">{f.name}</span>
                <span className="text-xs text-txt-muted">{(f.size / 1024).toFixed(0)} KB</span>
                <button onClick={() => setExamFiles((prev) => prev.filter((_, j) => j !== i))}
                  className="btn btn-icon btn-ghost w-6 h-6 text-txt-muted hover:text-danger">
                  <Icon name="x" size={14} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="mb-2 mt-1">
          <label className="label">Optional source files</label>
          <p className="text-xs text-txt-sub mb-3">
            Add notes, syllabus, or references to enrich the generated roadmap.
          </p>
        </div>

        <div
          className={`dropzone mb-5 ${dragSource ? "drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragSource(true);
          }}
          onDragLeave={() => setDragSource(false)}
          onDrop={(e) => handleDrop(e, "source")}
          onClick={() => sourceFileInputRef.current?.click()}
        >
          <div className="text-[40px] mb-3">🗂️</div>
          <h3 className="font-display text-xl mb-[6px] text-txt">
            Drop optional source files here
          </h3>
          <p className="text-[13px] text-txt-muted">
            PDF or TXT only
          </p>
          <input
            ref={sourceFileInputRef}
            type="file"
            accept=".pdf,.txt"
            multiple
            className="hidden"
            onChange={(e) => handleFilePick(e, "source")}
          />
        </div>

        {sourceFiles.length > 0 && (
          <div className="flex flex-col gap-2 mb-5">
            {sourceFiles.map((f, i) => (
              <div key={i} className="flex items-center gap-3 bg-bg-surf border border-[rgba(255,255,255,0.07)] rounded-[10px] px-4 py-3">
                <Icon name="file" size={16} className="text-primary flex-shrink-0" />
                <span className="text-sm text-txt flex-1 truncate">{f.name}</span>
                <span className="text-xs text-txt-muted">{(f.size / 1024).toFixed(0)} KB</span>
                <button onClick={() => setSourceFiles((prev) => prev.filter((_, j) => j !== i))}
                  className="btn btn-icon btn-ghost w-6 h-6 text-txt-muted hover:text-danger">
                  <Icon name="x" size={14} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Links */}
        <div className="mb-6">
          <label className="label">Supplementary web links (optional)</label>
          <p className="text-xs text-txt-sub mb-3">
            Articles, Wikipedia pages, or course materials that complement your documents.
          </p>
          {links.map((link, i) => (
            <div key={i} className="flex gap-2 mb-2">
              <input
                className="input"
                type="url"
                placeholder="https://en.wikipedia.org/wiki/..."
                value={link}
                onChange={(e) => {
                  const updated = [...links];
                  updated[i] = e.target.value;
                  setLinks(updated);
                }}
              />
              {links.length > 1 && (
                <button onClick={() => setLinks((prev) => prev.filter((_, j) => j !== i))}
                  className="btn btn-icon btn-ghost text-txt-muted hover:text-danger">
                  <Icon name="x" size={14} />
                </button>
              )}
            </div>
          ))}
          <button onClick={() => setLinks((prev) => [...prev, ""])}
            className="btn btn-ghost btn-sm text-primary mt-1">
            <Icon name="plus" size={14} /> Add another link
          </button>
        </div>

        {error && (
          <div className="text-danger text-sm bg-danger-dim border border-[rgba(239,68,68,0.2)] rounded-[10px] px-4 py-3 mb-4">
            {error}
          </div>
        )}

        <div className="flex gap-3">
          <button onClick={() => setStep("project")} className="btn btn-outline">
            ← Back
          </button>
          <button
            onClick={handleUploadAll}
            className="btn btn-primary flex-1 justify-center"
            disabled={uploading || examFiles.length === 0}
          >
            {uploading ? (
              <><span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Uploading…</>
            ) : (
              <><Icon name="upload" size={15} /> Upload & track progress</>
            )}
          </button>
        </div>
      </div>
    );
  }

  // Step 1: Project info
  return (
    <div className="max-w-[560px] mx-auto animate-fade-up">
      <div className="mb-6">
        <span className="badge badge-primary mb-2">Step 1 of 2</span>
        <h2 className="font-display text-[24px] font-bold">Create a study plan</h2>
        <p className="text-txt-muted text-sm mt-1">Tell us about your exam so we can personalize your roadmap.</p>
      </div>

      <form onSubmit={handleCreateProject} className="card flex flex-col gap-4">
        <div>
          <label className="label">Study plan name *</label>
          <input className="input" type="text" placeholder="e.g. GCE Advanced Mathematics 2026"
            value={project.title} onChange={(e) => setProject({ ...project, title: e.target.value })} required />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Subject</label>
            <input className="input" type="text" placeholder="Mathematics"
              value={project.subject} onChange={(e) => setProject({ ...project, subject: e.target.value })} />
          </div>
          <div>
            <label className="label">Exam type</label>
            <input className="input" type="text" placeholder="GCE A-Level"
              value={project.target_exam_type} onChange={(e) => setProject({ ...project, target_exam_type: e.target.value })} />
          </div>
        </div>

        <div>
          <label className="label flex items-center gap-2">
            <Icon name="clock" size={13} /> Exam deadline
          </label>
          <input className="input" type="date"
            value={project.deadline} onChange={(e) => setProject({ ...project, deadline: e.target.value })} />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Hours per day</label>
            <input className="input" type="number" min="0.5" max="12" step="0.5"
              value={project.hours_per_day} onChange={(e) => setProject({ ...project, hours_per_day: e.target.value })} />
          </div>
          <div>
            <label className="label">Days per week</label>
            <input className="input" type="number" min="1" max="7"
              value={project.days_per_week} onChange={(e) => setProject({ ...project, days_per_week: e.target.value })} />
          </div>
        </div>

        {error && (
          <div className="text-danger text-sm bg-danger-dim border border-[rgba(239,68,68,0.2)] rounded-[10px] px-4 py-3">
            {error}
          </div>
        )}

        <button type="submit" className="btn btn-primary w-full justify-center mt-2">
          Continue <Icon name="arrow" size={15} />
        </button>
      </form>
    </div>
  );
}
