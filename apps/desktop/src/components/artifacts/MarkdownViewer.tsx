"use client";

import React, { useState, useEffect, useId } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { Check, Copy, Code2, AlertCircle } from "lucide-react";

export interface MarkdownViewerProps {
  content: string;
  className?: string;
}

interface MermaidDiagramProps {
  chart: string;
}

function MermaidDiagram({ chart }: MermaidDiagramProps) {
  const [svgHtml, setSvgHtml] = useState<string>("");
  const [hasError, setHasError] = useState(false);
  const randomId = useId().replace(/:/g, "");

  useEffect(() => {
    let isMounted = true;

    async function renderChart() {
      if (typeof window === "undefined") return;

      try {
        const mermaidModule = await import("mermaid");
        const mermaid = mermaidModule.default || mermaidModule;

        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "strict",
          suppressErrorRendering: true,
        });

        const elementId = `mermaid-graph-${randomId}`;
        const { svg } = await mermaid.render(elementId, chart);

        if (isMounted) {
          setSvgHtml(svg);
          setHasError(false);
        }
      } catch (err) {
        if (isMounted) {
          setHasError(true);
        }
      }
    }

    renderChart();

    return () => {
      isMounted = false;
    };
  }, [chart, randomId]);

  if (hasError) {
    return (
      <div className="mermaid-container my-4 p-3 bg-slate-900/90 border border-amber-600/40 rounded-lg">
        <div className="flex items-center gap-1.5 text-xs text-amber-400 font-mono mb-2">
          <AlertCircle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span>Không thể kết xuất biểu đồ Mermaid (cú pháp chưa chuẩn)</span>
        </div>
        <pre className="text-xs font-mono text-slate-300 overflow-x-auto bg-slate-950 p-2.5 rounded border border-slate-800">
          <code>{chart}</code>
        </pre>
      </div>
    );
  }

  if (svgHtml) {
    return (
      <div
        className="mermaid-container my-4 p-4 bg-slate-900/70 border border-slate-800 rounded-lg overflow-x-auto flex justify-center"
        dangerouslySetInnerHTML={{ __html: svgHtml }}
      />
    );
  }

  // Initial loading fallback
  return (
    <div className="mermaid-container my-4 p-4 bg-slate-900/50 border border-slate-800 rounded-lg">
      <pre className="text-xs font-mono text-slate-400 overflow-x-auto">
        <code>{chart}</code>
      </pre>
    </div>
  );
}

export function MarkdownViewer({ content, className = "" }: MarkdownViewerProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(content);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch (err) {
      console.error("Failed to copy markdown content:", err);
    }
  };

  return (
    <div
      className={`relative flex flex-col w-full bg-slate-950 border border-slate-800 rounded-xl overflow-hidden ${className}`}
      data-testid="markdown-viewer"
    >
      {/* Action Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-800 text-slate-200 text-xs">
        <div className="flex items-center gap-2">
          <Code2 className="w-4 h-4 text-sky-400" />
          <span className="font-medium text-slate-300">Tài liệu Markdown</span>
        </div>

        <button
          type="button"
          onClick={handleCopy}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors border ${
            copied
              ? "bg-emerald-950 text-emerald-300 border-emerald-700"
              : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
          }`}
          aria-label={copied ? "Đã sao chép" : "Sao chép"}
          title="Sao chép nội dung Markdown"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span>Đã sao chép</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5 text-slate-400" />
              <span>Sao chép</span>
            </>
          )}
        </button>
      </div>

      {/* Markdown Content Area */}
      <div className="p-4 sm:p-6 overflow-auto text-slate-200 text-sm leading-relaxed prose prose-invert max-w-none">
        <ReactMarkdown
          rehypePlugins={[rehypeSanitize]}
          components={{
            code({ className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || "");
              const language = match ? match[1] : "";
              const codeString = String(children).replace(/\n$/, "");

              if (language === "mermaid") {
                return <MermaidDiagram chart={codeString} />;
              }

              const isInline = !match && !String(children).includes("\n");
              if (isInline) {
                return (
                  <code
                    className="px-1.5 py-0.5 rounded bg-slate-800/80 text-sky-300 font-mono text-[13px] border border-slate-700/60"
                    {...props}
                  >
                    {children}
                  </code>
                );
              }

              return (
                <pre className="p-3 my-3 rounded-lg bg-slate-900 border border-slate-800 font-mono text-xs overflow-x-auto text-slate-200">
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              );
            },
            h1: ({ children }) => (
              <h1 className="text-xl font-bold text-white pb-2 mb-4 border-b border-slate-800">
                {children}
              </h1>
            ),
            h2: ({ children }) => (
              <h2 className="text-lg font-semibold text-white mt-5 mb-3">
                {children}
              </h2>
            ),
            h3: ({ children }) => (
              <h3 className="text-base font-semibold text-slate-100 mt-4 mb-2">
                {children}
              </h3>
            ),
            p: ({ children }) => <p className="mb-3 text-slate-300 leading-normal">{children}</p>,
            ul: ({ children }) => (
              <ul className="list-disc list-inside mb-3 space-y-1 text-slate-300 pl-2">
                {children}
              </ul>
            ),
            ol: ({ children }) => (
              <ol className="list-decimal list-inside mb-3 space-y-1 text-slate-300 pl-2">
                {children}
              </ol>
            ),
            table: ({ children }) => (
              <div className="my-4 overflow-x-auto">
                <table className="w-full border-collapse border border-slate-800 text-xs text-left">
                  {children}
                </table>
              </div>
            ),
            th: ({ children }) => (
              <th className="border border-slate-800 bg-slate-900 px-3 py-2 font-medium text-slate-300">
                {children}
              </th>
            ),
            td: ({ children }) => (
              <td className="border border-slate-800 px-3 py-2 text-slate-300">
                {children}
              </td>
            ),
            blockquote: ({ children }) => (
              <blockquote className="border-l-4 border-sky-500 bg-slate-900/40 pl-3 py-1 my-3 text-slate-400 italic">
                {children}
              </blockquote>
            ),
            a: ({ href, children }) => (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-400 hover:text-sky-300 underline underline-offset-2"
              >
                {children}
              </a>
            ),
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
