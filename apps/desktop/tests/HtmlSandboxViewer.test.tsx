import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { HtmlSandboxViewer } from "@/components/artifacts/HtmlSandboxViewer";

describe("HtmlSandboxViewer Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // Brief specific test
  it("renders iframe with allow-scripts without allow-same-origin and toggles mobile viewport", () => {
    render(<HtmlSandboxViewer html="<h1>Demo</h1>" title="index.html" />);
    const iframe = screen.getByTitle("index.html");
    const sandboxAttr = iframe.getAttribute("sandbox") || "";
    expect(sandboxAttr).toBe("allow-scripts allow-forms");
    expect(sandboxAttr).not.toContain("allow-same-origin");

    // Toggle viewport
    const mobileBtn = screen.getByRole("button", { name: /mobile|390px/i });
    const desktopBtn = screen.getByRole("button", { name: /desktop|100%/i });

    // Initial is desktop (100% width container)
    const container = iframe.closest("[data-testid='sandbox-viewport-container']");
    expect(container).toHaveClass("w-full");

    // Click mobile
    fireEvent.click(mobileBtn);
    expect(container).toHaveClass("max-w-[390px]");

    // Click desktop
    fireEvent.click(desktopBtn);
    expect(container).not.toHaveClass("max-w-[390px]");
  });

  it("renders warnings banner when warnings prop is provided", () => {
    const warnings = [
      "Đã chặn external script: cdn.tailwindcss.com",
      "Đã chặn external stylesheet: evil.com/a.css",
    ];
    render(
      <HtmlSandboxViewer
        html="<h1>Offline</h1>"
        title="preview.html"
        warnings={warnings}
      />
    );

    expect(screen.getByText(/2 cảnh báo/i)).toBeInTheDocument();
    expect(screen.getByText(/cdn.tailwindcss.com/)).toBeInTheDocument();
    expect(screen.getByText(/evil.com\/a.css/)).toBeInTheDocument();
  });

  it("triggers external browser open on button click", () => {
    const onExternalOpen = vi.fn();
    // Mock URL.createObjectURL and window.open
    const originalCreateObjectURL = window.URL.createObjectURL;
    const originalOpen = window.open;
    window.URL.createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    window.open = vi.fn();

    render(
      <HtmlSandboxViewer
        html="<h1>Open in Browser</h1>"
        title="browser.html"
        onExternalOpen={onExternalOpen}
      />
    );

    const openBtn = screen.getByRole("button", { name: /mở bằng trình duyệt|mở ngoài/i });
    fireEvent.click(openBtn);

    expect(onExternalOpen).toHaveBeenCalledTimes(1);

    window.URL.createObjectURL = originalCreateObjectURL;
    window.open = originalOpen;
  });
});
