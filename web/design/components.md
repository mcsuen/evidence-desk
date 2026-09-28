# PITR 组件清单与状态

来源：Claude Design 画布第 0 板与各页面板，2026-09-21 定稿。实现位于 `web/src/ui/`（薄封装 Radix Primitives；feature 层不直接引用 `@radix-ui/*`）。

## 壳层
- **AppShell**：左侧导航栏 200px（可折叠为 56px 图标栏），顶栏 52px，内容区。
- **SideNav**：今日 / 公司 / 研究 / 审核 / 维护，底部 设置 + “本机私有 · 127.0.0.1”。计数徽章：红色 = 需要你决定，灰色 = 待办数量。
- **TopBar**：公司切换（图标 + 代码 + 名称 + ▾）、命令框（占位“跳转公司、打开知识页，或直接提问… ⌘K”）、右侧页面动作、主题切换。顶栏不放 Agent / 模型（按任务绑定）。
- **CommandPalette**（cmdk）：跳公司、打开知识页、就 X 提问。
- **BottomNav**（<768）：今日 / 公司 / 研究 / 审核 / 更多；浮动“提问”按钮 44px。

## 基础控件
- **Button**：primary / default / ghost / danger；尺寸 md 32 / sm 26；可带 14px 图标；禁用态透明度 .55 并给出原因文字。
- **IconButton** 34px，必须有 `aria-label`。
- **Input / Textarea / Select / DateTime**：高 34，边框 line-strong，圆角 7；`textarea.input` 自动高度不可拖。
- **SegmentedControl**（`.seg`）：筛选与视图切换，选中态反色。
- **Tabs**：高 38，下边 2px ink 线；用于 研究 / 执行流程 / Trace、公司页子导航、检查器分页。
- **Badge**：默认 / ok / warn / danger / accent；22px，不换行不压缩。
- **StatusDot** 8px：ok / warn / danger / accent / pending。
- **EvidenceTag**（`.ev`）：official 实线青 / author 实线紫 / infer 虚线棕；20px，不换行不压缩。
- **NumberChip**（`.num`）：正文里的绑定数字，虚线下划线 = 证据入口，选中态 `on` 实线 + 淡底；点击打开证据栏，关闭回到原位置并归还焦点。
- **Card / CardHeader / Row**：卡片 10px 圆角；行 12×16 内边距，最后一行无底线。
- **Table**（`.tbl`）：表头 11px 眉标；数值列右对齐等宽数字；行高按密度。
- **VerifyStrip**（`.verify`）：核验条，格子按内容取宽、可换行、整体不压缩；研究页四格：引用与数值 / 独立复核 / 人工采纳 / 时点承诺（PIT）。
- **Quote**（`.quote`）：引文，左边框取证据身份色，背景 inset。
- **KeyValue**（`.kv`）：期间 / 单位 / 可得时间 / 独立复核。
- **Progress**、**Spark**（迷你趋势：2px 线、12% 面填充、端点强调）、**Chart**（ECharts 容器，主题跟随 token）。
- **Toast**：深底浅字，带图标；**EmptyState**、**Skeleton**、**InlineError**。

## 浮层
- **EvidenceRail**：桌面右侧 360–380px 非模态侧栏（Radix Dialog `modal={false}`），可拖宽；窄屏为底部抽屉（模态 + 遮罩，拖柄）。头部：眉标“依据” + 数值 + 关闭。
- **Drawer**：目录抽屉（左，300px）、节点检查器（右 380px / 窄屏底部）。
- **Dialog / Popover / Tooltip / DropdownMenu**：Radix。

## 业务组件
- **AttentionGroup**（今日）：需要你回答 / 可以阅读的报告 / 待采纳 / 信号与异常。
- **Composer**：问题框 + 对象/期间/Wiki 引用标签 + 材料 + “本次执行”（Agent / 模型 / 推理强度 / 信息截止 / PIT 模式）+ 先查 Wiki / 开始研究。
- **AnswerFirst**：判断编号 1-2-3（衬线数字）→ 资料缺口 → 下一步 → 关键指标对照。
- **CompanyHeader + SubNav**：概览 / 知识 / 资料 / 数据 / 产业链 / 论点 / 问题 / 历史。
- **Directory**（三层：原始资料 / 知识 Wiki / 维护规范）。
- **ReviewQueue + Diff**：队列按公司分组；修改前后对照 `del/ins`；本处依据；关系与影响；采纳表单（全部查看后才可整批采纳）。
- **RunGraph**（执行流程）：纵向 DAG，节点卡片；并行分支并排、修复边橙色、数据依赖蓝色虚线；运行中节点脉冲；“需要注意”条置顶；工具按类型聚合；节点检查器分页加载事件。调试功能（回放、导出诊断包、LangSmith）仅 `--debug` 显示。
