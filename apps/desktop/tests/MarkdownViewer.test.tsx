import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { MarkdownViewer } from "@/components/artifacts/MarkdownViewer";

describe("MarkdownViewer Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders sanitized markdown and blocks malicious XSS scripts", () => {
    const maliciousMarkdown = `
# Báo cáo chiến lược

Đây là nội dung an toàn.

<script>alert("XSS Attack!");</script>
<img src="x" onerror="alert('XSS Image')" />
<a href="javascript:alert('XSS Link')">Click here</a>
`;

    const { container } = render(<MarkdownViewer content={maliciousMarkdown} />);

    expect(screen.getByText("Báo cáo chiến lược")).toBeInTheDocument();
    expect(screen.getByText("Đây là nội dung an toàn.")).toBeInTheDocument();

    // Verify <script> tag is NOT in the rendered DOM
    expect(container.querySelector("script")).toBeNull();

    // Verify onerror attribute is sanitized
    const img = container.querySelector("img");
    if (img) {
      expect(img.getAttribute("onerror")).toBeNull();
    }

    // Verify javascript: link is sanitized
    const link = container.querySelector("a");
    if (link) {
      expect(link.getAttribute("href")).not.toContain("javascript:");
    }
  });

  it("copies markdown content to clipboard with feedback message", async () => {
    const textContent = "# Kịch bản bán hàng\n\nNội dung kịch bản chuẩn...";
    
    // Mock navigator.clipboard
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<MarkdownViewer content={textContent} />);

    const copyBtn = screen.getByRole("button", { name: /sao chép|copy/i });
    expect(copyBtn).toBeInTheDocument();

    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith(textContent);

    await waitFor(() => {
      expect(screen.getByText(/đã sao chép/i)).toBeInTheDocument();
    });
  });

  it("handles mermaid fenced code blocks gracefully without crashing", () => {
    const markdownWithMermaid = `
# Kiến trúc phễu

\`\`\`mermaid
flowchart LR
    A[Lead] --> B[Khách hàng]
\`\`\`
`;

    const { container } = render(<MarkdownViewer content={markdownWithMermaid} />);
    expect(screen.getByText("Kiến trúc phễu")).toBeInTheDocument();
    // Mermaid container or fallback block exists
    expect(container.querySelector(".mermaid-container, pre, code")).not.toBeNull();
  });
});
