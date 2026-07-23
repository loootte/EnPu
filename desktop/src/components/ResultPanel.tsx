import { useState } from "react";
import type { RecognizeResponse } from "../lib/types";

type Tab = "texts" | "notes" | "json";

interface ResultPanelProps {
  result: RecognizeResponse | null;
  loading: boolean;
}

export function ResultPanel({ result, loading }: ResultPanelProps) {
  const [tab, setTab] = useState<Tab>("texts");

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

  if (!result) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-white/10 bg-slate-950/50 text-sm text-slate-500">
        识别结果将显示在这里
      </div>
    );
  }

  const tabs: { id: Tab; label: string }[] = [
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
          <span>engine: {result.engine}</span>
          {result.meta.mock ? <span className="text-amber-400">mock</span> : null}
          <span>{result.meta.elapsed_ms} ms</span>
          <span>
            {result.meta.width}×{result.meta.height}
          </span>
        </div>
      </div>

      <div className="max-h-[420px] flex-1 overflow-auto p-3">
        {tab === "texts" && (
          <ul className="space-y-1.5">
            {result.texts.length === 0 ? (
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
            {result.notes.length === 0 ? (
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
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
