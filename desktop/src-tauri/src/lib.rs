//! EnPu desktop shell (Tauri 2) + local core sidecar lifecycle (issue #14).

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};

const CORE_HOST: &str = "127.0.0.1";
const CORE_PORT: u16 = 8765;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(45);

struct SidecarState {
    child: Mutex<Option<Child>>,
    /// True if this process spawned the sidecar (should kill on exit).
    owned: Mutex<bool>,
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

/// Locate bundled enpu-core next to the app executable or in resource dir.
fn find_sidecar_binary(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("enpu-core.exe"));
            candidates.push(dir.join("enpu-core"));
            // NSIS / some layouts place externalBin under resources
            candidates.push(dir.join("resources").join("enpu-core.exe"));
            candidates.push(dir.join("binaries").join("enpu-core.exe"));
        }
    }

    if let Ok(resource) = app.path().resource_dir() {
        candidates.push(resource.join("enpu-core.exe"));
        candidates.push(resource.join("enpu-core"));
        candidates.push(resource.join("binaries").join("enpu-core.exe"));
    }

    // Dev fallback: repo layout next to target/
    if let Ok(exe) = std::env::current_exe() {
        // .../src-tauri/target/debug/enpu-desktop.exe
        if let Some(src_tauri) = exe
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
        {
            candidates.push(src_tauri.join("binaries").join("enpu-core.exe"));
            // unsuffixed prepare copy helpers
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

fn spawn_sidecar(bin: &PathBuf) -> std::io::Result<Child> {
    let mut cmd = Command::new(bin);
    cmd.args([
        "--engine",
        "mock",
        "--host",
        CORE_HOST,
        "--port",
        &CORE_PORT.to_string(),
    ])
    .stdin(Stdio::null())
    .stdout(Stdio::null())
    .stderr(Stdio::null());

    // Hide console window on Windows (binary may still be console subsystem)
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    cmd.spawn()
}

fn stop_sidecar(state: &SidecarState) {
    let owned = *state.owned.lock().unwrap_or_else(|e| e.into_inner());
    if !owned {
        return;
    }
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn start_core_if_needed(app: &AppHandle, state: &SidecarState) {
    if port_open(CORE_HOST, CORE_PORT) {
        eprintln!(
            "[enpu] core already listening on {CORE_HOST}:{CORE_PORT}; skip sidecar spawn"
        );
        return;
    }

    let Some(bin) = find_sidecar_binary(app) else {
        eprintln!(
            "[enpu] sidecar binary not found; start core manually (scripts/start.ps1 or enpu-core.exe)"
        );
        return;
    };

    eprintln!("[enpu] starting sidecar: {}", bin.display());
    match spawn_sidecar(&bin) {
        Ok(child) => {
            *state.child.lock().unwrap() = Some(child);
            *state.owned.lock().unwrap() = true;
            if wait_for_port(CORE_HOST, CORE_PORT, HEALTH_TIMEOUT) {
                eprintln!("[enpu] core ready on http://{CORE_HOST}:{CORE_PORT}");
            } else {
                eprintln!(
                    "[enpu] core did not become ready within {}s",
                    HEALTH_TIMEOUT.as_secs()
                );
            }
        }
        Err(err) => {
            eprintln!("[enpu] failed to spawn sidecar: {err}");
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(SidecarState {
            child: Mutex::new(None),
            owned: Mutex::new(false),
        })
        .invoke_handler(tauri::generate_handler![greet, core_status])
        .setup(|app| {
            let handle = app.handle().clone();
            let state = app.state::<SidecarState>();
            start_core_if_needed(&handle, &state);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building EnPu")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                let state = app_handle.state::<SidecarState>();
                stop_sidecar(&state);
            }
        });
}
