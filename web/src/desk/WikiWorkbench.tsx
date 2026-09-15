import { useEffect, useRef, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, operation, state } from "./api";
import { EvidenceScope, Evidence, Prose, headingId } from "./WikiEvidence";
import {
  CaptureForm,
  DraftEditor,
  fromRevision,
  newDraft,
  History,
  ReportForm,
  Issue,
  InspectionFeedback,
  ReviewContent,
  Status,
} from "./WikiEditors";
import "./wiki-workbench.css";

const types: Record<string, string> = {
  company: "公司概览",
  topic: "研究专题",
  concept: "概念与方法",
  analysis: "综合分析",
  source: "来源解读",
};
const stages: Record<string, string> = {
  queued: "等待执行",
  wiki_planning: "制定资料需求",
  wiki_discovering: "正在寻找资料",
  wiki_discovered: "已找到候选资料",
  wiki_acquiring: "获取与处理原件",
  wiki_checking: "检查质量与覆盖",
  wiki_compiling: "整理知识页面",
  wiki_review_ready: "准备审核包",
  wiki_check_finished: "检查结束",
  finished: "执行结束",
};
const execution: Record<string, string> = {
  queued: "等待执行",
  running: "进行中",
  partial: "检查不完整",
  completed: "搜集整理完成",
  failed: "执行失败",
  cancelled: "已取消",
};
const publication: Record<string, string> = {
  not_published: "尚未发布",
  waiting_review: "等待人工采纳",
  published: "正式版本已更新",
  rejected: "已驳回",
};
const sourceTypes: Record<string, string> = {
  official: "官方披露",
  regulatory: "监管资料",
  industry: "行业资料",
  media: "媒体报道",
  manual: "手动收录",
  claude: "Claude 会话",
  codex: "Codex 会话",
  slack: "Slack 材料",
  research: "研究产物",
};
const ref = (r: any) => ({ id: r.id, version: r.version });
const acquisitionErrors: Record<string, string> = {
  connection_failed: "连接失败", tls_error: "加密连接失败", host_deferred: "本站暂缓，继续处理其他来源",
  configuration_required: "需要配置联系信息", access_denied: "访问被拒绝", rate_limited: "站点限流，稍后再查",
  body_unavailable: "正文未取得", parse_failed: "正文未取得", invalid_content: "原件格式异常",
  period_conflict: "原文期间与候选不一致", title_conflict: "替代原件标题不一致", budget_exhausted: "本次获取预算已用尽",
  identity_conflict: "替代原件主体未确认",
};
function AcquisitionResult({ material: m }: { material: any }) {
  const label = m.acquisition_result === "alternative_acquired" ? "已通过替代入口取得" :
    acquisitionErrors[m.error_type] || ({ acquired: "已取得", revised: "发现修订", unchanged: "原件未变化",
      failed: "获取失败", downloaded: "原件已保存，等待解析", provided: "复用已有原件" } as Record<string, string>)[m.status] || m.status;
  return <>
    <span>{label}</span>
    {m.error_type === "configuration_required" && <p>填写 SEC 应用名称与真实联系邮箱。<a href="/settings">前往本机设置</a></p>}
    {m.alternative_of && <p><a href={m.alternative_of} target="_blank" rel="noreferrer">查看原入口 ↗</a></p>}
    {(m.receipts?.length > 0 || m.error) && <details><summary>获取记录</summary>
      {m.error && <p>{m.error}</p>}
      {m.receipts?.map((r: any, i: number) => <p key={i}>
        尝试 {i + 1} · {r.status ? "HTTP " + r.status : "尚未取得响应"}
        {r.elapsed_seconds != null && " · " + r.elapsed_seconds + " 秒"}
        {r.error_type && " · " + (acquisitionErrors[r.error_type] || "获取失败")}
        {r.bytes > 0 && " · " + r.bytes.toLocaleString() + " 字节"}
        {r.retry_after && " · 站点建议稍后重试"}
      </p>)}
    </details>}
  </>;
}
type Nav = (patch: Record<string, string | null>) => void;

export default function WikiWorkbench({
  company: parentCompany,
  notify,
}: {
  company: string;
  notify: (s: string) => void;
}) {
  const [params, setParams] = useSearchParams(),
    client = useQueryClient(),
    lastCompany = useRef(parentCompany);
  const company = params.get("company") || parentCompany,
    tab =
      params.get("tab") === "wiki"
        ? "home"
        : params.get("tab") || (params.get("page") ? "page" : "home"),
    pageId = params.get("page") || "",
    asOf = params.get("as_of") || "",
    jobId = params.get("job") || "",
    proposalId = params.get("proposal") || "";
  const [drawer, setDrawer] = useState(false),
    [draft, setDraft] = useState<any>(null),
    [search, setSearch] = useState(""),
    [searchResults, setSearchResults] = useState<any>(null);
  const modalElement = useRef<HTMLElement>(null);
  const [modal, setModal] = useState(""),
    [busy, setBusy] = useState(false);
  function nav(patch: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    next.set("company", company);
    next.delete("citation");
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next);
    setDrawer(false);
  }
  useEffect(() => {
    if (lastCompany.current !== parentCompany) {
      lastCompany.current = parentCompany;
      setParams({ company: parentCompany });
      setSearchResults(null);
    }
  }, [parentCompany, setParams]);
  const time = asOf ? "&as_of=" + encodeURIComponent(asOf) : "";
  const { data, error } = useQuery({
    queryKey: ["wiki-workspace", company, asOf],
    queryFn: () => api("/wiki/workspace?company=" + company + time),
    refetchInterval: asOf ? false : 5000,
  });
  const { data: reviewData } = useQuery({
    queryKey: ["wiki", company],
    queryFn: () => api("/wiki?company=" + company),
    enabled: ["review", "edit", "issues", "raw"].includes(tab) && !asOf,
    refetchInterval: tab === "review" ? 5000 : false,
  });
  const { data: page } = useQuery({
    queryKey: [
      "wiki-page",
      pageId,
      params.get("version"),
      asOf,
      data?.sequence,
    ],
    queryFn: () =>
      api(
        "/wiki/page?id=" +
          encodeURIComponent(pageId) +
          (params.get("version") ? "&version=" + params.get("version") : "") +
          time,
      ),
    enabled: !!pageId && ["page", "report"].includes(tab),
  });
  const readingKey = [company, tab, pageId, params.get("version"), asOf].join(":");
  const readingReady = !!data && (tab !== "page" || !!page);
  useEffect(() => {
    if (!readingReady || !["page", "home"].includes(tab)) return;
    const key = "pitr-wiki-reading:" + readingKey;
    let restored = false;
    const frame = requestAnimationFrame(() => {
      try { window.scrollTo(0, Number(sessionStorage.getItem(key) || 0)); } catch { /* Storage can be disabled. */ }
      restored = true;
    });
    const remember = () => { if (restored) try { sessionStorage.setItem(key, String(window.scrollY)); } catch { /* Reading remains available. */ } };
    window.addEventListener("scroll", remember, { passive: true });
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", remember); };
  }, [readingKey, readingReady, tab]);
  useEffect(() => {
    if (!modal) return;
    const origin = document.activeElement as HTMLElement;
    modalElement.current?.querySelector<HTMLElement>("input, textarea, button")?.focus();
    return () => { if (origin?.isConnected) origin.focus({ preventScroll: true }); };
  }, [modal]);
  async function run(fn: () => Promise<any>, message?: string) {
    try {
      const result = await fn();
      await Promise.all([
        client.invalidateQueries({ queryKey: ["wiki-workspace"] }),
        client.invalidateQueries({ queryKey: ["wiki"] }),
        client.invalidateQueries({ queryKey: ["wiki-job"] }),
        client.invalidateQueries({ queryKey: ["wiki-proposal"] }),
        client.invalidateQueries({ queryKey: ["home"] }),
      ]);
      if (message) notify(message);
      return result;
    } catch (e) {
      notify(String(e));
      return null;
    }
  }
  const pages = data?.pages || [],
    pending = data?.proposals.filter((p: any) => p.status === "pending") || [];
  function openPage(p: any) {
    nav({
      tab: "page",
      page: p.id,
      version: String(p.version),
      source: null,
      job: null,
    });
  }
  async function edit(revision?: any, issue?: any) {
    const policy = await api("/wiki/policy");
    setDraft({
      operation_id: operation(),
      company,
      policy: ref(policy),
      changes: [
        revision
          ? {
              ...fromRevision(revision),
              ...(issue
                ? {
                    corrects: issue.target,
                    change_type: "correction",
                    reason: issue.description,
                  }
                : {}),
            }
          : newDraft(company),
      ],
      inputs: revision ? [ref(revision)] : [],
      reason: issue?.description || "",
      origin: "human",
      issue_ids: issue ? [issue.id] : [],
    });
    nav({ tab: "edit" });
  }
  if (error) return <p role="alert">公司 Wiki 载入失败：{String(error)}</p>;
  if (!data) return <p className="d-empty">正在打开公司研究…</p>;
  return (
    <section className="ww-root">
      <header className="ww-topline">
        <button
          className="ww-menu"
          aria-label="展开三层目录"
          aria-expanded={drawer}
          onClick={() => setDrawer(!drawer)}
        >
          ☰ 目录
        </button>
        <div>
          <span className="ww-kicker">持续研究 / {company}</span>
          <h1>公司研究 Wiki</h1>
        </div>
        <div className="ww-actions">
          <button onClick={() => setModal("build")} disabled={!!asOf}>
            构建公司 Wiki
          </button>
          <button onClick={() => setModal("update")} disabled={!!asOf}>
            更新 Wiki
          </button>
          <button
            className="primary"
            onClick={() => nav({ tab: "query", job: null })}
          >
            提问
          </button>
          <button onClick={() => setModal("schedule")} disabled={!!asOf}>
            更新设置
          </button>
        </div>
      </header>
      <div className="ww-layout">
        <nav
          className={"ww-navigation " + (drawer ? "open" : "")}
          aria-label="资料、知识与规范"
        >
          <button
            className="ww-company"
            onClick={() => nav({ tab: "home", page: null, job: null })}
          >
            <strong>{company}</strong>
            <span>接着上次的研究</span>
          </button>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const r = await run(() =>
                api(
                  "/wiki/search?company=" +
                    company +
                    "&q=" +
                    encodeURIComponent(search) +
                    time,
                ),
              );
              if (r) {
                setSearchResults(r);
                nav({ tab: "search" });
              }
            }}
          >
            <input
              aria-label="搜索 Wiki"
              placeholder="搜索知识与问题"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button aria-label="执行 Wiki 搜索">⌕</button>
          </form>
          <section>
            <h2>
              <span>01</span> 原始资料
            </h2>
            <button
              className={tab === "raw" ? "active" : ""}
              onClick={() => nav({ tab: "raw", page: null })}
            >
              资料清单 <small>{data.sources.length}</small>
            </button>
            <p>
              官方披露 · 行业与媒体
              <br />
              附件 · 会话与研究线索
            </p>
          </section>
          <section>
            <h2>
              <span>02</span> 知识 Wiki
            </h2>
            <button
              className={tab === "home" ? "active" : ""}
              onClick={() => nav({ tab: "home", page: null })}
            >
              公司概览
            </button>
            {Object.entries(types)
              .filter(([k]) => k !== "company")
              .map(([kind, label]) => (
                <details key={kind} open={["topic", "concept"].includes(kind)}>
                  <summary>
                    {label}{" "}
                    <small>
                      {pages.filter((p: any) => p.page_type === kind).length}
                    </small>
                  </summary>
                  {pages
                    .filter((p: any) => p.page_type === kind)
                    .map((p: any) => (
                      <button
                        className={
                          pageId === p.id && tab === "page" ? "active" : ""
                        }
                        key={p.id}
                        onClick={() => openPage(p)}
                      >
                        {p.title}
                      </button>
                    ))}
                </details>
              ))}
            <button onClick={() => nav({ tab: "index" })}>
              全部目录 · index.md
            </button>
            <button onClick={() => nav({ tab: "log" })}>
              更新记录 · log.md
            </button>
          </section>
          <section>
            <h2>
              <span>03</span> 维护规范
            </h2>
            <button
              className={tab === "policy" ? "active" : ""}
              onClick={() => nav({ tab: "policy", page: null, policy_version: null })}
            >
              研究与维护约定 <small>v{data.policy?.version || "—"}</small>
            </button>
            <p>
              来源策略 · 证据要求
              <br />
              建库 · 更新 · 问答 · 纠错
            </p>
          </section>
          <div className="ww-nav-work">
            <button
              className={tab === "review" ? "active" : ""}
              onClick={() => nav({ tab: "review", page: null })}
            >
              变更审核 <b>{pending.length || ""}</b>
            </button>
            <button onClick={() => nav({ tab: "query" })}>问答与沉淀</button>
            <button onClick={() => nav({ tab: "jobs" })}>建库与更新任务</button>
            <button onClick={() => nav({ tab: "issues" })}>问题与巡检</button>
          </div>
          <label className="ww-asof">
            研究时点
            <input
              aria-label="Wiki 研究时点"
              type="datetime-local"
              value={
                asOf
                  ? new Date(
                      new Date(asOf).getTime() -
                        new Date(asOf).getTimezoneOffset() * 60000,
                    )
                      .toISOString()
                      .slice(0, 16)
                  : ""
              }
              onChange={(e) =>
                nav({
                  as_of: e.target.value
                    ? new Date(e.target.value).toISOString()
                    : null,
                  version: null,
                })
              }
            />
          </label>
          {asOf && (
            <button onClick={() => nav({ as_of: null })}>回到当前研究</button>
          )}
        </nav>
        <div className="ww-content">
          {asOf && (
            <p className="ww-time-note">
              时点阅读：{new Date(asOf).toLocaleString()}
              。只呈现当时已发布的认识、资料和状态。
            </p>
          )}
          {asOf && (["jobs", "review", "edit", "report", "issues"].includes(tab) || jobId) ? (
            <p className="d-empty">历史模式只开放当时的资料、页面、规范和更新记录。返回当前研究后处理任务与审核。</p>
          ) : jobId ? (
            <JobDetail id={jobId} run={run} nav={nav} />
          ) : (
            <>
              {tab === "home" && (
                <CompanyHome
                  data={data}
                  openPage={openPage}
                  nav={nav}
                  build={() => setModal("build")}
                />
              )}
              {tab === "page" && page && (
                <Reader
                  key={page.revision.ref}
                  data={{ ...page, linkedTitles: pages }}
                  asOf={asOf}
                  nav={nav}
                  openPage={openPage}
                  edit={() => edit(page.revision)}
                />
              )}
              {tab === "report" && page && (
                <ReportForm
                  page={page.revision}
                  run={run}
                  done={() => nav({ tab: "issues" })}
                />
              )}
              {tab === "raw" && (
                <Sources
                  data={data}
                  nav={nav}
                  time={time}
                  run={run}
                  selected={params.get("source") || ""}
                  openPage={openPage}
                />
              )}
              {tab === "policy" && (
                <Policy
                  metadata={params.get("policy_version") ? { ...data.policy, version: Number(params.get("policy_version")) } : data.policy}
                  asOf={asOf}
                  edit={edit}
                  jobs={data.jobs}
                />
              )}
              {(tab === "index" || tab === "search") && (
                <section className="ww-directory">
                  <h2>{tab === "search" ? "搜索结果" : "全部目录"}</h2>
                  {searchResults?.warnings?.map((w: string) => (
                    <p className="d-warning" key={w}>
                      {w}
                    </p>
                  ))}
                  {(tab === "search" ? searchResults?.items || [] : pages).map(
                    (p: any) => (
                      <button key={p.id} onClick={() => openPage(p)}>
                        <small>{types[p.page_type] || "知识"}</small>
                        <h3>{p.title}</h3>
                        <p>{p.summary || "打开阅读全文与依据"}</p>
                        <Status value={p.availability} />
                      </button>
                    ),
                  )}
                  <button disabled={!!asOf} onClick={() => edit()}>
                    新建知识页
                  </button>
                </section>
              )}
              {tab === "log" && <UpdateLog company={company} time={time} />}
              {tab === "jobs" && <JobList company={company} nav={nav} />}
              {tab === "review" && (
                <ReviewList
                  data={data}
                  reviewData={reviewData}
                  id={proposalId}
                  nav={nav}
                  run={run}
                  edit={(p: any) => {
                    setDraft({
                      ...p.request,
                      operation_id: operation(),
                      replaces: p.id,
                    });
                    nav({ tab: "edit" });
                  }}
                />
              )}
              {tab === "edit" && draft && reviewData && (
                <DraftEditor
                  draft={draft}
                  setDraft={setDraft}
                  sources={reviewData.sources}
                  revisions={reviewData.revisions}
                  onCancel={() => nav({ tab: "home" })}
                  onSave={() =>
                    run(async () => {
                      const p = await api("/wiki/proposals", {
                        ...draft,
                        operation_id: operation(),
                      });
                      nav({ tab: "review", proposal: p.id });
                      setDraft(null);
                      return p;
                    }, "完整变更已校验，等待审核")
                  }
                />
              )}
              {tab === "issues" && (
                <Maintenance
                  data={reviewData || data}
                  company={company}
                  run={run}
                  correct={async (i: any) => {
                    const p = await api(
                      "/wiki/page?id=" + encodeURIComponent(i.target.id),
                    );
                    edit(p.revision, i);
                  }}
                />
              )}
              {tab === "query" && (
                <Ask
                  company={company}
                  context={pages.find((p: any) => p.id === pageId)}
                  asOf={asOf}
                  run={run}
                  nav={nav}
                  update={() => setModal("update")}
                />
              )}
            </>
          )}
        </div>
      </div>
      {modal && (
        <div
          className="ww-modal-backdrop"
          onClick={() => !busy && setModal("")}
        >
          <section
            className="ww-modal"
            ref={modalElement}
            onKeyDown={(e) => {
              if (e.key === "Escape" && !busy) { e.preventDefault(); setModal(""); }
              if (e.key === "Tab") {
                const elements = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary')).filter(x => x.getClientRects().length);
                const first = elements[0], last = elements[elements.length - 1];
                if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
                else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
              }
            }}
            role="dialog"
            aria-modal="true"
            aria-label={modal === "schedule" ? "更新设置" : "Wiki 任务"}
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <h2>
                {modal === "build"
                  ? "构建公司 Wiki"
                  : modal === "update"
                    ? "主动更新 Wiki"
                    : "更新设置"}
              </h2>
              <button
                aria-label="关闭任务设置"
                disabled={busy}
                onClick={() => setModal("")}
              >
                ×
              </button>
            </header>
            {modal === "schedule" ? (
              <Schedule
                company={company}
                current={data.schedule}
                run={run}
                done={() => setModal("")}
              />
            ) : (
              <JobForm
                company={company}
                intent={modal}
                run={run}
                busy={busy}
                setBusy={setBusy}
                done={(j: any) => {
                  setModal("");
                  nav({ job: j.id, tab: "jobs" });
                }}
              />
            )}
          </section>
        </div>
      )}
    </section>
  );
}

function CompanyHome({
  data,
  openPage,
  nav,
  build,
}: {
  data: any;
  openPage: any;
  nav: Nav;
  build: any;
}) {
  const companyPage = data.pages.find(
      (p: any) => p.page_type === "company" && p.availability === "available",
    ),
    topics = data.pages.filter((p: any) => p.page_type === "topic"),
    pending = data.proposals.filter((p: any) => p.status === "pending"),
    issues = data.issues.filter((i: any) => i.state === "open");
  const { data: overview, error: overviewError } = useQuery({
    queryKey: [
      "wiki-home-page",
      companyPage?.id,
      companyPage?.version,
      data.as_of,
    ],
    queryFn: () =>
      api(
        "/wiki/page?id=" +
          encodeURIComponent(companyPage.id) +
          "&version=" +
          companyPage.version +
          (data.as_of ? "&as_of=" + encodeURIComponent(data.as_of) : ""),
      ),
    enabled: !!companyPage,
  });
  return (
    <div className="ww-home">
      <div className="ww-home-title">
        <span className="ww-kicker">公司概览</span>
        <h2>
          {data.companies.find((c: any) => c.company === data.company)?.name ||
            data.company}
        </h2>
        <p>当前认识、判断变化，以及值得继续追问的问题。</p>
      </div>
      <div className="ww-home-columns">
        <section className="ww-current">
          <div className="ww-section-head">
            <h3>当前认识</h3>
            {companyPage && (
              <button onClick={() => openPage(companyPage)}>
                完整公司页 →
              </button>
            )}
          </div>
          {overview ? (
            <EvidenceScope revision={overview.revision}>
              <Prose text={overview.revision.content} />
              <Evidence
                citations={overview.revision.citations}
                sources={overview.sources}
              />
            </EvidenceScope>
          ) : companyPage ? (
            <p className="d-muted">{overviewError ? "公司页载入失败，请刷新重试：" + String(overviewError) : "正在载入已采纳的公司认识…"}</p>
          ) : (
            <div className="ww-unwritten">
              <h3>这里还没有已采纳的公司认识</h3>
              <p>
                已有资料和草稿可以继续整理；正式判断会在你审核后出现在这里。
              </p>
              {pending.length ? (
                <button
                  className="primary"
                  onClick={() =>
                    nav({ tab: "review", proposal: pending[0].id })
                  }
                >
                  阅读已有草稿 · {pending.length} 批
                </button>
              ) : (
                <button className="primary" onClick={build}>
                  开始构建公司 Wiki
                </button>
              )}
            </div>
          )}
        </section>
        <aside className="ww-continuity">
          <section>
            <h3>继续研究</h3>
            {topics.length ? (
              topics.map((p: any) => (
                <button
                  className="ww-topic"
                  key={p.id}
                  onClick={() => openPage(p)}
                >
                  <b>{p.title}</b>
                  <p>{p.summary || "打开已有认识、证据与竞争性解释"}</p>
                  <small>
                    v{p.version} · {p.published_at?.slice(0, 10)}
                  </small>
                </button>
              ))
            ) : (
              <p>专题草稿采纳后，会在这里保留研究进度。</p>
            )}
          </section>
          <section>
            <h3>最近变化</h3>
            {pending.slice(0, 3).map((p: any) => (
              <button
                className="ww-topic"
                key={p.id}
                onClick={() => nav({ tab: "review", proposal: p.id })}
              >
                <b>待采纳 · {p.reason}</b>
                <p>{p.pages.slice(0, 3).join("、")}</p>
              </button>
            ))}
            {data.pages
              .filter((p: any) => p.page_type !== "source")
              .sort((a: any, b: any) =>
                b.published_at.localeCompare(a.published_at),
              )
              .slice(0, 3)
              .map((p: any) => (
                <button
                  className="ww-topic"
                  key={p.id}
                  onClick={() => openPage(p)}
                >
                  <small>{p.published_at.slice(0, 10)}</small>
                  <b>{p.title}</b>
                  <p>{p.reason}</p>
                </button>
              ))}
          </section>
          <section>
            <h3>未解决的问题</h3>
            {issues.length ? (
              issues.slice(0, 6).map((i: any) => (
                <button
                  key={i.id}
                  className="ww-topic"
                  onClick={() => nav({ tab: "issues" })}
                >
                  {i.description}
                </button>
              ))
            ) : (
              <p>尚无已登记疑点。资料覆盖和研究缺口请查看最近任务。</p>
            )}
            <button onClick={() => nav({ tab: "jobs" })}>查看资料覆盖 →</button>
          </section>
        </aside>
      </div>
    </div>
  );
}

function Reader({
  data,
  asOf,
  nav,
  openPage,
  edit,
}: {
  data: any;
  asOf: string;
  nav: Nav;
  openPage: any;
  edit: any;
}) {
  const r = data.revision,
    toc = [...r.content.matchAll(/^#{2,3}\s+(.+)$/gm)].map((m) => m[1]),
    [compare, setCompare] = useState(false),
    [other, setOther] = useState("");
  const { data: prior } = useQuery({
    queryKey: ["wiki-compare", r.id, other, asOf],
    queryFn: () =>
      api(
        "/wiki/page?id=" +
          encodeURIComponent(r.id) +
          "&version=" +
          other +
          (asOf ? "&as_of=" + encodeURIComponent(asOf) : ""),
      ),
    enabled: compare && !!other,
  });
  return (
    <EvidenceScope revision={r} restore>
      <div className="ww-reader-layout">
        <article className="ww-document">
          <div className="ww-breadcrumb">
            <button onClick={() => nav({ tab: "home", page: null })}>
              {r.company}
            </button>
            <span>
              {" "}
              / {types[r.page_type] || "知识"} / v{r.version}
            </span>
          </div>
          <div className="w-page-meta">
            <Status value={r.availability} />
            <span>发布于 {r.published_at.slice(0, 16).replace("T", " ")}</span>
            <span>规范 v{r.policy?.version || "—"}</span>
          </div>
          <h2>{r.title}</h2>
          {r.business_period && (
            <p className="ww-period">覆盖期间：{r.business_period}</p>
          )}
          {r.availability !== "available" && (
            <p className="d-warning">
              此版本
              {r.availability === "needs_review"
                ? "需要复核"
                : r.availability === "disputed"
                  ? "存在争议"
                  : "当前不可用于有效引用"}
              。请结合问题记录判断适用范围。
            </p>
          )}
          <div className={compare ? "ww-compare" : ""}>
            <div>
              <Prose text={r.content} />
            </div>
            {compare && (
              <section>
                <label>
                  比较历史版本
                  <select
                    value={other}
                    onChange={(e) => setOther(e.target.value)}
                  >
                    <option value="">选择版本</option>
                    {data.versions
                      .filter((p: any) => p.version !== r.version)
                      .map((p: any) => (
                        <option key={p.version} value={p.version}>
                          v{p.version} · {p.published_at.slice(0, 10)}
                        </option>
                      ))}
                  </select>
                </label>
                {prior && (
                  <EvidenceScope revision={prior.revision}>
                    <Prose text={prior.revision.content} />
                    <Evidence
                      citations={prior.revision.citations}
                      sources={prior.sources}
                    />
                  </EvidenceScope>
                )}
              </section>
            )}
          </div>
          {r.scope && (
            <section>
              <h3>适用范围</h3>
              <p>{r.scope}</p>
            </section>
          )}
          {r.nature === "method" &&
            ["applicability", "formula", "failure_cases", "example"].map(
              (f, i) => (
                <section key={f}>
                  <h3>{["适用条件", "公式", "失败情形", "案例"][i]}</h3>
                  <Prose text={r[f] || ""} />
                </section>
              ),
            )}
          <Evidence citations={r.citations} sources={data.sources} />
          <section className="ww-connections">
            <h3>接续研究与引用关系</h3>
            {r.relations?.map((rel: any) => (
              <button
                key={rel.target.id + rel.relation}
                onClick={() => openPage(rel.target)}
              >
                {data.linkedTitles?.find((p: any) => p.id === rel.target.id && p.version === rel.target.version)?.title || "关联知识"} · v{rel.target.version} ·{" "}
                {rel.relation === "related" ? "相关阅读" : "依据关系"}
              </button>
            ))}
            {data.backlinks.map((p: any) => (
              <button key={p.id + p.relation} onClick={() => openPage(p)}>
                ← {p.title} 引用了此版本
              </button>
            ))}
            {data.uses.map((u: any) => (
              <p key={u.id}>研究使用：{u.title || u.id}</p>
            ))}
            <Link
              to={
                "/research?company=" +
                r.company +
                "&question=" +
                encodeURIComponent(r.title) +
                "&wiki_ref=" +
                encodeURIComponent(r.ref)
              }
            >
              带着此问题与版本继续研究 →
            </Link>
          </section>
          <div className="w-page-actions">
            <button disabled={!!asOf} onClick={edit}>
              修订此页
            </button>
            <button disabled={!!asOf} onClick={() => nav({ tab: "report" })}>
              报告问题
            </button>
            <button onClick={() => nav({ tab: "query" })}>围绕此页提问</button>
            <button onClick={() => setCompare(!compare)}>
              {compare ? "结束比较" : "比较跨期认识"}
            </button>
          </div>
          <History objectId={r.id} asOf={asOf} sources={data.sources} />
        </article>
        <aside className="ww-toc">
          <h3>本页内容</h3>
          {toc.map((text, i) => (
            <a key={i} href={"#" + headingId(text)}>
              {text.replace(/[*_]/g, "")}
            </a>
          ))}
          <div>
            <h3>所用维护规范</h3>
            <button onClick={() => nav({ tab: "policy", policy_version: String(data.policy?.version || "") })}>
              {data.policy?.title || "历史规范未记录"}
              {data.policy ? " · v" + data.policy.version : ""}
            </button>
            <p>
              {data.sources.length} 份原始依据
              <br />
              {data.backlinks.length} 处反向引用
            </p>
          </div>
        </aside>
      </div>
    </EvidenceScope>
  );
}

function Sources({
  data,
  selected,
  nav,
  time,
  run,
  openPage,
}: {
  data: any;
  selected: string;
  nav: Nav;
  time: string;
  run: any;
  openPage: any;
}) {
  const [sourceFilter, setSourceFilter] = useState("all");
  const { data: source } = useQuery({
    queryKey: ["wiki-source", selected, time],
    queryFn: () =>
      api(
        "/wiki/sources/" +
          encodeURIComponent(selected) +
          (time ? "?" + time.slice(1) : ""),
      ),
    enabled: !!selected,
  });
  return (
    <section>
      <div className="ww-section-head">
        <div>
          <span className="ww-kicker">原始资料层</span>
          <h2>资料与研究线索</h2>
        </div>
        <select
          aria-label="资料类别"
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
        >
          <option value="all">全部来源</option>
          {Object.entries(sourceTypes).map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </div>
      {!time && (
        <details className="ww-capture-toggle">
          <summary>手动收录材料 / 连接会话 hook</summary>
          <CaptureForm company={data.company} run={run} />
        </details>
      )}
      <div className="ww-sources-list">
        {data.sources
          .filter(
            (s: any) => sourceFilter === "all" || s.provider === sourceFilter,
          )
          .map((s: any) => (
            <button
              key={s.id}
              className={s.id === selected ? "active" : ""}
              onClick={() => nav({ tab: "raw", source: s.id })}
            >
              <span>{sourceTypes[s.provider] || s.provider}</span>
              <div>
                <b>{s.title}</b>
                <small>
                  {s.subject_company || data.company} ·{" "}
                  {s.available_at?.slice(0, 10)} · {s.contributes_to.length}{" "}
                  个关联页面
                </small>
              </div>
              <span>
                {s.state === "available"
                  ? "已保存"
                  : s.state === "superseded"
                    ? "已有修订"
                    : "已撤回"}
              </span>
            </button>
          ))}
      </div>
      {source && (
        <article className="ww-source-reading">
          <h2>{source.title}</h2>
          <p>
            {sourceTypes[source.provider]} · 主体{" "}
            {source.subject_company || source.company} · 收集于{" "}
            {source.observed_at}
          </p>
          <a
            href={"/api/desk/wiki/sources/" + source.id + "/file"}
            target="_blank"
            rel="noreferrer"
          >
            打开保存的原件 ↗
          </a>
          {(source.retrieved_url || source.original_url) && <details>
            <summary>获取地址与原始发布关系</summary>
            <p><a href={source.retrieved_url || source.url} target="_blank" rel="noreferrer">实际取得的公开版本 ↗</a></p>
            {source.original_url && <p><a href={source.original_url} target="_blank" rel="noreferrer">登记的原始出处 ↗</a></p>}
            <p>{({ publisher_version: "同一发布方的公开版本", linked_original: "正文链接到原始发布", declared: "转载关系待核实，不作为新增独立证据", original: "原始发布入口" } as Record<string, string>)[source.origin_relation] || "来源关系保留在获取记录中"}</p>
          </details>}
          <section className="ww-contribution">
            <h3>这份资料贡献了什么</h3>
            {source.contributes_to.length ? (
              source.contributes_to.map((p: any) => (
                <button key={p.id} onClick={() => openPage(p)}>
                  {types[p.page_type] || "知识"} → {p.title}
                </button>
              ))
            ) : (
              <p>
                尚无已采纳的来源解读或知识页面，可在任务与审核中查看整理进度。
              </p>
            )}
          </section>
          {source.issues?.map((i: string) => (
            <p className="d-warning" key={i}>
              {i}
            </p>
          ))}
          <div className="ww-raw-blocks">
            {source.blocks.map((b: any) => (
              <section id={b.id} key={b.id}>
                <small>
                  {b.page ? "第 " + b.page + " 页 · " : ""}
                  {b.id}
                </small>
                <pre>{b.text}</pre>
              </section>
            ))}
          </div>
        </article>
      )}
    </section>
  );
}

function Policy({
  metadata,
  asOf,
  edit,
  jobs,
}: {
  metadata: any;
  asOf: string;
  edit: any;
  jobs: any[];
}) {
  const { data } = useQuery({
    queryKey: ["wiki-policy-page", metadata?.version, asOf],
    queryFn: () =>
      api(
        "/wiki/page?id=" +
          encodeURIComponent(metadata.id) +
          "&version=" +
          metadata.version +
          (asOf ? "&as_of=" + encodeURIComponent(asOf) : ""),
      ),
    enabled: !!metadata,
  });
  if (!metadata) return <p>此时点尚无已保存的维护规范。</p>;
  return (
    <article className="ww-document">
      <span className="ww-kicker">维护规范层 · v{metadata.version}</span>
      <h2>公司研究的工作约定</h2>
      <p>
        资料收集、知识整理与问答共用本规范。规范调整通过审核形成新版本，并触发相关认识复核。
      </p>
      {data && <Prose text={data.revision.content} />}
      <div className="ww-policy-flows">
        <h3>三个任务如何使用规范</h3>
        <p>
          <b>建库</b> · 官方、行业与媒体 → 保存原件 → 转换与检查 → 跨页提案 →
          人工采纳。
        </p>
        <p>
          <b>更新</b> · 检查新增和来源修订 → 对照已有认识 → 记录冲突与缺口 →
          审核发布。
        </p>
        <p>
          <b>问答</b> · 阅读 Wiki → 核对证据与时点 → 记录实际使用版本 →
          新分析回到已有专题。
        </p>
      </div>
      <button disabled={!!asOf || !data} onClick={() => edit(data.revision)}>
        提议调整规范
      </button>
      <h3>规范关联的任务</h3>
      {jobs.filter((j) => j.policy?.version === metadata.version).slice(0, 5).map((j) => (
        <p key={j.id}>
          {j.created_at.slice(0, 16)} · {execution[j.execution_status]}
        </p>
      ))}
      <History objectId={metadata.id} asOf={asOf} />
    </article>
  );
}

function JobForm({
  company,
  intent,
  run,
  busy,
  setBusy,
  done,
}: {
  company: string;
  intent: string;
  run: any;
  busy: boolean;
  setBusy: any;
  done: any;
}) {
  const [target, setTarget] = useState(company),
    [focus, setFocus] = useState(
      intent === "build"
        ? "业务模式、利润率、现金转化、竞争与风险"
        : "检查新披露、来源修订与已有认识的变化",
    ),
    [seeds, setSeeds] = useState(""),
    [register, setRegister] = useState(false),
    [name, setName] = useState(""),
    [domains, setDomains] = useState("");
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          if (register) {
            const r = await run(() =>
              api("/wiki/companies", {
                operation_id: operation(),
                company: target.toUpperCase(),
                name,
                official_domains: domains.split(/[，,\s]+/).filter(Boolean),
                aliases: [],
                catalog_urls: [],
              }),
            );
            if (!r) return;
          }
          const j = await run(() =>
            api("/wiki/jobs", {
              operation_id: operation(),
              company: target.toUpperCase(),
              intent,
              research_focus: focus,
              budget_seconds: intent === "build" ? 1200 : 600,
              seed_urls: seeds
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean),
            }),
          );
          if (j) done(j);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        公司代码
        <input
          required
          value={target}
          onChange={(e) => setTarget(e.target.value)}
        />
      </label>
      <label>
        研究重点
        <textarea
          aria-label="研究重点"
          required
          value={focus}
          onChange={(e) => setFocus(e.target.value)}
        />
      </label>
      <p>
        来源范围：官方披露、监管与行业资料、可追溯媒体。默认检查最近三个财年和八个季度。
      </p>
      <details>
        <summary>指定公开链接或登记新公司</summary>
        <label>
          优先取得的链接（每行一个）
          <textarea value={seeds} onChange={(e) => setSeeds(e.target.value)} />
        </label>
        <label className="w-check">
          <input
            type="checkbox"
            checked={register}
            onChange={(e) => setRegister(e.target.checked)}
          />
          登记这个公司主体
        </label>
        {register && (
          <>
            <label>
              公司完整名称
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              官方域名（用逗号分隔）
              <input
                required
                placeholder="ir.example.com"
                value={domains}
                onChange={(e) => setDomains(e.target.value)}
              />
            </label>
          </>
        )}
      </details>
      <p className="d-muted">
        本次预算{intent === "build" ? "二十" : "十"}
        分钟。未完成范围会保留，可继续执行。整理完成后等待人工采纳。
      </p>
      <button className="primary" disabled={busy}>
        {busy
          ? "正在创建任务…"
          : intent === "build"
            ? "开始搜集并构建"
            : "检查资料并更新"}
      </button>
    </form>
  );
}

function JobList({ company, nav }: { company: string; nav: Nav }) {
  const { data = [] } = useQuery({
    queryKey: ["wiki-job-list", company],
    queryFn: () => api("/wiki/jobs?company=" + company),
    refetchInterval: 3000,
  });
  return (
    <section>
      <h2>建库与更新任务</h2>
      <p>执行进度与正式知识的发布状态分别记录。</p>
      {data.length ? (
        data.map((j: any) => (
          <button
            className="ww-job-row"
            key={j.id}
            onClick={() => nav({ job: j.id })}
          >
            <strong>
              {j.request.intent === "build" ? "构建" : "更新"} {j.company} Wiki
            </strong>
            <span>
              {execution[j.execution_status]} ·{" "}
              {publication[j.publication_status]}
            </span>
            <small>{j.created_at.slice(0, 16).replace("T", " ")}</small>
          </button>
        ))
      ) : (
        <p className="d-empty">
          尚未发起任务。构建公司 Wiki 会从主动寻找公开资料开始。
        </p>
      )}
    </section>
  );
}
function JobDetail({ id, run, nav }: { id: string; run: any; nav: Nav }) {
  const { data: j } = useQuery({
    queryKey: ["wiki-job", id],
    queryFn: () => api("/wiki/jobs/" + id),
    refetchInterval: 3000,
  });
  if (!j) return <p>载入任务…</p>;
  return (
    <section className="ww-job-detail">
      <button onClick={() => nav({ job: null, tab: "jobs" })}>
        ← 全部任务
      </button>
      <h2>
        {j.company} ·{" "}
        {j.request.intent === "build" ? "构建公司 Wiki" : "更新 Wiki"}
      </h2>
      <p>{j.request.research_focus}</p>
      <div className="ww-job-states">
        {j.agent&&<span>{j.agent.provider==='claude'?'Claude Code':'Codex'} · {j.agent.resolved_model||j.agent.model||'本机默认模型'}</span>}
        <b>{stages[j.stage] || j.stage}</b>
        <span>{execution[j.execution_status]}</span>
        <strong>{publication[j.publication_status]}</strong>
      </div>
      <ol className="ww-job-pipeline">
        {[
          "制定需求",
          "寻找资料",
          "保存与转换",
          "检查质量",
          "整理页面",
          "人工采纳",
        ].map((s, i) => (
          <li key={s}>
            <small>{i + 1}</small>
            {s}
          </li>
        ))}
      </ol>
      <p>
        已取得 {j.materials.filter((m: any) => m.source_id).length} 份资料 ·
        失败 {j.failures.length} 项 · 未处理 {j.skipped.length} 项 · 规范 v
        {j.policy.version}
      </p>
      {j.error && (
        <p className="d-warning" role="alert">
          {j.error}
        </p>
      )}
      <div className="ww-actions">
        {j.proposal_id && (
          <button
            className="primary"
            onClick={() =>
              nav({ job: null, tab: "review", proposal: j.proposal_id })
            }
          >
            阅读完整变更与审核
          </button>
        )}
        {["queued", "running"].includes(j.execution_status) ? (
          <button
            onClick={() =>
              run(
                () =>
                  api("/wiki/jobs/" + id + "/cancel", {
                    operation_id: operation(),
                  }),
                "任务已取消，已保存原件保留",
              )
            }
          >
            取消任务
          </button>
        ) : (
          <button
            onClick={() =>
              run(async () => {
                const next = await api("/wiki/jobs/" + id + "/resume", {
                  operation_id: operation(),
                });
                nav({ job: next.id });
                return next;
              })
            }
          >
            继续补查
          </button>
        )}
      </div>
      <h3>资料清单</h3>
      <table>
        <thead>
          <tr>
            <th>资料 / 原始出处</th>
            <th>主体与类别</th>
            <th>获取结果</th>
          </tr>
        </thead>
        <tbody>
          {j.materials.map((m: any, i: number) => (
            <tr key={i}>
              <td>
                {m.source_id ? (
                  <button
                    onClick={() =>
                      nav({ tab: "raw", source: m.source_id, job: null })
                    }
                  >
                    {m.title || m.url}
                  </button>
                ) : (
                  <a href={m.url} target="_blank" rel="noreferrer">
                    {m.title || m.url}
                  </a>
                )}
                <small>{m.publisher}</small>
              </td>
              <td>
                {m.subject_company || m.subject} ·{" "}
                {sourceTypes[m.provider] || m.category}
              </td>
              <td>
                <AcquisitionResult material={m}/>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>覆盖与缺口</h3>
      <div className="ww-coverage">
        {j.coverage.map((n: any) => (
          <div key={n.id}>
            <b>{n.label}</b>
            <span>
              {n.status === "materials_found"
                ? "已找到材料，仍需核验"
                : "尚缺材料"}
            </span>
          </div>
        ))}
      </div>
      <h3>质量检查</h3>
      {j.checks.map((c: any, i: number) => (
        <p key={i}>
          {(
            {
              acquisition: "获取与解析",
              coverage: "资料覆盖",
              source_identity: "来源与主体",
              publication: "发布前校验",
            } as any
          )[c.kind] || c.kind}{" "}
          ·{" "}
          {c.status === "passed"
            ? "已通过"
            : c.status === "recorded"
              ? "已记录"
              : c.status === "awaiting_validation"
                ? "已提交统一校验"
                : "检查不完整"}
          {c.note && " · " + c.note}
        </p>
      ))}
      <details open={j.failures.length + j.skipped.length > 0}>
        <summary>失败、跳过与搜索范围</summary>
        {[...j.failures, ...j.skipped].map((f: any, i: number) => (
          <p key={i}>
            {f.url || stages[f.stage] || f.stage} · {f.reason}
            {f.resolved_by && " · 已由替代原件补齐，保留本次失败记录"}
          </p>
        ))}
        {j.discovery?.search_log?.map((s: string, i: number) => (
          <p key={i}>{s}</p>
        ))}
        {j.discovery?.gaps?.map((s: string, i: number) => (
          <p key={i}>未完成：{s}</p>
        ))}
        {j.supplemental_discovery?.search_log?.map((s: string, i: number) => <p key={"supplement-" + i}>缺口补查：{s}</p>)}
        {j.supplemental_discovery?.gaps?.map((s: string, i: number) => <p key={"gap-" + i}>补查仍未完成：{s}</p>)}
        {j.catalog_checks?.length > 0 && <p>已检查 {j.catalog_checks.length} 个官方目录，原始页面已保存。</p>}
        {j.catalog_excluded?.length > 0 && <details><summary>目录中未重复获取的资料（{j.catalog_excluded.length}）</summary>
          {j.catalog_excluded.map((c: any, i: number) => <p key={i}>{c.title || c.url} · {c.reason}</p>)}
        </details>}
      </details>
      {j.previous_failures?.length > 0 && <details>
        <summary>上次任务的失败记录（{j.previous_failures.length}）</summary>
        <p>这些是恢复前的记录，本次获取结果和剩余缺口单独列出。</p>
        {j.previous_failures.map((f: any, i: number) => <p key={i}>{f.url || f.stage} · {f.reason}</p>)}
      </details>}
    </section>
  );
}

function Schedule({
  company,
  current,
  run,
  done,
}: {
  company: string;
  current: any;
  run: any;
  done: any;
}) {
  const [enabled, setEnabled] = useState(current?.enabled ?? true),
    [frequency, setFrequency] = useState(current?.frequency || "weekly"),
    [days, setDays] = useState<number[]>(current?.weekdays || [0]),
    [time, setTime] = useState(current?.local_time || "09:00"),
    [zone, setZone] = useState(
      current?.timezone ||
        Intl.DateTimeFormat().resolvedOptions().timeZone ||
        "Asia/Shanghai",
    );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const s = await api("/wiki/schedules", {
            operation_id: operation(),
            company,
            enabled,
            frequency,
            weekdays: days,
            local_time: time,
            timezone: zone,
            research_focus:
              current?.research_focus || "复核新披露与已有研究认识的变化",
            budget_seconds: 600,
            notification_event_id: current?.notification_event_id || "",
          });
          done();
          return s;
        }, "更新计划已保存");
      }}
    >
      <p>
        定时执行与“更新
        Wiki”使用同一资料流程。每次十分钟，正式发布仍需人工采纳。
      </p>
      <label className="w-check">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        启用定时更新
      </label>
      <label>
        频率
        <select
          value={frequency}
          onChange={(e) => setFrequency(e.target.value)}
        >
          <option value="daily">每天</option>
          <option value="weekly">每周</option>
          <option value="custom">自定义星期</option>
        </select>
      </label>
      {frequency !== "daily" && (
        <div className="ww-weekdays">
          {["一", "二", "三", "四", "五", "六", "日"].map((label, i) => (
            <label key={i}>
              <input
                type="checkbox"
                checked={days.includes(i)}
                onChange={(e) =>
                  setDays(
                    e.target.checked
                      ? [...days, i]
                      : days.filter((d) => d !== i),
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
      )}
      <div className="w-form-row">
        <label>
          执行时间
          <input
            required
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
          />
        </label>
        <label>
          时区
          <input
            required
            value={zone}
            onChange={(e) => setZone(e.target.value)}
          />
        </label>
      </div>
      {current?.next_at && (
        <p>
          下次执行：{new Date(current.next_at).toLocaleString()}（本机显示时间）
        </p>
      )}
      <p className="d-muted">
        本机工作进程运行时执行；休眠后合并补查。无变化保留记录，出现待审核修改或失败时提示。
      </p>
      <div className="ww-actions">
        <button
          className="primary"
          disabled={!days.length && frequency !== "daily"}
        >
          保存更新设置
        </button>
        {current && !current.cancelled && (
          <button
            type="button"
            onClick={() =>
              run(async () => {
                const r = await api("/wiki/schedules/" + company + "/cancel", {
                  operation_id: operation(),
                });
                done();
                return r;
              }, "定时更新已取消")
            }
          >
            取消此计划
          </button>
        )}
      </div>
    </form>
  );
}

function ReviewList({
  data,
  reviewData,
  id,
  nav,
  run,
  edit,
}: {
  data: any;
  reviewData: any;
  id: string;
  nav: Nav;
  run: any;
  edit: any;
}) {
  const selected =
    id ||
    data.proposals.find((p: any) => p.status === "pending")?.id ||
    data.proposals[0]?.id;
  const { data: p } = useQuery({
    queryKey: ["wiki-proposal", selected],
    queryFn: () => api("/wiki/proposals/" + selected),
    enabled: !!selected,
  });
  return (
    <section>
      <div className="ww-section-head">
        <h2>完整变更审核</h2>
        <select
          aria-label="选择审核批次"
          value={selected || ""}
          onChange={(e) => nav({ proposal: e.target.value })}
        >
          {data.proposals.map((p: any) => (
            <option key={p.id} value={p.id}>
              {p.reason} · {state(p.status)}
            </option>
          ))}
        </select>
      </div>
      {p && reviewData ? (
        <Batch
          key={p.id + p.status}
          proposal={p}
          sources={reviewData.sources}
          run={run}
          edit={() => edit(p)}
        />
      ) : (
        <p className="d-empty">
          暂无完整变更包。资料整理完成后，在此查看修改原因、完整正文与证据。
        </p>
      )}
    </section>
  );
}
function Batch({
  proposal: p,
  sources,
  run,
  edit,
}: {
  proposal: any;
  sources: any[];
  run: any;
  edit: any;
}) {
  const [index, setIndex] = useState(0),
    [reading, setReading] = useState(true),
    [reason, setReason] = useState(""),
    [read, setRead] = useState(false),
    [busy, setBusy] = useState(false),
    [visited, setVisited] = useState<number[]>([0]),
    c = p.request.changes[index];
  const { data: observations = [] } = useQuery({
    queryKey: ["wiki-observations", p.company],
    queryFn: () => api("/wiki/observations?company=" + p.company),
  });
  function select(i: number) {
    setIndex(i);
    setVisited((v) => [...new Set([...v, i])]);
  }
  return (
    <article className="ww-review">
      <div className="ww-review-intro">
        <span className="ww-kicker">完整变更概览</span>
        <h2>{p.request.reason}</h2>
        <p>
          <Status value={p.status} /> · {p.request.changes.length}{" "}
          处修改整批发布 · 维护规范 v{p.request.policy.version}
        </p>
        <p>
          逐页核对正文、证据和关联影响。引用定位、数字与版本通过系统检查；含义和判断仍由你采纳。
        </p>
      </div>
      <nav className="ww-batch-tabs" aria-label="本批修改">
        {p.request.changes.map((r: any, i: number) => (
          <button
            key={r.id}
            className={i === index ? "active" : ""}
            onClick={() => select(i)}
          >
            <small>
              {visited.includes(i) ? "已查看" : "待查看"} ·{" "}
              {types[r.page_type] || "知识"}
            </small>
            {r.title}
          </button>
        ))}
      </nav>
      <div className="ww-section-head">
        <h3>
          {c.title}{" "}
          <small>
            v{c.expected_version} → v{c.expected_version + 1}
          </small>
        </h3>
        <button onClick={() => setReading(!reading)}>
          {reading ? "对照修改前后" : "阅读拟发布版本"}
        </button>
      </div>
      <p>{c.reason}</p>
      <div className={reading ? "ww-review-page" : "w-diff"}>
        {!reading && (
          <section>
            <h4>修改前</h4>
            <ReviewContent
              revision={p.before[c.id]}
              observations={observations}
              sources={sources}
            />
          </section>
        )}
        <section>
          <h4>拟发布</h4>
          <ReviewContent
            revision={c}
            observations={observations}
            sources={sources}
          />
        </section>
      </div>
      {c.relations.length > 0 && (
        <p>
          关联影响：
          {c.relations
            .map((r: any) => r.target.id + " · v" + r.target.version)
            .join("、")}
        </p>
      )}
      <div className="ww-actions">
        <button disabled={index === 0} onClick={() => select(index - 1)}>
          上一页
        </button>
        <span>
          {index + 1} / {p.request.changes.length}
        </span>
        <button
          disabled={index === p.request.changes.length - 1}
          onClick={() => select(index + 1)}
        >
          下一页
        </button>
      </div>
      {p.status === "pending" && (
        <form
          className="w-adopt"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            await run(
              () =>
                api("/wiki/proposals/" + p.id + "/review", {
                  operation_id: operation(),
                  digest: p.digest,
                  action: "adopt",
                  reason,
                }),
              "整批知识与页面已发布",
            );
            setBusy(false);
          }}
        >
          <label className="w-check">
            <input
              type="checkbox"
              checked={read}
              onChange={(e) => setRead(e.target.checked)}
            />
            我已核对完整变更、原始证据和关联影响
          </label>
          <label>
            采纳或驳回理由
            <textarea
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <div className="ww-actions">
            <button type="button" onClick={edit}>
              编辑并重新校验
            </button>
            <button
              type="button"
              disabled={!reason.trim() || busy}
              onClick={() =>
                run(
                  () =>
                    api("/wiki/proposals/" + p.id + "/review", {
                      operation_id: operation(),
                      digest: p.digest,
                      action: "reject",
                      reason,
                    }),
                  "已驳回并保留理由",
                )
              }
            >
              驳回
            </button>
            <button
              className="primary"
              disabled={
                !read ||
                !reason.trim() ||
                busy ||
                visited.length < p.request.changes.length
              }
            >
              采纳并发布整批
            </button>
          </div>
        </form>
      )}
    </article>
  );
}

function Ask({
  company,
  context,
  asOf,
  run,
  nav,
  update,
}: {
  company: string;
  context: any;
  asOf: string;
  run: any;
  nav: Nav;
  update: any;
}) {
  const [question, setQuestion] = useState(""),
    [reading, setReading] = useState<any>(null),
    [taskId, setTaskId] = useState(""),
    [busy, setBusy] = useState(false),
    [target, setTarget] = useState("");
  const { data: task } = useQuery({
    queryKey: ["wiki-answer-task", taskId],
    queryFn: () => api("/tasks/" + taskId),
    enabled: !!taskId,
    refetchInterval: (q) =>
      ["completed", "failed", "cancelled"].includes(
        (q.state.data as any)?.status,
      )
        ? false
        : 1500,
  });
  const [edits, setEdits] = useState<{ title?: string; content?: string }>({});
  const answer = task?.result?.answer;
  const answerTitle = edits.title ?? answer?.title ?? "",
    answerContent = edits.content ?? answer?.content ?? "";
  async function ask() {
    setBusy(true);
    try {
      const r = await run(() =>
        api("/wiki/query", {
          operation_id: operation(),
          company,
          question,
          as_of: asOf || null,
          context_refs:
            context && ["topic", "company"].includes(context.page_type)
              ? [ref(context)]
              : [],
        }),
      );
      if (r) {
        setReading(r);
        setEdits({});
        setTaskId("");
        if (r.items.length) {
          const t = await run(() =>
            api("/wiki/query/" + r.id + "/answer", {
              operation_id: operation(),
            }),
          );
          if (t) setTaskId(t.id);
        }
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="ww-ask">
      <span className="ww-kicker">基于 Wiki 与原始依据</span>
      <h2>接着已有认识提问</h2>
      {context && (
        <p>
          当前页面：{context.title} · v{context.version}
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask();
        }}
      >
        <label>
          研究问题
          <textarea
            required
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="利润率变化是否改变了我们已有的解释？哪些证据支持，哪些仍有缺口？"
          />
        </label>
        <button
          className="primary"
          disabled={busy || ["queued", "running"].includes(task?.status)}
        >
          {busy ? "正在读取…" : "查阅 Wiki 并回答"}
        </button>
      </form>
      {reading && (
        <p>
          已检索 {reading.items.length} 个相关版本。
          {answer
            ? "答案实际使用 " + answer.used.length + " 个版本。"
            : "正在核对可用依据。"}
        </p>
      )}
      {reading && !reading.items.length && (
        <div className="ww-unwritten">
          <h3>当前知识不足以回答</h3>
          <p>没有可用的已发布页面。可以先查看草稿，或明确发起资料补查。</p>
          <button onClick={() => nav({ tab: "review" })}>查看待审核草稿</button>
          <button disabled={!!asOf} onClick={update}>补查公开资料 / 更新此专题</button>
        </div>
      )}
      {reading?.items?.length > 0 && (
        <details className="ww-answer-edit">
          <summary>编辑分析草稿</summary>
          <label>
            分析标题
            <input
              value={answerTitle}
              onChange={(e) => setEdits({ ...edits, title: e.target.value })}
            />
          </label>
          <label>
            新认识、比较与未解决问题
            <textarea
              value={answerContent}
              onChange={(e) => setEdits({ ...edits, content: e.target.value })}
            />
          </label>
        </details>
      )}
      {task && !answer && (
        <p role="status">
          {state(task.status)}
          {task.error && " · " + task.error}
        </p>
      )}
      {answer && (
        <EvidenceScope revision={answer}>
          <article className="ww-answer">
            <h3>{answerTitle}</h3>
            <Prose text={answerContent} />
            <Evidence citations={answer.citations} sources={reading.sources} />
            <h4>实际使用的 Wiki 版本</h4>
            {answer.used.map((r: any) => (
              <button
                key={r.id}
                onClick={() =>
                  nav({ tab: "page", page: r.id, version: String(r.version) })
                }
              >
                {reading.items.find((p: any) => p.id === r.id)?.title || r.id} ·
                v{r.version}
              </button>
            ))}
            <div className="ww-writeback">
              <h3>把新分析接到已有研究</h3>
              <label>
                修订目标
                <select
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                >
                  <option value="">自动选择所用研究专题</option>
                  <option value="__analysis">保存为独立综合分析</option>
                  {reading.items
                    .filter((p: any) =>
                      ["topic", "company", "analysis"].includes(p.page_type),
                    )
                    .map((p: any) => (
                      <option key={p.id} value={p.id}>
                        {p.title} · v{p.version}
                      </option>
                    ))}
                </select>
              </label>
              <button
                disabled={!!asOf}
                onClick={() =>
                  run(async () => {
                    const p = reading.items.find((r: any) => r.id === target);
                    const saved = await api("/wiki/answers", {
                      operation_id: operation(),
                      query_id: reading.id,
                      title: answerTitle,
                      content: answerContent,
                      used: answer.used,
                      citations: answer.citations,
                      numeric_assertions: answer.numeric_assertions,
                      target: p ? ref(p) : null,
                      writeback: target === "__analysis" ? "analysis" : "topic",
                      save_proposal: true,
                    });
                    if (saved.proposal_id)
                      nav({ tab: "review", proposal: saved.proposal_id });
                    return saved;
                  }, "分析已形成修订草稿；重复内容复用已有提案")
                }
              >
                保存分析并提交审核
              </button>
              <button disabled={!!asOf} onClick={update}>补查公开资料 / 更新此专题</button>
            </div>
          </article>
        </EvidenceScope>
      )}
      {reading && (
        <details>
          <summary>检索命中与排除记录</summary>
          {reading.items.map((p: any) => (
            <p key={p.id}>
              {p.title} · v{p.version}
            </p>
          ))}
          {reading.excluded?.map((p: any) => (
            <p key={p.ref}>
              {p.ref} · {p.reason}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
function UpdateLog({ company, time }: { company: string; time: string }) {
  const { data = [] } = useQuery({
    queryKey: ["wiki-log", company, time],
    queryFn: () => api("/wiki/log?company=" + company + time),
  });
  const names: Record<string, string> = {
    "job.created": "发起资料任务",
    "job.progress": "任务阶段记录",
    "job.finished": "任务执行结束",
    "source.acquired": "保存公开原件",
    "source.checked": "复查资料",
    "proposal.created": "提交完整变更",
    "proposal.adopted": "采纳并发布",
    "proposal.rejected": "驳回修订",
    "query.answered": "保存研究回答",
    "source.ingested": "导入原始资料",
    "source.captured": "收录研究线索",
    "update.schedule_changed": "调整更新计划",
    "update.schedule_fired": "定时更新触发",
  };
  return (
    <section>
      <h2>更新记录</h2>
      <p>收录、整理、审核、研究使用与维护共同构成一条知识的生命周期。</p>
      {data
        .filter((e: any) => e.kind !== "job.progress")
        .map((e: any) => (
          <div className="ww-log-row" key={e.sequence}>
            <time>{e.occurred_at.slice(0, 16).replace("T", " ")}</time>
            <b>{names[e.kind] || e.kind}</b>
            {e.details.reason && <p>{e.details.reason}</p>}
          </div>
        ))}
    </section>
  );
}
function Maintenance({
  data,
  company,
  run,
  correct,
}: {
  data: any;
  company: string;
  run: any;
  correct: any;
}) {
  return (
    <section>
      <div className="ww-section-head">
        <h2>问题与影响范围</h2>
        <button
          onClick={() =>
            run(
              () =>
                api("/wiki/inspections", {
                  operation_id: operation(),
                  company,
                  kind: "rules",
                }),
              "规则巡检已入队",
            )
          }
        >
          运行规则巡检
        </button>
        <button
          onClick={() =>
            run(
              () =>
                api("/wiki/inspections", {
                  operation_id: operation(),
                  company,
                  kind: "semantic",
                }),
              "语义巡检已入队",
            )
          }
        >
          运行语义巡检
        </button>
      </div>
      {data.issues.map((i: any) => (
        <Issue key={i.id} issue={i} run={run} correct={() => correct(i)} />
      ))}
      {!data.issues.length && (
        <p className="d-empty">尚无已登记疑点。阅读中可对具体段落报错。</p>
      )}
      <h3>维护记录</h3>
      {data.inspections?.map((i: any) => (
        <details key={i.id}>
          <summary>
            {i.kind === "rules" ? "规则巡检" : "语义巡检"} ·{" "}
            {i.started_at.slice(0, 16)} · {i.scope.length} 个检查对象
          </summary>
          <p>
            跳过 {i.skipped.length} · 失败 {i.failures.length}
            {i.budget_exhausted ? " · 预算耗尽" : ""}
          </p>
          {i.finished_at && <InspectionFeedback run={run} inspection={i} />}
        </details>
      ))}
    </section>
  );
}
