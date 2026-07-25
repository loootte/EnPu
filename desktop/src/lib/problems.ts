/**
 * Score problem tags (#46 / P4-G) — mirrored from core score.extra.problems.
 */

import type { Score, ScoreProblem, ScoreProblemKind } from "./types";

export const PROBLEM_KIND_LABELS: Record<ScoreProblemKind, string> = {
  low_confidence: "低置信度",
  meter_over: "时值过满",
  meter_under: "时值不足",
  empty_measure: "空小节",
  layout_pollution: "版面污染",
  geometry_pitch: "几何音高",
  other: "其他",
};

export const PROBLEM_KIND_COLORS: Record<ScoreProblemKind, string> = {
  low_confidence: "border-amber-500/40 bg-amber-500/10 text-amber-100",
  meter_over: "border-rose-500/40 bg-rose-500/10 text-rose-100",
  meter_under: "border-orange-500/40 bg-orange-500/10 text-orange-100",
  empty_measure: "border-slate-400/40 bg-slate-500/10 text-slate-200",
  layout_pollution: "border-violet-500/40 bg-violet-500/10 text-violet-100",
  geometry_pitch: "border-sky-500/40 bg-sky-500/10 text-sky-100",
  other: "border-white/15 bg-white/5 text-slate-200",
};

export function problemsFromScore(score: Score | null | undefined): ScoreProblem[] {
  if (!score) return [];
  const raw = score.extra?.problems;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (p): p is ScoreProblem =>
      p != null &&
      typeof p === "object" &&
      typeof (p as ScoreProblem).id === "string" &&
      typeof (p as ScoreProblem).kind === "string" &&
      typeof (p as ScoreProblem).message === "string",
  );
}

export function problemMeasureNumbers(problems: ScoreProblem[]): number[] {
  const set = new Set<number>();
  for (const p of problems) {
    if (p.measure != null && p.measure >= 1) set.add(p.measure);
  }
  return [...set].sort((a, b) => a - b);
}
