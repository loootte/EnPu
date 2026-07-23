//! EnPu desktop shell (Tauri 2) + local core sidecar lifecycle (issue #14).
//!
//! - Starts bundled `enpu-core` (or paddle venv launcher when available)
//! - On window close: asks whether to stop the recognition core
//! - Kills process tree on Windows so PyInstaller onefile children die too

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

const CORE_HOST: &str = "127.0.0.1";
const CORE_PORT: u16 = 8765;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(45);

struct SidecarState {
    child: Mutex<Option<Child>>,
    /// True if this process spawned the sidecar (eligible to stop on exit).
    owned: Mutex<bool>,
    /// Child process id (for taskkill /T tree kill on Windows).
    child_pid: Mutex<Option<u32>>,
}

#[tauri::command]
fn greet(name: &str) -> String {
    format!("你好，{}！EnPu 桌面壳（Tauri）已就绪。", name)
}

/// Report whether the local core port answers (sidecar or external).
#[tauri::command]
fn core_status() -> serde_json::Value {
    let up = port_open(CORE_HOST, CORE_PORT);
    serde_json::json!({
        "host": CORE_HOST,
        "port": CORE_PORT,
        "online": up,
        "url": format!("http://{}:{}", CORE_HOST, CORE_PORT),
    })
}

fn port_open(host: &str, port: u16) -> bool {
    TcpStream::connect_timeout(
        &format!("{host}:{port}").parse().unwrap_or_else(|_| {
            std::net::SocketAddr::from(([127, 0, 0, 1], port))
        }),
        Duration::from_millis(400),
    )
    .is_ok()
}

fn wait_for_port(host: &str, port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if port_open(host, port) {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

/// Prefer paddle venv launcher if install-paddle-ocr.ps1 completed; else mock sidecar.
fn find_core_launch(app: &AppHandle) -> Option<(PathBuf, Vec<String>, String)> {
    // 1) User-local paddle venv after post-install script
    if let Some(local) = paddle_launcher_path() {
        if local.is_file() {
            eprintln!("[enpu] using paddle launcher: {}", local.display());
            return Some((
                local,
                vec![],
                "paddleocr".to_string(),
            ));
        }
    }

    // 2) Bundled enpu-core.exe (mock by default)
    let bin = find_sidecar_binary(app)?;
    eprintln!("[enpu] using bundled sidecar: {}", bin.display());
    Some((
        bin,
        vec![
            "--engine".into(),
            "mock".into(),
            "--host".into(),
            CORE_HOST.into(),
            "--port".into(),
            CORE_PORT.to_string(),
        ],
        "mock".into(),
    ))
}

fn paddle_launcher_path() -> Option<PathBuf> {
    // %LOCALAPPDATA%\EnPu\start-enpu-core-paddle.cmd
    let base = std::env::var_os("LOCALAPPDATA")?;
    let p = PathBuf::from(base)
        .join("EnPu")
        .join("start-enpu-core-paddle.cmd");
    Some(p)
}

/// Locate bundled enpu-core next to the app executable or in resource dir.
fn find_sidecar_binary(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("enpu-core.exe"));
            candidates.push(dir.join("enpu-core"));
            candidates.push(dir.join("resources").join("enpu-core.exe"));
            candidates.push(dir.join("binaries").join("enpu-core.exe"));
        }
    }

    if let Ok(resource) = app.path().resource_dir() {
        candidates.push(resource.join("enpu-core.exe"));
        candidates.push(resource.join("enpu-core"));
        candidates.push(resource.join("binaries").join("enpu-core.exe"));
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(src_tauri) = exe
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
        {
            candidates.push(src_tauri.join("binaries").join("enpu-core.exe"));
            if let Ok(rd) = std::fs::read_dir(src_tauri.join("binaries")) {
                for e in rd.flatten() {
                    let n = e.file_name().to_string_lossy().to_string();
                    if n.starts_with("enpu-core") && (n.ends_with(".exe") || !n.contains('.')) {
                        candidates.push(e.path());
                    }
                }
            }
        }
    }

    candidates.into_iter().find(|p| p.is_file())
}

fn spawn_core(bin: &PathBuf, args: &[String]) -> std::io::Result<Child> {
    let mut cmd = Command::new(bin);
    cmd.args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        // CREATE_NEW_PROCESS_GROUP helps taskkill /T find the tree
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
        cmd.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
    }

    // cmd scripts need to run via cmd.exe /C
    if bin
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.eq_ignore_ascii_case("cmd") || e.eq_ignore_ascii_case("bat"))
        .unwrap_or(false)
    {
        let mut c = Command::new("cmd.exe");
        let mut full = vec!["/C".to_string(), bin.to_string_lossy().to_string()];
        full.extend(args.iter().cloned());
        c.args(&full)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
            c.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
        }
        return c.spawn();
    }

    cmd.spawn()
}

/// Kill process tree (Windows: taskkill /T). Needed for PyInstaller onefile.
fn kill_process_tree(pid: u32) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status();
    }
}

fn kill_enpu_core_by_name() {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = Command::new("taskkill")
            .args(["/IM", "enpu-core.exe", "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

fn stop_sidecar(state: &SidecarState, force_by_name: bool) {
    let owned = *state.owned.lock().unwrap_or_else(|e| e.into_inner());
    if !owned && !force_by_name {
        return;
    }

    if let Ok(mut pid_g) = state.child_pid.lock() {
        if let Some(pid) = pid_g.take() {
            eprintln!("[enpu] stopping core process tree pid={pid}");
            kill_process_tree(pid);
        }
    }

    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    if force_by_name || owned {
        // Fallback: PyInstaller may leave a detached worker named enpu-core.exe
        kill_enpu_core_by_name();
    }

    if let Ok(mut o) = state.owned.lock() {
        *o = false;
    }

    // Wait until port is free (best-effort)
    for _ in 0..20 {
        if !port_open(CORE_HOST, CORE_PORT) {
            break;
        }
        thread::sleep(Duration::from_millis(100));
    }
}

fn clear_owned(state: &SidecarState) {
    // Detach: keep child running, forget handle so Drop doesn't kill it
    if let Ok(mut guard) = state.child.lock() {
        if let Some(child) = guard.take() {
            // leak intentionally — process keeps running
            std::mem::forget(child);
        }
    }
    if let Ok(mut pid_g) = state.child_pid.lock() {
        *pid_g = None;
    }
    if let Ok(mut o) = state.owned.lock() {
        *o = false;
    }
    eprintln!("[enpu] leaving core running on {CORE_HOST}:{CORE_PORT}");
}

fn start_core_if_needed(app: &AppHandle, state: &SidecarState) {
    if port_open(CORE_HOST, CORE_PORT) {
        eprintln!(
            "[enpu] core already listening on {CORE_HOST}:{CORE_PORT}; skip spawn"
        );
        // Do not mark owned — we did not start it
        return;
    }

    let Some((bin, args, mode)) = find_core_launch(app) else {
        eprintln!(
            "[enpu] no core binary/launcher found; start manually or reinstall"
        );
        return;
    };

    eprintln!("[enpu] starting core ({mode}): {}", bin.display());
    match spawn_core(&bin, &args) {
        Ok(child) => {
            let pid = child.id();
            *state.child_pid.lock().unwrap() = Some(pid);
            *state.child.lock().unwrap() = Some(child);
            *state.owned.lock().unwrap() = true;
            if wait_for_port(CORE_HOST, CORE_PORT, HEALTH_TIMEOUT) {
                eprintln!("[enpu] core ready on http://{CORE_HOST}:{CORE_PORT} ({mode})");
            } else {
                eprintln!(
                    "[enpu] core did not become ready within {}s",
                    HEALTH_TIMEOUT.as_secs()
                );
            }
        }
        Err(err) => {
            eprintln!("[enpu] failed to spawn core: {err}");
        }
    }
}

/// Windows MessageBox Yes/No. Returns true if user chose Yes.
#[cfg(windows)]
fn ask_yes_no(title: &str, text: &str) -> bool {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        MessageBoxW, IDYES, MB_ICONQUESTION, MB_YESNO,
    };

    fn wide(s: &str) -> Vec<u16> {
        std::ffi::OsStr::new(s)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }

    let t = wide(title);
    let b = wide(text);
    let r = unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            b.as_ptr(),
            t.as_ptr(),
            MB_YESNO | MB_ICONQUESTION,
        )
    };
    r == IDYES as i32
}

#[cfg(not(windows))]
fn ask_yes_no(_title: &str, _text: &str) -> bool {
    // Non-Windows: default to stopping the core we own
    true
}

fn on_close_requested(app: &AppHandle, state: &SidecarState) {
    let owned = *state.owned.lock().unwrap_or_else(|e| e.into_inner());
    let up = port_open(CORE_HOST, CORE_PORT);

    if !up {
        return;
    }

    // Always ask if core is up (owned by us or left from previous session on same machine)
    let msg = if owned {
        "是否同时关闭本地识别核心 enpu-core？\n\n\
         · 是：停止识别服务（端口 8765）\n\
         · 否：保留 core 在后台运行，下次启动可复用"
    } else {
        "检测到本机识别核心仍在运行（http://127.0.0.1:8765）。\n\n\
         是否关闭它？\n\
         · 是：结束 enpu-core\n\
         · 否：保留后台运行"
    };

    if ask_yes_no("EnPu · 关闭识别核心？", msg) {
        stop_sidecar(state, true);
    } else if owned {
        clear_owned(state);
    }

    // Ensure app exits after dialog (CloseRequested already prevented default)
    app.exit(0);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(SidecarState {
            child: Mutex::new(None),
            owned: Mutex::new(false),
            child_pid: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![greet, core_status])
        .setup(|app| {
            let handle = app.handle().clone();
            let state = app.state::<SidecarState>();
            start_core_if_needed(&handle, &state);

            // Intercept window close → ask about enpu-core
            let h2 = handle.clone();
            if let Some(win) = app.get_webview_window("main") {
                win.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let st = h2.state::<SidecarState>();
                        on_close_requested(&h2, &st);
                    }
                });
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building EnPu")
        .run(|app_handle, event| {
            // Fallback if closed without CloseRequested (e.g. app.exit)
            if let RunEvent::Exit = event {
                let state = app_handle.state::<SidecarState>();
                let owned = *state.owned.lock().unwrap_or_else(|e| e.into_inner());
                // Only auto-kill if still owned and user didn't already choose "leave running"
                if owned {
                    // Safety net without dialog (already exiting)
                    stop_sidecar(&state, true);
                }
            }
        });
}
