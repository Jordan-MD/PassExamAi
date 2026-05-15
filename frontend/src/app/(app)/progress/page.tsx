"use client";
import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { progressApi, projectsApi } from "@/lib/api";
import type { ProjectProgress, Project } from "@/types";
import Icon from "@/components/ui/Icon";

function ProgressContent() {
  const params = useSearchParams();
  const router = useRouter();
  const projectId = params.get("projectId") || "";

  const [progress, setProgress] = useState<ProjectProgress | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState(projectId);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    projectsApi.list().then((p) => {
      setProjects(p);
      if (!selectedProject && p.length > 0) setSelectedProject(p[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selectedProject) return;
    setLoading(true);
    progressApi.get(selectedProject)
      .then((p) => { setProgress(p); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedProject]);

  const statusIcon: Record<string, string> = {
    completed: "check",
    in_progress: "eye",
    available: "arrow",
    locked: "lock",
  };
  const statusColor: Record<string, string> = {
    completed: "text-success",
    in_progress: "text-primary",
    available: "text-txt-muted",
    locked: "text-txt-sub",
  };

  return (
    <div className="max-w-[760px] animate-fade-up">
      {/* Project selector */}
      {projects.length > 1 && (
        <div className="mb-5">
          <label className="label">Study plan</label>
          <select
            className="input max-w-xs"
            value={selectedProject}
            onChange={(e) => setSelectedProject(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.title}</option>
            ))}
          </select>
        </div>
      )}

      {loading ? (
        <div className="flex flex-col gap-4">
          <div className="skeleton h-[100px] w-full" />
          <div className="skeleton h-[400px] w-full" />
        </div>
      ) : !progress ? (
        <div className="card empty-state py-12">
          <Icon name="bar" size={40} className="opacity-40 mb-4" />
          <h3 className="font-display text-xl text-txt mb-2">No progress yet</h3>
          <p className="text-sm mb-5">Start studying chapters to track your progress.</p>
          <button onClick={() => router.push("/roadmap")} className="btn btn-primary">
            Go to roadmap
          </button>
        </div>
      ) : (
        <>
          {/* Overview cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            {[
              { label: "Total chapters", value: progress.total_chapters, color: "#4F7EF5" },
              { label: "Completed", value: progress.completed_chapters, color: "#22C55E" },
              { label: "In progress", value: progress.in_progress_chapters, color: "#F5A623" },
              { label: "Completion", value: `${progress.completion_percentage}%`, color: "#A855F7" },
            ].map((s) => (
              <div key={s.label} className="card text-center py-4">
                <div className="font-display text-2xl font-bold mb-1" style={{ color: s.color }}>
                  {s.value}
                </div>
                <div className="text-xs text-txt-muted">{s.label}</div>
              </div>
            ))}
          </div>

          {/* Progress bar global */}
          <div className="card mb-5">
            <div className="flex justify-between text-sm mb-2">
              <span className="text-txt font-medium">Overall progress</span>
              <span className="text-txt-muted">{progress.completion_percentage}%</span>
            </div>
            <div className="progress-bar h-[10px]">
              <div
                className="progress-fill-success"
                style={{ width: `${progress.completion_percentage}%`, height: "100%", borderRadius: "99px", transition: "width 0.8s ease" }}
              />
            </div>
          </div>

          {/* Chapter list */}
          <div className="card">
            <h3 className="font-display text-[17px] font-semibold mb-4">Chapter breakdown</h3>
            <div className="flex flex-col">
              {progress.chapters
                .sort((a, b) => a.chapter_order - b.chapter_order)
                .map((ch, i) => {
                  const pct = ch.completion_status === "completed" ? 100
                    : ch.completion_status === "in_progress" ? 45
                    : 0;

                  return (
                    <div
                      key={ch.chapter_id}
                      className={`flex items-center gap-4 py-3 ${i < progress.chapters.length - 1 ? "border-b border-[rgba(255,255,255,0.07)]" : ""}`}
                    >
                      <div className={`flex-shrink-0 ${statusColor[ch.completion_status]}`}>
                        <Icon name={statusIcon[ch.completion_status] || "lock"} size={16} />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium text-txt truncate">{ch.chapter_title}</span>
                          <span className="text-xs text-txt-muted ml-4 flex-shrink-0">
                            {ch.completion_status === "completed" ? "Done" :
                              ch.completion_status === "in_progress" ? "In progress" :
                              ch.completion_status === "available" ? "Ready" : "Locked"}
                          </span>
                        </div>
                        <div className="progress-bar h-[4px]">
                          <div
                            className={pct === 100 ? "progress-fill-success" : "progress-fill"}
                            style={{ width: `${pct}%`, height: "100%", borderRadius: "99px", transition: "width 0.6s ease" }}
                          />
                        </div>
                        {ch.last_seen_at && (
                          <p className="text-[11px] text-txt-sub mt-1">
                            Last studied {new Date(ch.last_seen_at).toLocaleDateString()}
                          </p>
                        )}
                      </div>

                      {ch.completion_status !== "locked" && (
                        <button
                          onClick={() => router.push(`/chapters/${ch.chapter_id}?projectId=${selectedProject}`)}
                          className="btn btn-outline btn-sm flex-shrink-0"
                        >
                          {ch.completion_status === "completed" ? "Review" : "Study"}
                        </button>
                      )}
                    </div>
                  );
                })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function ProgressPage() {
  return (
    <Suspense fallback={
      <div className="flex justify-center py-12">
        <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    }>
      <ProgressContent />
    </Suspense>
  );
}