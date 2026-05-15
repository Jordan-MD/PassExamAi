"use client";
import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Icon from "@/components/ui/Icon";

// For demo purposes - in production this would fetch from DB
const mockResults = [
  { id: "1", name: "Mock Exam 1", date: "Apr 11", percentage: 72, grade: "Pass", subject: "Operating Systems" },
  { id: "2", name: "Mock Exam 2", date: "Apr 8", percentage: 86, grade: "Distinction", subject: "Data Structures" },
  { id: "3", name: "Chapter 1 Quiz", date: "Apr 6", percentage: 90, grade: "Distinction", subject: "Intro to OS" },
];

function ScoreRingSmall({ score }: { score: number }) {
  const size = 44;
  const r = 17;
  const circ = 2 * Math.PI * r;
  const fill = ((100 - score) / 100) * circ;
  const color = score >= 70 ? "#22C55E" : score >= 50 ? "#F5A623" : "#EF4444";

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={22} cy={22} r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={4} />
        <circle cx={22} cy={22} r={r} fill="none" stroke={color} strokeWidth={4}
          strokeDasharray={circ} strokeDashoffset={fill} strokeLinecap="round" />
      </svg>
      <div className="absolute font-display text-xs font-bold" style={{ color }}>{score}</div>
    </div>
  );
}

function ResultsContent() {
  const params = useSearchParams();
  const router = useRouter();

  return (
    <div className="max-w-[800px] animate-fade-up">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        {[
          { label: "Exams taken", value: mockResults.length, color: "#4F7EF5", icon: "award" },
          { label: "Average score", value: `${Math.round(mockResults.reduce((a, r) => a + r.percentage, 0) / mockResults.length)}%`, color: "#22C55E", icon: "star" },
          { label: "Distinctions", value: mockResults.filter((r) => r.grade === "Distinction").length, color: "#F5A623", icon: "zap" },
        ].map((s) => (
          <div key={s.label} className="card flex items-center gap-3">
            <div className="w-10 h-10 rounded-[10px] flex items-center justify-center flex-shrink-0"
              style={{ background: s.color + "18", color: s.color }}>
              <Icon name={s.icon} size={18} />
            </div>
            <div>
              <div className="font-display text-2xl font-bold leading-[1.1]">{s.value}</div>
              <div className="text-xs text-txt-muted mt-[2px]">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* History table */}
      <div className="card">
        <h3 className="font-display text-[17px] font-semibold mb-4">Exam history</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-[rgba(255,255,255,0.07)]">
                {["Exam", "Subject", "Date", "Score", "Grade", ""].map((h) => (
                  <th key={h} className="text-left px-3 py-2 text-xs font-semibold text-txt-muted uppercase tracking-[.05em]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {mockResults.map((e) => (
                <tr key={e.id} className="border-b border-[rgba(255,255,255,0.07)] last:border-b-0 hover:bg-bg-surf/50 transition-colors">
                  <td className="px-3 py-3 font-medium text-txt">{e.name}</td>
                  <td className="px-3 py-3 text-txt-muted">{e.subject}</td>
                  <td className="px-3 py-3 text-txt-muted">{e.date}</td>
                  <td className="px-3 py-3">
                    <ScoreRingSmall score={e.percentage} />
                  </td>
                  <td className="px-3 py-3">
                    <span className={`badge ${e.percentage >= 70 ? "badge-success" : "badge-warning"}`}>
                      {e.grade}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right">
                    <button className="btn btn-ghost btn-sm text-txt-muted">
                      <Icon name="eye" size={14} /> Review
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* CTA */}
      <div className="card mt-5 flex items-center justify-between flex-wrap gap-4">
        <div>
          <h3 className="font-semibold text-txt mb-1">Ready for another exam?</h3>
          <p className="text-sm text-txt-muted">Practice makes perfect. Generate a new mock exam.</p>
        </div>
        <button onClick={() => router.push("/exam")} className="btn btn-primary">
          <Icon name="award" size={15} /> New mock exam
        </button>
      </div>
    </div>
  );
}

export default function ResultsPage() {
  return (
    <Suspense fallback={
      <div className="flex justify-center py-12">
        <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    }>
      <ResultsContent />
    </Suspense>
  );
}