import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiClient } from "@/lib/apiClient";

const mockInvoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

describe("ApiClient & Tauri Sidecar Connection Integration", () => {
  const originalWindow = global.window;

  beforeEach(() => {
    vi.clearAllMocks();
    mockInvoke.mockReset();
    delete (global as any).window.__TAURI_INTERNALS__;
    delete (global as any).window.__TAURI__;
    delete (global as any).window.__LOCAL_AUTH_TOKEN__;
  });

  afterEach(() => {
    global.window = originalWindow;
  });

  it("initializes with default loopback port and dev token in web browser environment", () => {
    const client = new ApiClient();
    expect(client.getBaseUrl()).toBe("http://127.0.0.1:8765");
  });

  it("respects explicit baseUrl and token overrides without being clobbered", async () => {
    mockInvoke.mockResolvedValue({ port: 44444, token: "tauri-token" });
    (global as any).window.__TAURI_INTERNALS__ = {};

    const client = new ApiClient({
      baseUrl: "http://127.0.0.1:9999",
      token: "explicit-token-12345",
    });

    expect(client.getBaseUrl()).toBe("http://127.0.0.1:9999");
    expect(client.getToken()).toBe("explicit-token-12345");

    await client.syncTauriBackendConnection();
    expect(client.getBaseUrl()).toBe("http://127.0.0.1:9999");
    expect(client.getToken()).toBe("explicit-token-12345");
  });

  it("dynamically queries Tauri get_backend_connection when running inside Tauri webview", async () => {
    const expectedPort = 56789;
    const expectedToken = "a".repeat(64);

    mockInvoke.mockImplementation((cmd: string) => {
      if (cmd === "get_backend_connection") {
        return Promise.resolve({
          port: expectedPort,
          token: expectedToken,
        });
      }
      return Promise.reject(new Error(`Unknown command ${cmd}`));
    });

    (global as any).window.__TAURI_INTERNALS__ = {};

    const client = new ApiClient();
    await client.syncTauriBackendConnection();

    expect(mockInvoke).toHaveBeenCalledWith("get_backend_connection");
    expect(client.getBaseUrl()).toBe(`http://127.0.0.1:${expectedPort}`);
    expect(client.getToken()).toBe(expectedToken);
    expect((global as any).window.__LOCAL_AUTH_TOKEN__).toBe(expectedToken);
  });

  it("falls back gracefully to static defaults when Tauri invoke rejects", async () => {
    mockInvoke.mockRejectedValue(new Error("IPC connection closed"));
    (global as any).window.__TAURI_INTERNALS__ = {};

    const client = new ApiClient();
    await expect(client.syncTauriBackendConnection()).resolves.not.toThrow();

    expect(client.getBaseUrl()).toBe("http://127.0.0.1:8765");
  });
});
