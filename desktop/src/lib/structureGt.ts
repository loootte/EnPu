/**
 * Build evaluation GT from structure-layer boxes (#86).
 * Users edit L1–L5 in the UI; those boxes become geometry ground truth
 * without a separate annotation tool.
 */

import type { Score, StructureBox, StructureDebug } from "./types";

function boxOf(it: StructureBox): {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
} | null {
  const b = it.box;
  if (
    b == null ||
    b.x1 == null ||
    b.y1 == null ||
    b.x2 == null ||
    b.y2 == null
  ) {
    return null;
  }
  return { x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 };
}

/**
 * Convert StructureDebug (+ optional Score) into GT JSON accepted by
 * ``/v1/evaluation/compare`` and param tuner.
 */
export function structureToEvalGt(
  structure: StructureDebug,
  score?: Score | null,
  opts?: { label?: string },
): Record<string, unknown> {
  const items = structure.items ?? [];
  const l1 = items.filter((it) => it.layer === "L1");
  const l2 = items.filter((it) => it.layer === "L2");
  const l3 = items.filter((it) => it.layer === "L3");
  const l4 = items.filter((it) => it.layer === "L4");

  const regions = l1
    .map((it) => {
      const box = boxOf(it);
      if (!box) return null;
      const role =
        it.kind === "title" ||
        it.kind === "score" ||
        it.kind === "meta" ||
        it.kind === "key_time"
          ? it.kind
          : it.label?.includes("title")
            ? "title"
            : it.label?.includes("score") || it.kind === "region"
              ? "score"
              : it.kind || "region";
      return { role, kind: role, box, label: it.label };
    })
    .filter(Boolean);

  const systems = l2
    .map((it, i) => {
      const box = boxOf(it);
      if (!box) return null;
      return { box, label: it.label || `sys${i}`, kind: "system" };
    })
    .filter(Boolean);

  const measures = l3
    .map((it, i) => {
      const box = boxOf(it);
      if (!box) return null;
      return { box, label: it.label || `m${i + 1}`, kind: "measure" };
    })
    .filter(Boolean);

  const notes = l4
    .map((it, i) => {
      const box = boxOf(it);
      if (!box) return null;
      const kind =
        it.kind === "chord" || it.kind === "lyric" ? it.kind : "pitch";
      return {
        box,
        kind,
        label: it.label || `n${i}`,
        pitch: it.pitch ?? undefined,
      };
    })
    .filter(Boolean);

  const barlines = (structure.barlines ?? [])
    .map((b) => Number(b.x))
    .filter((x) => Number.isFinite(x));

  // Pitch sequence from L5 boxes if present, else from score
  const l5 = items.filter((it) => it.layer === "L5" && it.pitch);
  let pitch_sequence: string[] = [];
  if (l5.length) {
    pitch_sequence = l5
      .map((it) => String(it.pitch))
      .filter((p) => p && p !== "null");
  } else if (score?.parts?.[0]?.measures) {
    for (const m of score.parts[0].measures) {
      for (const n of m.notes || []) {
        if (n.is_rest || !n.pitch) continue;
        let tag = String(n.pitch);
        if (n.accidental === "sharp") tag += "#";
        if (n.accidental === "flat") tag += "b";
        pitch_sequence.push(tag);
      }
    }
  }

  const measure_count =
    measures.length ||
    score?.parts?.[0]?.measures?.length ||
    Number(structure.summary?.n_measures) ||
    0;

  const system_count =
    systems.length || Number(structure.summary?.n_systems) || undefined;

  const gt: Record<string, unknown> = {
    schema_version: "0.1",
    title: score?.title || opts?.label || "annotation-from-edit",
    key: score?.key || "C",
    time_signature: score?.time_signature || "4/4",
    parts: score?.parts
      ? JSON.parse(JSON.stringify(score.parts))
      : [
          {
            id: "P1",
            name: "melody",
            measures: Array.from({ length: Math.max(measure_count, 1) }, (_, i) => ({
              number: i + 1,
              notes: [],
            })),
          },
        ],
    extra: {
      eval: {
        pitch_sequence,
        measure_count,
        ...(system_count != null ? { system_count } : {}),
        source: "ui_structure_edit",
        label: opts?.label || null,
      },
    },
    layers: {
      L1: { regions },
      L2: { systems },
      L3: { measures, barlines },
      L4: { notes },
    },
  };

  return gt;
}

/** Snapshot structure JSON (deep clone) for pred/GT freeze. */
export function cloneStructure(
  structure: StructureDebug | null | undefined,
): StructureDebug | null {
  if (!structure) return null;
  return JSON.parse(JSON.stringify(structure)) as StructureDebug;
}
