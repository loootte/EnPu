/**
 * Problem navigation panel (#46 / P4-G).
 * Lists Score.extra.problems; click jumps to measure; filter by kind.
 */

import { useMemo, useState } from "react";
import {
  PROBLEM_KIND_COLORS,
  PROBLEM_KIND_LABELS,
  problemsFromScore,
} from "../lib/problems";
import type { Score, ScoreProblem, ScoreProblemKind } from "../lib/types";

interface ProblemNavPanelProps {
  score: Score | null | undefined;
  /** Currently focused problem id (optional highlight). */
  activeId?: string | null;
  onSelect?: (problem: ScoreProblem) => void;
  className?: string;
}

const ALL_KINDS = Object.keys(PROBLEM_KIND_LABELS) as ScoreProblemKind[];

export function ProblemNavPanel({
  score,
  activeId = null,
  onSelect,
  className = "",
}: ProblemNavPanelProps) {
  const problems = useMemo(() => problemsFromScore(score), [score]);
  const [kindFilter, setKindFilter] = useState<ScoreProblemKind | "all">("all");

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const p of problems) {
      c[p.kind] = (c[p.kind] ?? 0) + 1;
    }
    return c;
  }, [problems]);

  const filtered = useMemo(() => {
    if (kindFilter === "all") return problems;
    return problems.filter((p) => p.kind === kindFilter);
  }, [kindFilter, problems]);

  if (!score) {
    return (
      <div
        className={`rounded-xl border border-white/10 bg-slate-950/50 p-3 text-xs text-slate-500 ${className}`}
      >
        识别后显示问题导航（#46）
      </div>
    );
  }

  if (problems.length === 0) {
    return (
      <div
        className={`rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs text-emerald-200/90 ${className}`}
      >
        未检测到问题标签 · 共 0 项
      </div>
    );
  }

  return (
    <div
      className={`flex flex-col rounded-xl border border-white/10 bg-slate-950/50 ${className}`}
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/5 px-3 py-2">
        <h3 className="text-xs font-semibold text-slate-200">
          问题导航
          <span className="ml-1.5 font-normal text-slate-500">
            {filtered.length}/{problems.length}
          </span>
        </h3>
        <span className="text-[10px] text-slate-600">#46 P4-G</span>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-white/5 px-2 py-2">
        <FilterChip
          label="全部"
          count={problems.length}
          active={kindFilter === "all"}
          onClick={() => setKindFilter("all")}
        />
        {ALL_KINDS.map((k) =>
          counts[k] ? (
            <FilterChip
              key={k}
              label={PROBLEM_KIND_LABELS[k]}
              count={counts[k]!}
              active={kindFilter === k}
              onClick={() => setKindFilter(k)}
            />
          ) : null,
        )}
      </div>

      <ul className="max-h-48 space-y-1 overflow-y-auto p-2">
        {filtered.map((p) => {
          const kind = (p.kind in PROBLEM_KIND_LABELS
            ? p.kind
            : "other") as ScoreProblemKind;
          const color =
            PROBLEM_KIND_COLORS[kind] ?? PROBLEM_KIND_COLORS.other;
          const active = activeId === p.id;
          return (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => onSelect?.(p)}
                className={[
                  "flex w-full flex-col gap-0.5 rounded-lg border px-2 py-1.5 text-left transition",
                  color,
                  active
                    ? "ring-1 ring-indigo-400/60"
                    : "hover:brightness-110",
                ].join(" ")}
              >
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="font-medium">
                    {PROBLEM_KIND_LABELS[kind] ?? p.kind}
                  </span>
                  {p.measure != null ? (
                    <span className="text-white/70">m{p.measure}</span>
                  ) : null}
                  {p.note_index != null ? (
                    <span className="text-white/50">n{p.note_index + 1}</span>
                  ) : null}
                  {p.severity === "error" ? (
                    <span className="ml-auto text-[10px] text-rose-300">
                      error
                    </span>
                  ) : null}
                </div>
                <p className="text-[11px] leading-snug opacity-90">
                  {p.message}
                </p>
              </button>
            </li>
          );
        })}
        {filtered.length === 0 ? (
          <li className="px-1 py-2 text-[11px] text-slate-500">
            当前筛选下无问题
          </li>
        ) : null}
      </ul>
    </div>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-full px-2 py-0.5 text-[10px] font-medium transition",
        active
          ? "bg-indigo-500/40 text-indigo-50"
          : "bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200",
      ].join(" ")}
    >
      {label}
      <span className="ml-1 opacity-70">{count}</span>
    </button>
  );
}
