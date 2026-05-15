"use client";
import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { examApi } from "@/lib/api";
import type { Exam, ExamResult } from "@/types";
import Icon from "@/components/ui/Icon";

function ExamContent() {
  const params = useSearchParams();
  const router = useRouter();
  const roadmapId = params.get("roadmapId") || "";
  const examId = params.get("examId") || "";

  const [exam, setExam] = useState<Exam | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [textAnswers, setTextAnswers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<ExamResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Timer
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const [timerActive, setTimerActive] = useState(false);

  useEffect(() => {
    if (examId) {
      setLoading(true);
      examApi.get(examId).then((e) => {
        setExam(e);
        if (e.time_limit) setTimeLeft(e.time_limit * 60);
        setLoading(false);
      }).catch(() => setLoading(false));
    }
  }, [examId]);

  useEffect(() => {
    if (!timerActive || timeLeft === null) return;
    if (timeLeft <= 0) { handleSubmit(); return; }
    const t = setInterval(() => setTimeLeft((p) => (p !== null ? p - 1 : null)), 1000);
    return () => clearInterval(t);
  }, [timerActive, timeLeft]);

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60).toString().padStart(2, "0");
    const s = (secs % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

  const handleGenerate = async () => {
    if (!roadmapId) return;
    setGenerating(true);
    setError("");
    try {
      const e = await examApi.generate(roadmapId, 10, 60);
      setExam(e);
      if (e.time_limit) setTimeLeft(e.time_limit * 60);
      router.replace(`/exam?examId=${e.id}&roadmapId=${roadmapId}`);
    } catch (e: any) { setError(e.message); }
    finally { setGenerating(false); }
  };

  const handleSubmit = useCallback(async () => {
    if (!exam?.id) return;
    setTimerActive(false);
    setSubmitting(true);
    setError("");
    try {
      const allAnswers = exam.questions.map((q) => ({
        question_id: q.id || "",
        answer: q.question_type === "mcq"
          ? (answers[q.id || ""] || "")
          : (textAnswers[q.id || ""] || ""),
      })).filter((a) => a.question_id);

      const res = await examApi.submit(exam.id, allAnswers);
      setResult(res);
    } catch (e: any) { setError(e.message); }
    finally { setSubmitting(false); }
  }, [exam, answers, textAnswers]);

  if (result) {
    return <ResultView result={result} onBack={() => router.push("/results")} />;
  }

  if (loading || generating) {
    return (
      <div className="max-w-[700px] mx-auto animate-fade-up">
        <div className="card text-center py-16">
          <div className="inline-block w-10 h-10 border-2 border-primary/30 border-t-primary rounded-full animate-spin mb-5" />
          <p className="text-txt-muted text-sm">{generating ? "Generating your exam…" : "Loading…"}</p>
        </div>
      </div>
    );
  }

  if (!exam && !examId) {
    return (
      <div className="max-w-[560px] mx-auto animate-fade-up">
        <div className="card text-center py-12">
          <div className="w-16 h-16 rounded-full bg-[rgba(168,85,247,0.12)] flex items-center justify-center mx-auto mb-5">
            <Icon name="award" size={28} className="text-[#A855F7]" />
          </div>
          <h2 className="font-display text-[24px] font-bold mb-2">Mock exam</h2>
          <p className="text-txt-muted text-sm mb-2 leading-[1.6]">
            10 questions · 60 minutes · AI-graded
          </p>
          <p className="text-txt-sub text-xs mb-8">
            Questions are generated from your uploaded study materials.
          </p>
          {error && (
            <div className="text-danger text-sm bg-danger-dim border border-[rgba(239,68,68,0.2)] rounded-[10px] px-4 py-3 mb-4 text-left">
              {error}
            </div>
          )}
          <button onClick={handleGenerate} className="btn btn-primary btn-lg">
            <Icon name="zap" size={16} /> Generate exam
          </button>
        </div>
      </div>
    );
  }

  if (!exam) return null;

  const answeredCount = exam.questions.filter((q) =>
    q.question_type === "mcq" ? answers[q.id || ""] : textAnswers[q.id || ""]
  ).length;

  return (
    <div className="max-w-[760px] animate-fade-up">
      {/* Header */}
      <div className="card mb-5 flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="font-display text-xl font-bold">{exam.title}</h2>
          <p className="text-txt-muted text-sm mt-1">
            {answeredCount} / {exam.questions.length} answered
          </p>
        </div>
        <div className="flex items-center gap-4">
          {timeLeft !== null && (
            <div className={`font-mono text-xl font-medium ${timeLeft < 300 ? "text-danger animate-pulse" : "text-accent"}`}>
              {formatTime(timeLeft)}
            </div>
          )}
          {!timerActive && timeLeft !== null && (
            <button onClick={() => setTimerActive(true)} className="btn btn-outline btn-sm">
              <Icon name="clock" size={14} /> Start timer
            </button>
          )}
          <button
            onClick={handleSubmit}
            disabled={submitting || answeredCount === 0}
            className="btn btn-primary"
          >
            {submitting ? (
              <><span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Submitting…</>
            ) : "Submit exam"}
          </button>
        </div>
      </div>

      {/* Progress */}
      <div className="mb-5">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${(answeredCount / exam.questions.length) * 100}%` }} />
        </div>
      </div>

      {error && (
        <div className="text-danger text-sm bg-danger-dim border border-[rgba(239,68,68,0.2)] rounded-[10px] px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {/* Questions */}
      <div className="flex flex-col gap-4">
        {exam.questions.map((q, idx) => (
          <div key={q.id || idx} className="exam-q">
            <div className="flex items-center justify-between mb-2">
              <span className="exam-q-num">
                Question {idx + 1} · {q.points} pt{q.points !== 1 ? "s" : ""}
              </span>
              <span className="badge badge-neutral text-xs">
                {q.question_type.replace("_", " ")}
              </span>
            </div>
            <p className="exam-q-text">{q.prompt}</p>

            {q.question_type === "mcq" && q.options && (
              <div>
                {q.options.map((opt) => (
                  <div
                    key={opt.label}
                    className={`choice ${answers[q.id || ""] === opt.label ? "selected" : ""}`}
                    onClick={() => setAnswers((p) => ({ ...p, [q.id || ""]: opt.label }))}
                  >
                    <div className="w-[26px] h-[26px] rounded-full border-[1.5px] border-current flex items-center justify-center text-xs font-semibold flex-shrink-0">
                      {opt.label}
                    </div>
                    {opt.content}
                  </div>
                ))}
              </div>
            )}

            {(q.question_type === "short_answer" || q.question_type === "structured") && (
              <textarea
                className="input mt-2"
                rows={q.question_type === "structured" ? 6 : 3}
                placeholder="Write your answer here…"
                value={textAnswers[q.id || ""] || ""}
                onChange={(e) => setTextAnswers((p) => ({ ...p, [q.id || ""]: e.target.value }))}
                style={{ resize: "vertical" }}
              />
            )}
          </div>
        ))}
      </div>

      <div className="mt-6 flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={submitting || answeredCount === 0}
          className="btn btn-primary btn-lg"
        >
          {submitting ? "Submitting…" : <><Icon name="send" size={16} /> Submit exam</>}
        </button>
      </div>
    </div>
  );
}

// ── Score ring SVG ──────────────────────────────────────
function ScoreRing({ score, size = 120 }: { score: number; size?: number }) {
  const r = size / 2 - 10;
  const circ = 2 * Math.PI * r;
  const fill = ((100 - score) / 100) * circ;
  const color = score >= 70 ? "#22C55E" : score >= 50 ? "#F5A623" : "#EF4444";

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={8} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={8}
          strokeDasharray={circ} strokeDashoffset={fill} strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 1s ease" }} />
      </svg>
      <div className="absolute text-center">
        <div className="font-display text-3xl font-bold text-txt leading-none">{score}</div>
        <div className="text-xs text-txt-muted mt-1">%</div>
      </div>
    </div>
  );
}

// ── Result view ─────────────────────────────────────────
function ResultView({ result, onBack }: { result: ExamResult; onBack: () => void }) {
  const grade = result.percentage >= 70 ? "Pass" : result.percentage >= 50 ? "Borderline" : "Fail";
  const gradeColor = result.percentage >= 70 ? "badge-success" : result.percentage >= 50 ? "badge-warning" : "badge-danger";

  return (
    <div className="max-w-[700px] mx-auto animate-fade-up">
      <div className="card text-center py-8 mb-5">
        <ScoreRing score={Math.round(result.percentage)} size={140} />
        <div className="mt-5 mb-3">
          <span className={`badge ${gradeColor} text-sm px-4 py-2`}>{grade}</span>
        </div>
        <h2 className="font-display text-2xl font-bold mb-1">
          {result.total_score.toFixed(1)} / {result.max_score.toFixed(1)} points
        </h2>
        <p className="text-txt-muted text-sm max-w-md mx-auto leading-[1.6] mt-2">{result.feedback}</p>
      </div>

      {/* Section scores */}
      <div className="card mb-5">
        <h3 className="font-display text-[17px] font-semibold mb-4">Score by chapter</h3>
        <div className="flex flex-col gap-3">
          {result.section_scores.map((s) => {
            const pct = s.max_score > 0 ? (s.score / s.max_score) * 100 : 0;
            return (
              <div key={s.chapter_id}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-txt">{s.chapter_title}</span>
                  <span className="text-txt-muted">{s.score.toFixed(1)}/{s.max_score.toFixed(1)}</span>
                </div>
                <div className="progress-bar">
                  <div
                    className={pct >= 70 ? "progress-fill-success" : "progress-fill"}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex gap-3 justify-center flex-wrap">
        <button onClick={onBack} className="btn btn-outline btn-lg">
          <Icon name="star" size={16} /> View all results
        </button>
      </div>
    </div>
  );
}


export default function ExamPage() {
  return (
    <Suspense fallback={
      <div className="flex justify-center py-12">
        <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    }>
      <ExamContent />
    </Suspense>
  );
}