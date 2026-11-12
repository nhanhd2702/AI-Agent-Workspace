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

  it("triggers onOpenExternal or onExternalOpen callback when provided", () => {
    const onOpenExternal = vi.fn();

    render(
      <HtmlSandboxViewer
        html="<h1>Open in Browser</h1>"
        title="browser.html"
        onOpenExternal={onOpenExternal}
      />
    );

    const openBtn = screen.getByRole("button", { name: /mở bằng trình duyệt|mở ngoài/i });
    fireEvent.click(openBtn);

    expect(onOpenExternal).toHaveBeenCalledTimes(1);
  });

  it("safely falls back to file download with URL.revokeObjectURL instead of opening unsandboxed blob tab", () => {
    const originalCreateObjectURL = window.URL.createObjectURL;
    const originalRevokeObjectURL = window.URL.revokeObjectURL;
    const originalOpen = window.open;

    const createObjectURLMock = vi.fn().mockReturnValue("blob:mock-safe-url");
    const revokeObjectURLMock = vi.fn();
    const windowOpenMock = vi.fn();

    window.URL.createObjectURL = createObjectURLMock;
    window.URL.revokeObjectURL = revokeObjectURLMock;
    window.open = windowOpenMock;

    // Spy on anchor click
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    vi.useFakeTimers();

    render(
      <HtmlSandboxViewer
        html="<h1>Safe Download</h1>"
        title="dashboard.html"
      />
    );

    const openBtn = screen.getByRole("button", { name: /mở bằng trình duyệt|mở ngoài/i });
    fireEvent.click(openBtn);

    // CRITICAL SECURITY ASSERTION: Must NOT call window.open(blobUrl) to prevent same-origin XSS escape
    expect(windowOpenMock).not.toHaveBeenCalled();

    // Must create download anchor with safe filename and trigger click
    expect(createObjectURLMock).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);

    // Must revoke object URL to prevent memory leaks
    vi.advanceTimersByTime(1100);
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:mock-safe-url");

    vi.useRealTimers();
    window.URL.createObjectURL = originalCreateObjectURL;
    window.URL.revokeObjectURL = originalRevokeObjectURL;
    window.open = originalOpen;
    clickSpy.mockRestore();
  });
});
