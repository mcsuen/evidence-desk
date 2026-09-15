import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import Markdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { PdfPage } from "./PdfPage";

type Entry = { citation: any; source: any };
type Scope = {
  prefix: string;
  entries: Map<string, Entry>;
  open: (anchor: string, origin?: HTMLElement) => void;
};
const EvidenceContext = createContext<Scope | null>(null);
export function citationAnchor(citation: any) {
  let value = 2166136261;
  for (const byte of new TextEncoder().encode(
    citation.source_id + ":" + citation.block_id,
  ))
    value = Math.imul(value ^ byte, 16777619) >>> 0;
  return (
    "evidence-" +
    value
      .toString(16)
      .padStart(8, "0")
      .split("")
      .map((c) => String.fromCharCode(97 + parseInt(c, 16)))
      .join("")
  );
}
export function headingId(text: string) {
  return (
    "section-" +
    text
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-|-$/g, "")
  );
}
export function EvidenceScope({
  children,
  revision,
  restore = false,
}: {
  children: ReactNode;
  revision?: any;
  restore?: boolean;
}) {
  const prefix = useId(),
    entries = useRef(new Map<string, Entry>()),
    origin = useRef<HTMLElement | undefined>(undefined),
    panel = useRef<HTMLElement>(null);
  const [active, setActive] = useState(""),
    [width, setWidth] = useState(480),
    [missing, setMissing] = useState(false);
  function close() {
    setActive("");
    setMissing(false);
    origin.current?.focus({ preventScroll: true });
    if (restore) {
      const url = new URL(location.href);
      url.searchParams.delete("citation");
      history.replaceState(history.state, "", url);
    }
  }
  function open(anchor: string, element?: HTMLElement) {
    origin.current = element;
    setActive(anchor);
    setMissing(!entries.current.has(anchor));
    if (restore) {
      const url = new URL(location.href);
      url.searchParams.set("citation", anchor);
      history.replaceState(history.state, "", url);
    }
  }
  useEffect(() => {
    if (restore) {
      const anchor = new URLSearchParams(location.search).get("citation");
      if (anchor) {
        setActive(anchor);
        setMissing(!entries.current.has(anchor));
      }
    }
  }, [restore]);
  useEffect(() => {
    if (active) panel.current?.focus({ preventScroll: true });
  }, [active]);
  const entry = entries.current.get(active),
    block = entry?.source?.blocks?.find(
      (b: any) => b.id === entry.citation.block_id,
    );
  const assertions = (revision?.numeric_assertions || []).filter((a: any) => {
    const rendered = String(revision?.[a.field || "content"] || "");
    const nextLink = rendered.slice(a.end || 0).match(/^\]\(#(evidence-[a-p]+)\)/);
    return !nextLink || nextLink[1] === active;
  });
  const blocks = entry?.source?.blocks || [];
  const blockIndex = blocks.findIndex((b: any) => b.id === entry?.citation.block_id);
  const contextText = blocks.slice(Math.max(0, blockIndex - 1), blockIndex + 2).map((b: any) => b.text).join("\n\n");
  return (
    <EvidenceContext.Provider
      value={{ prefix, entries: entries.current, open }}
    >
      {children}
      {active && (
        <aside
          className="w-proof-panel"
          ref={panel}
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-label="原文与数值依据"
          style={{ width }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
            if (e.key === "Tab") {
              const items = panel.current?.querySelectorAll<HTMLElement>(
                'button,a,input,select,[tabindex="0"]',
              );
              if (items?.length) {
                const first = items[0],
                  last = items[items.length - 1];
                if (
                  e.shiftKey &&
                  (document.activeElement === first ||
                    document.activeElement === panel.current)
                ) {
                  e.preventDefault();
                  last.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first.focus();
                }
              }
            }
          }}
        >
          <header>
            <div>
              <small>原始资料 → 知识依据</small>
              <h2>查证这一处引用</h2>
            </div>
            <button onClick={close} aria-label="关闭依据，返回阅读">
              ×
            </button>
          </header>
          <label className="w-proof-width">
            面板宽度
            <input
              aria-label="依据面板宽度"
              type="range"
              min="360"
              max="800"
              value={width}
              onChange={(e) => setWidth(Number(e.target.value))}
            />
          </label>
          {missing || !entry ? (
            <p role="alert">此版本缺少可定位的依据，请报告问题。</p>
          ) : (
            <>
              <h3>{entry.source?.title || entry.citation.source_id}</h3>
              <p className="d-muted">
                {entry.source?.provider} ·{" "}
                {entry.source?.subject_company || entry.source?.company} ·{" "}
                {entry.source?.available_at?.slice(0, 10)}
              </p>
              <blockquote>{entry.citation.quote}</blockquote>
              {block && (
                <details open>
                  <summary>
                    原文上下文{block.page ? " · 第 " + block.page + " 页" : ""}
                  </summary>
                  <pre className="w-proof-context">{contextText}</pre>
                </details>
              )}
              {block?.page &&
                entry.source?.media_type === "application/pdf" && (
                  <details>
                    <summary>查看 PDF 页面定位</summary>
                    <PdfPage
                      sourceId={entry.citation.source_id}
                      page={block.page}
                      bbox={block.bbox || null}
                      url={
                        "/api/desk/wiki/sources/" +
                        encodeURIComponent(entry.citation.source_id) +
                        "/file"
                      }
                    />
                  </details>
                )}
              <a
                target="_blank"
                rel="noreferrer"
                href={
                  "/api/desk/wiki/sources/" +
                  encodeURIComponent(entry.citation.source_id) +
                  "/file" +
                  (block?.page ? "#page=" + block.page : "")
                }
              >
                打开保存的原件 ↗
              </a>
              {entry.source?.url?.startsWith("https://") && (
                <p>
                  <a href={entry.source.url} target="_blank" rel="noreferrer">
                    原始出处 ↗
                  </a>
                </p>
              )}
              {assertions.length > 0 && (
                <details>
                  <summary>本页数值、口径与计算</summary>
                  {assertions.map((a: any, i: number) => (
                    <div className="w-proof-number" key={i}>
                      <b>{a.name || "确定性计算"}</b>
                      <p>
                        {a.period} · {a.unit} · {a.basis}
                      </p>
                      <code>{a.expression || String(a.value)}</code>
                      {a.periods && (
                        <p>
                          {Object.entries(a.periods)
                            .map(([k, v]) => k + ": " + v)
                            .join(" / ")}
                        </p>
                      )}
                    </div>
                  ))}
                </details>
              )}
              {revision && (
                <p className="d-muted">
                  引用页面 v{revision.version} · 发布于{" "}
                  {revision.published_at?.slice(0, 16)}
                  <br />
                  所用规范 v{revision.policy?.version || "—"}
                </p>
              )}
              <button onClick={close}>返回原阅读位置</button>
            </>
          )}
        </aside>
      )}
    </EvidenceContext.Provider>
  );
}
function EvidenceLink({
  href,
  children,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const scope = useContext(EvidenceContext),
    [missing, setMissing] = useState(false);
  const anchor = href?.startsWith("#evidence-") ? href.slice(1) : null;
  if (!anchor)
    return (
      <a {...props} href={href}>
        {children}
      </a>
    );
  return (
    <>
      <a
        {...props}
        href={href}
        data-evidence-link
        onClick={(event) => {
          event.preventDefault();
          if (scope) {
            scope.open(anchor, event.currentTarget);
          } else setMissing(true);
        }}
      >
        {children}
      </a>
      {missing && <span role="status">缺少引用上下文</span>}
    </>
  );
}
function childrenText(node: ReactNode): string {
  return typeof node === "string" || typeof node === "number"
    ? String(node)
    : Array.isArray(node)
      ? node.map(childrenText).join("")
      : node && typeof node === "object" && "props" in node
        ? childrenText((node.props as any).children)
        : "";
}
const components = {
  a: ({
    node: _node,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & { node?: unknown }) => (
    <EvidenceLink {...props} />
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 id={headingId(childrenText(children))}>{children}</h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 id={headingId(childrenText(children))}>{children}</h3>
  ),
};
export function Prose({ text }: { text: string }) {
  return (
    <div className="w-prose">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={components}
        urlTransform={(url) => {
          if (url.startsWith("wiki:")) {
            const [identity, version] = url.slice(5).split("@v");
            return (
              "/wiki?tab=page&page=" +
              encodeURIComponent(identity) +
              (version ? "&version=" + encodeURIComponent(version) : "")
            );
          }
          return defaultUrlTransform(url);
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
function EvidenceItem({ citation, source }: { citation: any; source: any }) {
  const scope = useContext(EvidenceContext),
    anchor = citationAnchor(citation);
  useEffect(() => {
    scope?.entries.set(anchor, { citation, source });
    return () => {
      scope?.entries.delete(anchor);
    };
  }, [scope?.entries, anchor, citation, source]);
  return (
    <details
      id={(scope?.prefix || "") + "-" + anchor}
      data-citation={anchor}
      tabIndex={-1}
    >
      <summary
        onClick={(e) => {
          if (scope) {
            e.preventDefault();
            scope.open(anchor, e.currentTarget);
          }
        }}
      >
        {source?.title || citation.source_id} · {citation.block_id} ↗
      </summary>
      <blockquote>{citation.quote}</blockquote>
    </details>
  );
}
export function Evidence({
  citations,
  sources,
}: {
  citations: any[];
  sources: any[];
}) {
  const groups = new Map<string, any>();
  for (const citation of citations) {
    const anchor = citationAnchor(citation),
      prior = groups.get(anchor);
    groups.set(
      anchor,
      prior
        ? {
            ...prior,
            quote: prior.quote.includes(citation.quote)
              ? prior.quote
              : prior.quote + "\n\n" + citation.quote,
          }
        : citation,
    );
  }
  return (
    <section className="w-evidence">
      <h3>原始依据</h3>
      {[...groups].map(([anchor, citation]) => (
        <EvidenceItem
          key={anchor}
          citation={citation}
          source={sources.find((s) => s.id === citation.source_id)}
        />
      ))}
    </section>
  );
}
