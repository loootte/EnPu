/**
 * Editable EnPu Score panel (issue #12).
 * Edit meta + notes; play via WebAudio; export JSON/MusicXML/MIDI/project.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { CoreApiError, exportScore, getCoreBaseUrl } from "../lib/api";
import { playScore, type PlaybackHandle } from "../lib/playback";
import {
  defaultNote,
  downloadBase64,
  downloadText,
  safeFilename,
  toProject,
} from "../lib/scoreUtils";
import {
  DURATION_OPTIONS,
  PITCH_OPTIONS,
  type Score,
  type ScoreNote,
} from "../lib/types";

interface ScoreEditorProps {
  score: Score;
  onChange: (score: Score) => void;
  sourceImage?: string | null;
  coreOnline?: boolean;
  disabled?: boolean;
  onMessage?: (kind: "info" | "error", message: string) => void;
}

function updateNote(
  score: Score,
  mi: number,
  ni: number,
  patch: Partial<ScoreNote>,
): Score {
  const next = structuredClone(score) as Score;
  const part = next.parts[0];
  if (!part) return score;
  const measure = part.measures[mi];
  if (!measure) return score;
  const note = measure.notes[ni];
  if (!note) return score;
  Object.assign(note, patch);
  if (patch.is_rest === true) {
    note.pitch = null;
  } else if (patch.is_rest === false && !note.pitch) {
    note.pitch = "1";
  }
  return next;
}

export function ScoreEditor({
  score,
  onChange,
  sourceImage,
  coreOnline = true,
  disabled = false,
  onMessage,
}: ScoreEditorProps) {
  const [playing, setPlaying] = useState(false);
  const [activeNote, setActiveNote] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const handleRef = useRef<PlaybackHandle | null>(null);
  const baseUrl = getCoreBaseUrl();
  const part = score.parts[0];

  const stopPlay = useCallback(() => {
    handleRef.current?.stop();
    handleRef.current = null;
    setPlaying(false);
    setActiveNote(null);
  }, []);

  useEffect(() => () => stopPlay(), [stopPlay]);

  const onPlay = () => {
    if (playing) {
      stopPlay();
      return;
    }
    try {
      stopPlay();
      setPlaying(true);
      handleRef.current = playScore(score, {
        onNote: (i) => setActiveNote(i),
        onEnd: () => {
          setPlaying(false);
          setActiveNote(null);
          handleRef.current = null;
        },
      });
    } catch (err) {
      setPlaying(false);
      onMessage?.(
        "error",
        err instanceof Error ? err.message : "播放失败",
      );
    }
  };

  const setMeta = (patch: Partial<Score>) => {
    onChange({ ...score, ...patch });
  };

  const addMeasure = () => {
    const next = structuredClone(score) as Score;
    const p = next.parts[0];
    if (!p) return;
    const num = (p.measures[p.measures.length - 1]?.number ?? 0) + 1;
    p.measures.push({
      number: num,
      notes: [defaultNote()],
    });
    onChange(next);
  };

  const addNote = (mi: number) => {
    const next = structuredClone(score) as Score;
    const m = next.parts[0]?.measures[mi];
    if (!m) return;
    m.notes.push(defaultNote());
    onChange(next);
  };

  const removeNote = (mi: number, ni: number) => {
    const next = structuredClone(score) as Score;
    const m = next.parts[0]?.measures[mi];
    if (!m || m.notes.length <= 1) return;
    m.notes.splice(ni, 1);
    onChange(next);
  };

  const exportJson = () => {
    const name = safeFilename(score.title || "enpu-score", ".json");
    downloadText(JSON.stringify(score, null, 2), name, "application/json");
    onMessage?.("info", `已下载 Score JSON：${name}`);
  };

  const saveProject = () => {
    const proj = toProject(score, sourceImage);
    const name = safeFilename(score.title || "enpu-project", ".enpu.json");
    downloadText(JSON.stringify(proj, null, 2), name, "application/json");
    onMessage?.("info", `已保存工程：${name}`);
  };

  const exportBinary = async (format: "musicxml" | "midi") => {
    if (exporting) return;
    setExporting(true);
    try {
      const res = await exportScore(score, format, baseUrl);
      downloadBase64(res.content_base64, res.filename, res.media_type);
      const warn =
        res.warnings?.length > 0 ? `（告警：${res.warnings.join("; ")}）` : "";
      onMessage?.(
        "info",
        `已导出 ${format.toUpperCase()}：${res.filename}${warn}`,
      );
    } catch (err) {
      const msg =
        err instanceof CoreApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err);
      onMessage?.("error", msg);
    } finally {
      setExporting(false);
    }
  };

  let flatIndex = -1;

  return (
    <div className="flex flex-col gap-3">
      {/* Meta */}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          标题
          <input
            disabled={disabled}
            className="rounded-md border border-white/10 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
            value={score.title ?? ""}
            onChange={(e) => setMeta({ title: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          调号 key
          <input
            disabled={disabled}
            className="rounded-md border border-white/10 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
            value={score.key ?? "C"}
            onChange={(e) => setMeta({ key: e.target.value })}
            placeholder="C / G / F / Bb"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          拍号
          <input
            disabled={disabled}
            className="rounded-md border border-white/10 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
            value={score.time_signature ?? "4/4"}
            onChange={(e) => setMeta({ time_signature: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          速度 BPM
          <input
            disabled={disabled}
            type="number"
            min={30}
            max={240}
            className="rounded-md border border-white/10 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
            value={score.tempo_bpm ?? 80}
            onChange={(e) =>
              setMeta({
                tempo_bpm: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </label>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={onPlay}
          className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
        >
          {playing ? "停止试听" : "试听旋律"}
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={exportJson}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/5"
        >
          导出 JSON
        </button>
        <button
          type="button"
          disabled={disabled || exporting || !coreOnline}
          onClick={() => void exportBinary("musicxml")}
          className="rounded-lg border border-indigo-400/40 bg-indigo-500/20 px-3 py-1.5 text-xs text-indigo-100 hover:bg-indigo-500/30 disabled:opacity-40"
          title={!coreOnline ? "需要 core 在线" : undefined}
        >
          {exporting ? "导出中…" : "导出 MusicXML"}
        </button>
        <button
          type="button"
          disabled={disabled || exporting || !coreOnline}
          onClick={() => void exportBinary("midi")}
          className="rounded-lg border border-indigo-400/40 bg-indigo-500/20 px-3 py-1.5 text-xs text-indigo-100 hover:bg-indigo-500/30 disabled:opacity-40"
        >
          导出 MIDI
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={saveProject}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/5"
        >
          保存工程
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={addMeasure}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5"
        >
          + 小节
        </button>
      </div>

      {/* Measures */}
      <div className="max-h-[360px] space-y-3 overflow-auto pr-1">
        {!part ? (
          <p className="text-sm text-slate-500">（无声部）</p>
        ) : (
          part.measures.map((m, mi) => (
            <div
              key={`m-${m.number}-${mi}`}
              className="rounded-lg border border-white/10 bg-white/[0.03] p-2"
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-slate-400">
                  小节 {m.number}
                </span>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => addNote(mi)}
                  className="text-[11px] text-indigo-300 hover:text-indigo-200 disabled:opacity-40"
                >
                  + 音符
                </button>
              </div>
              <div className="flex flex-col gap-1.5">
                {m.notes.map((n, ni) => {
                  flatIndex += 1;
                  const idx = flatIndex;
                  const active = playing && activeNote === idx;
                  return (
                    <div
                      key={`n-${mi}-${ni}`}
                      className={[
                        "grid grid-cols-[auto_auto_1fr_1fr_auto_auto] items-center gap-1.5 rounded-md px-1.5 py-1 sm:grid-cols-[auto_auto_auto_1fr_1fr_auto_auto]",
                        active
                          ? "bg-emerald-500/20 ring-1 ring-emerald-400/50"
                          : "bg-slate-900/40",
                      ].join(" ")}
                    >
                      <label className="flex items-center gap-1 text-[10px] text-slate-500">
                        <input
                          type="checkbox"
                          disabled={disabled}
                          checked={!!n.is_rest}
                          onChange={(e) =>
                            onChange(
                              updateNote(score, mi, ni, {
                                is_rest: e.target.checked,
                              }),
                            )
                          }
                        />
                        休
                      </label>
                      <select
                        disabled={disabled || !!n.is_rest}
                        className="rounded border border-white/10 bg-slate-950 px-1 py-0.5 font-mono text-xs text-slate-100 disabled:opacity-40"
                        value={n.pitch ?? "1"}
                        onChange={(e) =>
                          onChange(
                            updateNote(score, mi, ni, {
                              pitch: e.target.value,
                              is_rest: false,
                            }),
                          )
                        }
                      >
                        {PITCH_OPTIONS.map((p) => (
                          <option key={p} value={p}>
                            {p}
                          </option>
                        ))}
                      </select>
                      <select
                        disabled={disabled}
                        className="hidden rounded border border-white/10 bg-slate-950 px-1 py-0.5 text-xs text-slate-100 sm:block"
                        value={n.duration || "quarter"}
                        onChange={(e) =>
                          onChange(
                            updateNote(score, mi, ni, {
                              duration: e.target.value,
                            }),
                          )
                        }
                      >
                        {DURATION_OPTIONS.map((d) => (
                          <option key={d} value={d}>
                            {d}
                          </option>
                        ))}
                      </select>
                      <input
                        disabled={disabled}
                        type="number"
                        min={-2}
                        max={2}
                        title="八度"
                        className="w-12 rounded border border-white/10 bg-slate-950 px-1 py-0.5 text-xs text-slate-100"
                        value={n.octave ?? 0}
                        onChange={(e) =>
                          onChange(
                            updateNote(score, mi, ni, {
                              octave: Number(e.target.value) || 0,
                            }),
                          )
                        }
                      />
                      <input
                        disabled={disabled}
                        placeholder="歌词"
                        className="min-w-0 rounded border border-white/10 bg-slate-950 px-1.5 py-0.5 text-xs text-slate-100"
                        value={n.lyric ?? ""}
                        onChange={(e) =>
                          onChange(
                            updateNote(score, mi, ni, {
                              lyric: e.target.value || null,
                            }),
                          )
                        }
                      />
                      <button
                        type="button"
                        disabled={disabled || m.notes.length <= 1}
                        onClick={() => removeNote(mi, ni)}
                        className="text-[11px] text-rose-300/80 hover:text-rose-200 disabled:opacity-30"
                        title="删除音符"
                      >
                        ×
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>

      <p className="text-[11px] text-slate-500">
        试听使用浏览器 WebAudio（近似时值）。MusicXML / MIDI 经本地 core
        的 /v1/export 生成。工程文件为 .enpu.json，可再次打开。
      </p>
    </div>
  );
}
