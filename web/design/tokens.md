# PITR 设计基础 · Token

来源：Claude Design 画布「PITR 研究工作台重设计」第 0 板，2026-09-21 定稿。代码中的唯一实现是 `web/src/styles/tokens.css`；本文档只解释角色与取值，不再单独维护第二份数值。

## 色彩（按角色，浅色 / 深色逐个重选，不是反相）

| 角色 | 变量 | 浅色 | 深色 | 用途 |
| --- | --- | --- | --- | --- |
| 画布 | `--bg` | `#F4F5F8` | `#0F1217` | 页面底 |
| 面板 | `--surface` | `#FFFFFF` | `#161A21` | 卡片、导航栏、表格 |
| 内凹 | `--inset` | `#EEF0F4` | `#12151B` | 输入框底、引文底、条形图底 |
| 分隔 | `--line` | `#E3E6EC` | `#262C36` | 边框、分隔线 |
| 强分隔 | `--line-strong` | `#C9CED8` | `#39414E` | 输入框边、按钮边 |
| 正文 | `--ink` | `#171A21` | `#E7EAF0` | |
| 次要 | `--ink-2` | `#4A5160` | `#AEB5C2` | 说明文字 |
| 弱化 | `--ink-3` | `#7A8294` | `#7C8494` | 眉标、时间、辅助 |
| 强调 | `--accent` / `--accent-ink` / `--accent-soft` | `#2F5BEA` / `#FFFFFF` / `#E8EEFF` | `#7DA2FF` / `#0F1217` / `#1E2A4A` | 唯一强调色：主按钮、选中、数字证据入口下划线 |
| 通过 | `--ok` / `--ok-soft` | `#1E8E5A` / `#E3F5EC` | `#3BC27E` / `#14301F` | 语义状态，不当强调色用 |
| 注意 | `--warn` / `--warn-soft` | `#B7791F` / `#FBF1DC` | `#E0A03A` / `#3A2C12` | 需要你补充、待复核、修复边 |
| 失败 | `--danger` / `--danger-soft` | `#C93B4C` / `#FBE7EA` | `#F06A78` / `#3D1A20` | 失败、中断、红色信号 |
| 待定 | `--pending` / `--pending-soft` | `#7A8294` / `#EEF0F4` | `#8B93A2` / `#1C2129` | 待审核、未知 |
| 证据·官方披露 | `--ev-official` | `#0E7C86` | `#38B6C0` | 实线标签、引文左边框 |
| 证据·附件作者观点 | `--ev-author` | `#6D4FC2` | `#A78BFA` | 实线标签 |
| 证据·研究推断 | `--ev-infer` | `#8A6D3B` | `#C9A46A` | 虚线标签 |
| 信号 红/黄/绿 | `--sig-red` / `--sig-amber` / `--sig-green` | `#C93B4C` / `#C98500` / `#1E8E5A` | `#F06A78` / `#E0A03A` / `#3BC27E` | 信号面板、假设状态点 |
| 图表序列 1–4 | `--s1`…`--s4` | `#2F5BEA` `#0E9384` `#D97706` `#8B5CF6` | `#5B86F5` `#1FA893` `#C98500` `#9A7DF0` | 已通过 dataviz 色觉校验（两套各自校验） |
| 覆盖状态 | `--cov-none` `--cov-unverified` `--cov-candidate` `--cov-evidenced` `--cov-bidirectional` | `#C9CED8` `#B7791F` `#7A8294` `#2F5BEA` `#1E8E5A` | 取深色的 line-strong / warn / pending / accent / ok | 覆盖地图节点 |
| 关系阶段 | `--stage-candidate` `--stage-qualified` `--stage-transacting` `--stage-material` | pending / ev-official / accent / ok | 同左深色 | 关系图边 |
| 阴影 | `--shadow` | `0 8px 24px rgba(23,26,33,.12)` | `0 8px 24px rgba(0,0,0,.45)` | 只用于浮层 |

规则：证据身份三色必须一眼可分；语义色不当强调色；文字永远用 ink 系，序列色只给图形标记。

## 字体

- 界面与正文：`'IBM Plex Sans','Noto Sans SC',system-ui,sans-serif`，14px / 1.6；阅读正文（报告、知识页）15px / 1.85，段落宽 ≤ 660px。
- 标题与判断句：`'Noto Serif SC','Songti SC',serif` 600，用于报告标题、判断句、公司页“当前认识”标题、页面 h1。
- 等宽：`'IBM Plex Mono',ui-monospace,monospace`，用于 ID、ticker、计算式、事件时间。
- 数字全局 `font-variant-numeric: tabular-nums`。
- 字号阶：30 / 26 / 22 / 18 / 15 / 14 / 13 / 12 / 11（眉标：11px、600、字距 .08em、大写）。

## 间距、圆角、密度

- 4px 基准；圆角 4（小标签）/ 7（按钮、输入）/ 10（卡片）；圆形状态点 8px。
- 控件高度：主按钮 32、小按钮 26、输入 34、顶栏 52、标签页 38。
- 密度 `<html data-density="compact|comfortable">`：紧凑（表格、队列、Trace，行高 32）与舒适（阅读页，行高 40）。
- 响应式 4 档：≥1440 证据栏常驻；1024–1439；768–1023 导航折叠为图标栏；<768 底部导航 + 抽屉。

## 主题

`tokens.css` 在 `:root` 定义浅色，`@media (prefers-color-scheme: dark)` 下用 `:root:not([data-theme="light"])` 重定义，再用 `:root[data-theme="dark"]` 重定义一次；`app/theme.ts` 用 localStorage `pitr.theme` 覆盖并写到 `<html data-theme>`。ECharts / xyflow 通过 `lib/tokens.ts` 读取 CSS 变量，主题切换时重绘。
