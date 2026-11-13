// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use std::process::{Child, Command};
use std::sync::Mutex;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use tauri::Manager;

#[derive(Clone, Serialize, Deserialize, Debug, PartialEq, Eq)]
pub struct BackendConnectionInfo {
    pub port: u16,
    pub token: String,
}

pub struct AppState {
    pub connection: BackendConnectionInfo,
    pub sidecar_child: Mutex<Option<Child>>,
}

/// Generates a cryptographically secure 64-character hexadecimal session token.
pub fn generate_session_token() -> String {
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

/// Binds to 127.0.0.1:0 to obtain a free ephemeral loopback port, then releases the socket.
pub fn pick_free_loopback_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0")
        .expect("failed to bind to loopback port");
    let port = listener.local_addr()
        .expect("failed to get local address")
        .port();
    drop(listener);
    port
}

/// Tauri command invoked by the webview frontend to obtain dynamic sidecar port and session token.
#[tauri::command]
pub fn get_backend_connection(state: tauri::State<AppState>) -> BackendConnectionInfo {
    state.connection.clone()
}

/// Spawns the backend sidecar executable if available on disk.
fn spawn_sidecar(port: u16, token: &str) -> Option<Child> {
    let binary_name = if cfg!(windows) {
        "backend-sidecar.exe"
    } else {
        "backend-sidecar"
    };

    let mut candidate_paths = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidate_paths.push(parent.join(binary_name));
            candidate_paths.push(parent.join("binaries").join(binary_name));
        }
    }
    candidate_paths.push(std::path::PathBuf::from(format!("binaries/{}", binary_name)));
    candidate_paths.push(std::path::PathBuf::from(binary_name));

    for path in &candidate_paths {
        if path.exists() {
            let child = Command::new(path)
                .arg("--port")
                .arg(port.to_string())
                .arg("--token")
                .arg(token)
                .spawn();
            if let Ok(c) = child {
                eprintln!("[Sidecar] Spawned sidecar binary {:?} on port {}", path, port);
                return Some(c);
            }
        }
    }

    eprintln!("[Sidecar] No local sidecar binary found; continuing in external daemon mode.");
    None
}

fn main() {
    let token = generate_session_token();
    let port = pick_free_loopback_port();
    let child = spawn_sidecar(port, &token);

    let app_state = AppState {
        connection: BackendConnectionInfo {
            port,
            token,
        },
        sidecar_child: Mutex::new(child),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![get_backend_connection])
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                let state = app_handle.state::<AppState>();
                if let Ok(mut lock) = state.sidecar_child.lock() {
                    if let Some(mut child) = lock.take() {
                        eprintln!("[Sidecar] Gracefully terminating backend sidecar process...");
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generates_non_empty_local_auth_token_and_binds_loopback_port() {
        let token = generate_session_token();
        assert_eq!(token.len(), 64);
        let port = pick_free_loopback_port();
        assert!(port > 1024);
    }
}
