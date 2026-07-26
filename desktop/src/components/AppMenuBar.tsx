/**
 * Top application menu bar: 文件 / 识别 / 导出 / 帮助.
 */

import { useEffect, useRef, useState } from "react";

export type MenuAction =
  | "file.openImage"
  | "file.openProject"
  | "file.saveProject"
  | "file.newScore"
  | "file.clear"
  | "recognize.run"
  | "recognize.crop"
  | "export.json"
  | "export.musicxml"
  | "export.midi"
  | "view.refreshHealth"
  | "help.about";

export interface AppMenuBarProps {
  disabled?: boolean;
  canRecognize?: boolean;
  canCrop?: boolean;
  canSave?: boolean;
  canExportBinary?: boolean;
  coreLabel?: string;
  coreOnline?: boolean;
  dirty?: boolean;
  projectName?: string | null;
  onAction: (action: MenuAction) => void;
}

type MenuId = "file" | "recognize" | "export" | "view" | "help" | null;

interface MenuItem {
  id: MenuAction | "sep";
  label?: string;
  shortcut?: string;
  disabled?: boolean;
}

export function AppMenuBar({
  disabled = false,
  canRecognize = false,
  canCrop = false,
  canSave = false,
  canExportBinary = false,
  coreLabel = "",
  coreOnline = false,
  dirty = false,
  projectName = null,
  onAction,
}: AppMenuBarProps) {
  const [open, setOpen] = useState<MenuId>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  const run = (action: MenuAction) => {
    setOpen(null);
    onAction(action);
  };

  const menus: {
    id: Exclude<MenuId, null>;
    label: string;
    items: MenuItem[];
  }[] = [
    {
      id: "file",
      label: "文件",
      items: [
        { id: "file.openImage", label: "打开图片…", shortcut: "Ctrl+O" },
        { id: "file.openProject", label: "打开工程…", shortcut: "Ctrl+Shift+O" },
        { id: "sep" },
        {
          id: "file.saveProject",
          label: dirty ? "保存工程… *" : "保存工程…",
          shortcut: "Ctrl+S",
          disabled: !canSave || disabled,
        },
        { id: "sep" },
        {
          id: "file.newScore",
          label: "新建空白谱",
          shortcut: "Ctrl+N",
          disabled: disabled,
        },
        { id: "file.clear", label: "清空工作区", disabled: disabled },
      ],
    },
    {
      id: "recognize",
      label: "识别",
      items: [
        {
          id: "recognize.run",
          label: "开始识别",
          shortcut: "Ctrl+Enter",
          disabled: !canRecognize || disabled,
        },
        {
          id: "recognize.crop",
          label: "局部重识别",
          shortcut: "Ctrl+Shift+R",
          disabled: !canCrop || disabled,
        },
      ],
    },
    {
      id: "export",
      label: "导出",
      items: [
        {
          id: "export.json",
          label: "导出 Score JSON",
          disabled: !canSave || disabled,
        },
        {
          id: "export.musicxml",
          label: "导出 MusicXML",
          disabled: !canExportBinary || disabled,
        },
        {
          id: "export.midi",
          label: "导出 MIDI",
          disabled: !canExportBinary || disabled,
        },
      ],
    },
    {
      id: "view",
      label: "视图",
      items: [
        { id: "view.refreshHealth", label: "刷新核心状态" },
      ],
    },
    {
      id: "help",
      label: "帮助",
      items: [{ id: "help.about", label: "关于恩谱" }],
    },
  ];

  return (
    <div
      ref={rootRef}
      className="flex shrink-0 flex-wrap items-center gap-1 border-b border-white/10 bg-slate-950/80 px-2 py-1 backdrop-blur"
    >
      <div className="mr-2 flex items-center gap-1.5 px-1">
        <span className="text-sm font-semibold tracking-tight text-white">
          恩谱
        </span>
        <span className="hidden text-[10px] text-slate-500 sm:inline">EnPu</span>
      </div>

      {menus.map((menu) => (
        <div key={menu.id} className="relative">
          <button
            type="button"
            className={[
              "rounded px-2.5 py-1 text-xs font-medium transition",
              open === menu.id
                ? "bg-white/15 text-white"
                : "text-slate-300 hover:bg-white/10 hover:text-white",
            ].join(" ")}
            onClick={() => setOpen((o) => (o === menu.id ? null : menu.id))}
            onMouseEnter={() => {
              if (open) setOpen(menu.id);
            }}
          >
            {menu.label}
          </button>
          {open === menu.id ? (
            <div className="absolute left-0 top-full z-50 mt-0.5 min-w-[12rem] rounded-md border border-white/15 bg-slate-900 py-1 shadow-xl shadow-black/40">
              {menu.items.map((item, i) =>
                item.id === "sep" ? (
                  <div
                    key={`sep-${i}`}
                    className="my-1 border-t border-white/10"
                  />
                ) : (
                  <button
                    key={item.id}
                    type="button"
                    disabled={item.disabled}
                    className="flex w-full items-center justify-between gap-6 px-3 py-1.5 text-left text-xs text-slate-200 hover:bg-indigo-500/25 disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => run(item.id as MenuAction)}
                  >
                    <span>{item.label}</span>
                    {item.shortcut ? (
                      <span className="text-[10px] text-slate-500">
                        {item.shortcut}
                      </span>
                    ) : null}
                  </button>
                ),
              )}
            </div>
          ) : null}
        </div>
      ))}

      <div className="ml-auto flex flex-wrap items-center gap-2 px-1 text-[11px] text-slate-500">
        {projectName ? (
          <span className="max-w-[12rem] truncate text-slate-400" title={projectName}>
            {dirty ? "● " : ""}
            {projectName}
          </span>
        ) : dirty ? (
          <span className="text-amber-400/90">未保存</span>
        ) : null}
        <span
          className={[
            "rounded-full px-2 py-0.5 text-[10px] font-medium",
            coreOnline
              ? "bg-emerald-500/20 text-emerald-200"
              : "bg-rose-500/15 text-rose-200",
          ].join(" ")}
          title={coreLabel}
        >
          {coreOnline ? "核心在线" : "核心离线"}
        </span>
      </div>
    </div>
  );
}
