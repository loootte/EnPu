"""EnPu Train UI (#101) — Streamlit app.

Run from train/ directory::

    streamlit run ui/app.py

Flow: import .enpu.json -> Layout GT list -> train -> eval -> metrics.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

TRAIN_ROOT = Path(__file__).resolve().parents[1]
if str(TRAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAIN_ROOT))

from enpu_train.ui_backend import (  # noqa: E402
    DEFAULT_LAYOUT_ROOT,
    DEFAULT_RUNS,
    REPO_ROOT,
    TrainJobSpec,
    cancel_train_job,
    cuda_available,
    default_ckpt_for_run,
    import_enpu_project,
    inspect_layout_sample,
    list_runs,
    list_samples_info,
    load_history,
    poll_train_job,
    run_eval,
    start_train_job,
)

st.set_page_config(
    page_title="EnPu Train",
    page_icon="🎼",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("active_run_dir", None)
    ss.setdefault("last_eval", None)
    ss.setdefault("import_messages", [])
    ss.setdefault("layout_roots", [str(DEFAULT_LAYOUT_ROOT)])


def main() -> None:
    _init_state()
    st.title("EnPu Train — L1–L3 布局训练")
    st.caption(
        "父任务 #92 · UI #101 · 数据规范 data-spec · Framework #95。\n"
        "本界面**不是**恩谱桌面产品；改框/拖线请在桌面完成后再导入工程。"
    )

    with st.sidebar:
        st.header("路径")
        st.text(f"REPO: {REPO_ROOT}")
        st.text(f"layout: {DEFAULT_LAYOUT_ROOT}")
        st.text(f"runs: {DEFAULT_RUNS}")
        if cuda_available():
            st.success("CUDA available")
            default_device = "cuda"
        else:
            st.info("CUDA not available — using CPU")
            default_device = "cpu"
        st.markdown(
            """
**等价 CLI**
```text
python scripts/export_from_enpu_project.py -p song.enpu.json -o ../samples/layout/L00x
python scripts/train.py --config configs/mvp_l2_l3.yaml
python scripts/eval.py --ckpt runs/.../best.pt --data ../samples/layout
```
"""
        )

    tab_data, tab_train, tab_test, tab_hist = st.tabs(
        ["1. 数据集 / 导入", "2. 训练", "3. 测试", "4. 历史实验"]
    )

    # ---------- Dataset ----------
    with tab_data:
        st.subheader("从恩谱工程导入 Layout GT")
        c1, c2 = st.columns([3, 1])
        with c1:
            project_path = st.text_input(
                "工程文件路径 (.enpu.json)",
                placeholder=r"C:\Users\...\song.enpu.json",
                key="project_path",
            )
        with c2:
            sample_id = st.text_input("样本 ID（可选）", value="", key="sample_id")

        out_name = st.text_input(
            "输出目录名（在 samples/layout 下）",
            value="",
            placeholder="L003_my_song",
            key="out_name",
        )

        if st.button("导入 Layout", type="primary", key="btn_import"):
            if not project_path.strip():
                st.error("请填写工程路径")
            else:
                out_dir = None
                if out_name.strip():
                    out_dir = DEFAULT_LAYOUT_ROOT / out_name.strip()
                try:
                    with st.spinner("导出并校验…"):
                        result = import_enpu_project(
                            project_path.strip(),
                            out_dir=out_dir,
                            sample_id=sample_id.strip() or None,
                        )
                    st.session_state.import_messages.append(result)
                    if result["ok"]:
                        st.success(f"导入成功: {result['out_dir']}")
                    else:
                        st.warning(f"已写出但校验未通过: {result['out_dir']}")
                        st.json(result.get("info"))
                except Exception as e:
                    st.error(f"导入失败: {e}")

        st.divider()
        st.subheader("样本列表")
        if st.button("刷新列表", key="btn_refresh_samples"):
            st.rerun()

        samples = list_samples_info(st.session_state.layout_roots)
        if not samples:
            st.info("暂无 layout 样本。请导入工程，或确认 samples/layout 存在。")
        else:
            rows = []
            for s in samples:
                rows.append(
                    {
                        "id": s.sample_id,
                        "ok": "✅" if s.ok else "❌",
                        "systems": s.n_systems,
                        "splits": s.n_splits,
                        "measures": s.n_measures,
                        "size": f"{s.width}x{s.height}" if s.width else "",
                        "path": s.path,
                        "errors": "; ".join(s.errors[:2]) if s.errors else "",
                    }
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)

            # preview
            ok_samples = [s for s in samples if s.image_path]
            if ok_samples:
                pick = st.selectbox(
                    "预览样本",
                    options=ok_samples,
                    format_func=lambda s: s.sample_id,
                    key="preview_sample",
                )
                if pick and pick.image_path:
                    cols = st.columns([1, 1])
                    with cols[0]:
                        st.image(pick.image_path, caption=pick.sample_id, use_container_width=True)
                    with cols[1]:
                        st.json(pick.to_dict())

            # train/val multi-select
            st.markdown("**训练用样本根目录**（默认整个 `samples/layout`）")
            st.caption("当前 Framework 按目录加载；导入后的样本已在 samples/layout 下即可参与训练。")
            use_synth = st.checkbox("训练时附加合成样本", value=True, key="use_synth")

    # ---------- Train ----------
    with tab_train:
        st.subheader("一键训练")
        tc1, tc2, tc3, tc4 = st.columns(4)
        with tc1:
            tasks = st.multiselect(
                "任务",
                options=["l2", "l3"],
                default=["l2", "l3"],
                key="tasks",
            )
        with tc2:
            epochs = st.number_input("epochs", min_value=1, max_value=200, value=2, key="epochs")
        with tc3:
            batch_size = st.number_input("batch size", min_value=1, max_value=32, value=2, key="bs")
        with tc4:
            device = st.selectbox(
                "device",
                options=["cpu", "cuda"] if cuda_available() else ["cpu"],
                index=0 if default_device == "cpu" else 0,
                key="device",
            )

        with st.expander("高级"):
            lr = st.number_input("learning rate", value=1e-3, format="%.5f", key="lr")
            val_ratio = st.slider("val_ratio", 0.0, 0.5, 0.25, 0.05, key="val_ratio")
            synth_count = st.number_input(
                "synth_count",
                min_value=0,
                max_value=64,
                value=4 if st.session_state.get("use_synth", True) else 0,
                key="synth_count",
            )
            run_name = st.text_input(
                "实验名 / 输出目录名",
                value=f"ui_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                key="run_name",
            )
            skip_export = st.checkbox("跳过权重导出（更快）", value=False, key="skip_export")

        b1, b2, b3 = st.columns(3)
        with b1:
            start = st.button("开始训练", type="primary", key="btn_train")
        with b2:
            refresh = st.button("刷新进度", key="btn_poll")
        with b3:
            cancel = st.button("取消训练", key="btn_cancel")

        if start:
            if not tasks:
                st.error("请至少选择一个任务 (l2/l3)")
            else:
                spec = TrainJobSpec(
                    run_name=run_name.strip() or f"ui_{int(datetime.now().timestamp())}",
                    tasks=list(tasks),
                    epochs=int(epochs),
                    batch_size=int(batch_size),
                    lr=float(lr),
                    device=str(device),
                    data_roots=[str(DEFAULT_LAYOUT_ROOT)],
                    synth_count=int(synth_count),
                    val_ratio=float(val_ratio),
                    skip_export=bool(skip_export),
                )
                try:
                    job = start_train_job(spec)
                    st.session_state.active_run_dir = job["run_dir"]
                    st.success(f"已启动 PID={job['pid']} → {job['run_dir']}")
                except Exception as e:
                    st.error(f"启动失败: {e}")

        active = st.session_state.active_run_dir
        if active is None:
            # pick latest run with job
            runs = list_runs()
            for r in runs:
                if (Path(r["path"]) / "job.json").is_file():
                    active = r["path"]
                    break

        if cancel and active:
            res = cancel_train_job(active)
            if res.get("ok"):
                st.warning(f"已请求取消 PID={res.get('pid')}")
            else:
                st.error(res.get("error") or "取消失败")

        if active and (refresh or start or True):
            st.markdown(f"**当前 run:** `{active}`")
            status = poll_train_job(active)
            st.session_state.active_run_dir = active
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("状态", status.get("status", "?"))
                st.write(f"PID: {status.get('pid')}")
            with col_b:
                hist = status.get("history") or []
                if hist:
                    last = hist[-1]
                    st.metric("epoch", last.get("epoch"))
                    st.metric("train_loss", f"{last.get('train_loss', float('nan')):.4f}")
                    val = last.get("val") or {}
                    if val:
                        st.write(
                            f"val L2 IoU={val.get('l2_mean_iou')} · "
                            f"L3 x_err={val.get('l3_mean_abs_x_error')} · "
                            f"count_mae={val.get('l3_split_count_mae')}"
                        )

            if hist:
                chart = {
                    "train_loss": {
                        str(h.get("epoch")): h.get("train_loss")
                        for h in hist
                        if h.get("train_loss") is not None
                    }
                }
                val_loss = {
                    str(h.get("epoch")): (h.get("val") or {}).get("loss")
                    for h in hist
                    if (h.get("val") or {}).get("loss") is not None
                }
                if val_loss:
                    chart["val_loss"] = val_loss
                try:
                    st.line_chart(chart)
                except Exception:
                    st.json(hist)

            with st.expander("训练日志 (tail)", expanded=status.get("status") == "running"):
                st.code(status.get("log_tail") or "(empty)", language="text")

            if status.get("status") == "running":
                st.info("训练进行中 — 点击「刷新进度」更新。")
            elif status.get("status") == "failed":
                st.error("训练失败，请查看日志。")
            elif status.get("status") == "succeeded":
                st.success("训练完成。可到「测试」页评估。")
                ckpt = default_ckpt_for_run(active)
                if ckpt:
                    st.write(f"ckpt: `{ckpt}`")

    # ---------- Test ----------
    with tab_test:
        st.subheader("一键测试 / 评估")
        runs = list_runs()
        run_options = {r["name"]: r["path"] for r in runs if r.get("has_best") or r.get("has_last")}
        if not run_options:
            st.warning("还没有可用的 ckpt。请先训练。")
        else:
            run_pick = st.selectbox("实验", options=list(run_options.keys()), key="eval_run")
            run_dir = Path(run_options[run_pick])
            ckpt = default_ckpt_for_run(run_dir)
            st.write(f"ckpt: `{ckpt}`")
            data_root = st.text_input(
                "测试数据目录",
                value=str(DEFAULT_LAYOUT_ROOT),
                key="eval_data",
            )
            eval_device = st.selectbox(
                "eval device",
                options=["cpu", "cuda"] if cuda_available() else ["cpu"],
                key="eval_device",
            )
            if st.button("开始测试", type="primary", key="btn_eval"):
                if ckpt is None:
                    st.error("找不到 best.pt / last.pt")
                else:
                    try:
                        with st.spinner("eval 运行中…"):
                            res = run_eval(
                                ckpt,
                                data_root,
                                out_json=run_dir / "eval_ui.json",
                                device=eval_device,
                            )
                        st.session_state.last_eval = res
                        if res.get("ok"):
                            st.success("评估完成")
                        else:
                            st.error(res.get("error") or "评估失败")
                            st.code(res.get("stdout") or "")
                    except Exception as e:
                        st.error(f"评估异常: {e}")

            last = st.session_state.last_eval
            if last and last.get("metrics"):
                m = last["metrics"]
                st.subheader("指标")
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("L2 mean IoU", _fmt(m.get("l2_mean_iou")))
                mc2.metric("L3 mean |Δx|", _fmt(m.get("l3_mean_abs_x_error")))
                mc3.metric("L3 count MAE", _fmt(m.get("l3_split_count_mae")))
                mc4.metric("L3 count exact", _fmt(m.get("l3_split_count_exact")))
                st.json(m)
            elif (run_dir / "eval_ui.json").is_file():
                import json

                m = json.loads((run_dir / "eval_ui.json").read_text(encoding="utf-8"))
                st.subheader("上次评估 (eval_ui.json)")
                st.json(m)

    # ---------- History ----------
    with tab_hist:
        st.subheader("历史实验")
        runs = list_runs()
        if not runs:
            st.info("runs/ 下暂无实验")
        else:
            for r in runs:
                with st.expander(
                    f"{r['name']}  ·  {r.get('mtime', '')[:19]}  ·  "
                    f"{'best' if r.get('has_best') else '—'}  ·  "
                    f"loss={r.get('last_train_loss')}",
                    expanded=False,
                ):
                    st.write(r["path"])
                    if r.get("last_val"):
                        st.json(r["last_val"])
                    hist = load_history(r["path"])
                    if hist:
                        st.write(f"epochs recorded: {len(hist)}")
                    if st.button("设为当前 run", key=f"set_{r['name']}"):
                        st.session_state.active_run_dir = r["path"]
                        st.success(f"active → {r['path']}")


def _fmt(v) -> str:
    try:
        if v is None:
            return "—"
        x = float(v)
        if x != x:
            return "nan"
        return f"{x:.4f}"
    except Exception:
        return str(v)


if __name__ == "__main__":
    main()
