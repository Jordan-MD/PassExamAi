"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { projectsApi } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase";
import type { Project } from "@/types";
import Icon from "@/components/ui/Icon";

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [userName, setUserName] = useState("there");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const supabase = getSupabaseClient();
    supabase.auth.getUser().then(({ data }) => {
      if (data.user) {
        const name = data.user.user_metadata?.full_name || data.user.email?.split("@")[0] || "there";
        setUserName(name);
      }
    });
    projectsApi.list().then((p) => { setProjects(p); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  const handleDeleteProject = async (projectId: string, title: string) => {
    const confirmed = window.confirm(`Delete "${title}"? This action cannot be undone.`);
    if (!confirmed) return;

    setDeletingId(projectId);
    setError("");
    try {
      await projectsApi.delete(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
    } catch (e: any) {
      setError(e.message || "Unable to delete this project.");
    } finally {
      setDeletingId(null);
    }
  };

  const stats = [
    { label: "Study projects", value: projects.length, icon: "layers", color: "#4F7EF5" },
    { label: "Chapters studied", value: "—", icon: "book", color: "#22C55E" },
    { label: "Exercises done", value: "—", icon: "pen", color: "#F5A623" },
    { label: "Mock exams taken", value: "—", icon: "award", color: "#A855F7" },
  ];

  return (
    <div className="animate-fade-up">
      {/* Header */}
      <div className="flex items-center justify-between mb-7 flex-wrap gap-4">
        <div>
          <h1 className="font-display text-[28px] font-bold">{greeting}, {userName} 👋</h1>
          <p className="text-txt-muted mt-1 text-sm">Ready to continue your revision?</p>
        </div>
        <Link href="/upload" className="btn btn-primary">
          <Icon name="plus" size={15} /> New study plan
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-7">
        {stats.map((s) => (
          <div key={s.label} className="card flex items-center gap-[14px]">
            <div className="w-10 h-10 rounded-[10px] flex items-center justify-center flex-shrink-0"
              style={{ background: s.color + "18", color: s.color }}>
              <Icon name={s.icon} size={18} />
            </div>
            <div>
              <div className="font-display text-2xl font-bold leading-[1.1]">{loading ? "—" : s.value}</div>
              <div className="text-xs text-txt-muted mt-[2px]">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Projects */}
      <h2 className="font-display text-xl mb-4">Your study plans</h2>
      {error && (
        <div className="text-danger text-sm bg-danger-dim border border-[rgba(239,68,68,0.2)] rounded-[10px] px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col gap-3">
          {[1, 2].map((i) => (
            <div key={i} className="skeleton h-[88px] w-full" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="empty-state card">
          <span className="text-[48px] mb-4 opacity-50">📚</span>
          <h3 className="font-display text-[22px] text-txt mb-2">No study plans yet</h3>
          <p className="text-sm max-w-[320px] leading-[1.6] mb-6">
            Upload an exam paper to generate your first personalized study roadmap.
          </p>
          <Link href="/upload" className="btn btn-primary">
            <Icon name="upload" size={15} /> Upload your first exam
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-[14px]">
          {projects.map((p) => (
            <div key={p.id} className="card card-hover flex items-center gap-5">
              <div className="w-12 h-12 rounded-xl bg-primary-dim flex items-center justify-center flex-shrink-0">
                <Icon name="book" size={22} className="text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-[10px] mb-1">
                  <span className="text-base font-semibold text-txt truncate">{p.title}</span>
                  <span className="badge badge-success">Active</span>
                </div>
                <div className="flex items-center gap-4 text-[13px] text-txt-muted flex-wrap">
                  {p.subject && <span>{p.subject}</span>}
                  {p.subject && p.target_exam_type && <span>•</span>}
                  {p.target_exam_type && <span>{p.target_exam_type}</span>}
                  {p.deadline && (
                    <>
                      <span>•</span>
                      <span className="flex items-center gap-1">
                        <Icon name="clock" size={12} /> Deadline: {new Date(p.deadline).toLocaleDateString()}
                      </span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex-shrink-0 flex items-center gap-2 flex-wrap justify-end">
                <Link href={`/roadmap?projectId=${p.id}`} className="btn btn-outline btn-sm">
                  Continue <Icon name="arrow" size={13} />
                </Link>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  title="Project editing will be added in the next iteration."
                >
                  <Icon name="pen" size={13} /> Edit soon
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm text-danger"
                  onClick={() => void handleDeleteProject(p.id, p.title)}
                  disabled={deletingId === p.id}
                >
                  {deletingId === p.id ? (
                    <><span className="inline-block w-3 h-3 border-2 border-danger/30 border-t-danger rounded-full animate-spin" /> Deleting…</>
                  ) : (
                    <><Icon name="x" size={13} /> Delete</>
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
