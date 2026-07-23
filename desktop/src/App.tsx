import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";

/**
 * Phase 0 shell (#4): prove Tauri + React + Tailwind window boots.
 * Image import / recognize UI lands in #5.
 */
function App() {
  const [greetMsg, setGreetMsg] = useState("");
  const [name, setName] = useState("恩谱");

  async function greet() {
    try {
      setGreetMsg(await invoke<string>("greet", { name: name || "EnPu" }));
    } catch (err) {
      setGreetMsg(`invoke failed: ${String(err)}`);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950">
      <div className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-12">
        <header className="mb-10 text-center">
          <p className="mb-2 text-sm font-medium tracking-[0.2em] text-indigo-300 uppercase">
            EnPu · Desktop PoC
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-white sm:text-5xl">
            恩谱
          </h1>
          <p className="mt-3 text-base text-slate-300">
            中文敬拜简谱 OMR 数字化工具 · Tauri 2 桌面壳
          </p>
        </header>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-6 shadow-xl backdrop-blur">
          <h2 className="text-lg font-semibold text-white">环境自检</h2>
          <p className="mt-1 text-sm text-slate-400">
            Tailwind 样式生效即表示前端栈就绪。下方按钮验证 Rust 命令通道。
          </p>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <input
              className="flex-1 rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-white outline-none ring-indigo-400 focus:ring-2"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="输入名字…"
              aria-label="greet name"
            />
            <button
              type="button"
              onClick={() => void greet()}
              className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-400 active:bg-indigo-600"
            >
              调用 greet
            </button>
          </div>

          {greetMsg ? (
            <p className="mt-4 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
              {greetMsg}
            </p>
          ) : null}

          <ul className="mt-6 space-y-2 text-sm text-slate-300">
            <li className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
              Tauri 2 + React + TypeScript + Tailwind
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
              识别 UI / 导入图片 → Issue #5
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
              对接本地 core（:8765）→ Issue #6
            </li>
          </ul>
        </section>

        <footer className="mt-8 text-center text-xs text-slate-500">
          Phase 0 · Shell only · core 服务需单独启动
        </footer>
      </div>
    </div>
  );
}

export default App;
