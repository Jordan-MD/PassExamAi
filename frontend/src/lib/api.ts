import { getSupabaseClient } from "./supabase";
import type {
  Project, UploadedDocument, DocumentIngestResponse, DocumentStatusResponse,
  Roadmap, Lesson, Exercise, GradingResult, Exam, ExamResult, ProjectProgress,
  UserSource, ChatMessage,
} from "@/types";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 15_000; // 15 secondes max

// ── Auth helper ────────────────────────────────────────────

async function getAuthHeaders(): Promise<HeadersInit> {
  const supabase = getSupabaseClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token) throw new Error("Not authenticated");
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.access_token}`,
  };
}

// ── Core fetch avec timeout ────────────────────────────────

async function apiRequest<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = await getAuthHeaders();

  // Timeout via AbortController — évite le spinner infini si le backend crash
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(`${BACKEND}/api/v1${path}`, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) },
      signal: controller.signal,
    });

    if (!res.ok) {
      // Tente de lire le message d'erreur JSON du backend (FastAPI retourne {"detail": "..."})
      let detail = `HTTP ${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        detail = body.detail || body.message || detail;
      } catch {
        // Le body n'était pas du JSON (ex: 504 HTML de reverse proxy)
      }
      throw new Error(detail);
    }

    // 204 No Content — pas de body à parser
    if (res.status === 204) return undefined as T;

    return res.json();
  } catch (err: any) {
    if (err.name === "AbortError") {
      throw new Error(`Request timed out (>${REQUEST_TIMEOUT_MS / 1000}s) — backend unreachable`);
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ── Projects ───────────────────────────────────────────────

export const projectsApi = {
  list: () => apiRequest<Project[]>("/projects"),
  get: (id: string) => apiRequest<Project>(`/projects/${id}`),
  create: (data: {
    title: string;
    subject?: string;
    target_exam_type?: string;
    deadline?: string;
    hours_per_day?: number;
    days_per_week?: number;
  }) => apiRequest<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
  delete: (id: string) => apiRequest<void>(`/projects/${id}`, { method: "DELETE" }),
};

// ── Documents ──────────────────────────────────────────────

export const documentsApi = {
  list: (projectId: string) =>
    apiRequest<UploadedDocument[]>(`/documents?project_id=${projectId}`),
  ingest: (data: {
    storage_url: string;
    filename: string;
    project_id: string;
    source_type: string;
  }) => apiRequest<DocumentIngestResponse>("/documents/ingest", {
    method: "POST",
    body: JSON.stringify(data),
  }),
  getStatus: (documentId: string) =>
    apiRequest<DocumentStatusResponse>(`/documents/${documentId}/status`),
  delete: (id: string) => apiRequest<void>(`/documents/${id}`, { method: "DELETE" }),
};

// ── Sources (user links) ───────────────────────────────────

export const sourcesApi = {
  list: (projectId: string) =>
    apiRequest<UserSource[]>(`/sources?project_id=${projectId}`),
  add: (data: { url: string; title?: string; project_id: string }) =>
    apiRequest<{ source_id: string; status: string }>("/sources", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getStatus: (sourceId: string) =>
    apiRequest<UserSource>(`/sources/${sourceId}/status`),
};

// ── Roadmap ────────────────────────────────────────────────

export const roadmapApi = {
  generate: (projectId: string) =>
    apiRequest<Roadmap>("/roadmap/generate", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
    }),
  get: (roadmapId: string) => apiRequest<Roadmap>(`/roadmap/${roadmapId}`),
  list: (projectId: string) =>
    apiRequest<Roadmap[]>(`/roadmap?project_id=${projectId}`),
};

// ── Chapters ───────────────────────────────────────────────

export const chaptersApi = {
  getLesson: (chapterId: string, useWebEnrichment = true) =>
    apiRequest<Lesson>(`/chapters/${chapterId}/lesson`, {
      method: "POST",
      body: JSON.stringify({ use_web_enrichment: useWebEnrichment }),
    }),

  // Streaming chat — retourne un ReadableStream
  chat: async (
    chapterId: string,
    message: string,
    history: ChatMessage[]
  ): Promise<ReadableStream<Uint8Array>> => {
    const headers = await getAuthHeaders();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const res = await fetch(`${BACKEND}/api/v1/chapters/${chapterId}/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({ message, history }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`Chat error ${res.status}`);
      return res.body!;
    } finally {
      clearTimeout(timeoutId);
    }
  },

  getExercises: (chapterId: string, count = 5, types?: string[]) =>
    apiRequest<Exercise[]>(`/chapters/${chapterId}/exercises`, {
      method: "POST",
      body: JSON.stringify({ count, types }),
    }),

  gradeAnswer: (exerciseId: string, answer: string) =>
    apiRequest<GradingResult>(`/chapters/exercises/${exerciseId}/grade`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),

  complete: (chapterId: string) =>
    apiRequest<{ status: string }>(`/chapters/${chapterId}/complete`, {
      method: "POST",
    }),
};

// ── Exam ───────────────────────────────────────────────────

export const examApi = {
  generate: (roadmapId: string, questionCount = 10, timeLimit?: number) =>
    apiRequest<Exam>("/exam/generate", {
      method: "POST",
      body: JSON.stringify({
        roadmap_id: roadmapId,
        question_count: questionCount,
        time_limit: timeLimit,
      }),
    }),
  get: (examId: string) => apiRequest<Exam>(`/exam/${examId}`),
  submit: (examId: string, answers: { question_id: string; answer: string }[]) =>
    apiRequest<ExamResult>(`/exam/${examId}/submit`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
};

// ── Progress ───────────────────────────────────────────────

export const progressApi = {
  get: (projectId: string) =>
    apiRequest<ProjectProgress>(`/progress?project_id=${projectId}`),
};