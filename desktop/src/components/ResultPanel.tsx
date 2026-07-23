import { useState } from "react";
import type { RecognizeResponse, Score } from "../lib/types";
import { ScoreEditor } from "./ScoreEditor";

type Tab = "edit" | "texts" | "notes" | "json";

interface ResultPanelProps {
  result: RecognizeResponse | null;
  loading: boolean;
  /** Working score (editable). When null and result has score, parent should seed it. */
  score: Score | null;
  onScoreChange: (score: Score) => void;
  coreOnline?: boolean;
  onMessage?: (kind: "info" | "error", message: string) => void;
}

export function ResultPanel({
  result,
  loading,
  score,
  onScoreChange,
  coreOnline = true,
  onMessage,
}: ResultPanelProps) {
  const [tab, setTab] = useState<Tab>("edit");

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-white/10 bg-slate-950/50">
        <div className="flex items-center gap-3 text-sm text-indigo-200">
          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-indigo-300 border-t-transparent" />
          识别中…
        </div>
      </div>
    );
  }

  if (!result && !score) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 rounded-xl border border-white/10 bg-slate-950/50 text-sm text-slate-500">
        <p>识别结果将显示在这里</p>
        <p className="text-xs text-slate-600">
          也可打开 .enpu.json / Score JSON 工程
        </p>
      </div>
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "edit", label: "编辑 / 试听 / 导出" },
    { id: "texts", label: "OCR 文本" },
    { id: "notes", label: "音高提示" },
    { id: "json", label: "JSON" },
  ];

  return (
    <div className="flex min-h-64 flex-col rounded-xl border border-white/10 bg-slate-950/50">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/5 px-3 py-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={[
              "rounded-md px-2.5 py-1 text-xs font-medium transition",
              tab === t.id
                ? "bg-indigo-500/30 text-indigo-100"
                : "text-slate-400 hover:bg-white/5 hover:text-slate-200",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex flex-wrap gap-2 text-[11px] text-slate-500">
          {result ? (
            <>
              <span>engine: {result.engine}</span>
              {result.meta.parse_mode ? (
                <span className="text-sky-300">
                  parse: {result.meta.parse_mode}
                </span>
              ) : null}
              {result.meta.mock ? (
                <span className="text-amber-400">mock</span>
              ) : null}
              <span>{result.meta.elapsed_ms} ms</span>
            </>
          ) : (
            <span className="text-slate-400">仅工程编辑</span>
          )}
        </div>
      </div>

      <div className="max-h-[520px] flex-1 overflow-auto p-3">
        {tab === "edit" && (
          <>
            {score ? (
              <ScoreEditor
                score={score}
                onChange={onScoreChange}
                sourceImage={result?.meta.filename}
                coreOnline={coreOnline}
                onMessage={onMessage}
              />
            ) : (
              <p className="text-sm text-slate-500">
                （未生成 Score
                {result?.meta.parse_mode
                  ? ` · mode=${result.meta.parse_mode}`
                  : ""}
                。可打开工程或重新识别。）
              </p>
            )}
            {result?.meta.parse_warnings &&
            result.meta.parse_warnings.length > 0 ? (
              <ul className="mt-3 list-disc pl-4 text-xs text-amber-300/90">
                {result.meta.parse_warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : null}
          </>
        )}

        {tab === "texts" && (
          <ul className="space-y-1.5">
            {!result || result.texts.length === 0 ? (
              <li className="text-sm text-slate-500">（无文本）</li>
            ) : (
              result.texts.map((t, i) => (
                <li
                  key={`${i}-${t}`}
                  className="rounded-md bg-white/5 px-2.5 py-1.5 font-mono text-sm text-slate-100"
                >
                  {t}
                </li>
              ))
            )}
          </ul>
        )}

        {tab === "notes" && (
          <ul className="flex flex-wrap gap-2">
            {!result || result.notes.length === 0 ? (
              <li className="text-sm text-slate-500">（未提取到数字音高）</li>
            ) : (
              result.notes.map((n, i) => (
                <li
                  key={`${i}-${n.pitch}-${n.text}`}
                  className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 font-mono text-sm text-emerald-100"
                  title={n.text ?? undefined}
                >
                  {n.pitch ?? "?"}
                </li>
              ))
            )}
          </ul>
        )}

        {tab === "json" && (
          <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-slate-200">
            {JSON.stringify(
              score
                ? { score, recognize: result }
                : result,
              null,
              2,
            )}
          </pre>
        )}
      </div>
    </div>
  );
}
