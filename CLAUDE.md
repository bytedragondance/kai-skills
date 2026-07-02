# CLAUDE.md — 我的个人 Claude Code Skill 工作流（fork 自 mattpocock/skills）

## 这个仓库是什么

从 `mattpocock/skills` fork 来的**个人化编程 skill 集**。目标：以 skill 为主搭自己的
Claude Code 工作流。选它做基座的原因——它"小而可组合"，每个 skill 单一职责、互不替代，
**为裁剪而生**（superpowers/BMAD 那种门控互锁的集子裁不动，故未选）。

## 命名 / 可移植：skill 不绑 Claude

这些 skill 是 **Agent Skills 开放标准**（纯 `name`+`description` frontmatter + markdown 正文），
README 原话 "work with any model"，同一批 skill 能装进多个 harness（`~/.claude/skills` Claude Code +
`~/.agents/skills` pi 等标准 harness，Codex/Cursor 亦可）。所以仓库取了 **agent 中立名**（非 `claude-*`）。
含义：**裁剪决策与 agent 无关**，按"编程流程需不需要"判断即可；哪天想上 Codex/Cursor，SKILL.md 正文
直接带走，只换安装位置。

真正绑 Claude 的只有薄壳：`.claude-plugin/plugin.json`（Claude 插件清单）、`/` 斜杠调用 UX、
少数名字冲着 Claude 的 skill（`git-guardrails-claude-code`/`claude-handoff`/`setup-matt-pocock-skills`）。

## 分支 / 追踪纪律（重要，别破坏）

- `main` = 上游纯净镜像，**永不手改**，只用 `merge --ff-only upstream/main` 前进。
- `mine` = 我的策展集 = 实际用的那套。所有裁剪、我自己的 skill 都在这。
- 追踪上游：跑 `bin/check-upstream.sh` -> 看 diff -> **只 `cherry-pick` 想要的那一笔**。
- **铁律：绝不 `git merge upstream/main` 到 mine。** merge 是"默认全收"，个人集要的是
  "默认不收、逐笔点头"。方向反了就会把删掉的 cruft、不想要的新 skill 全带回来。

## 保持 cherry-pick 干净的关键约定

- **留下的上游 skill 尽量别改内容**（改了 -> 上游同文件一改，cherry-pick 必冲突）。
- **我的定制走"新增"而非"修改"**：自己的 skill 放到 `skills/mine/` 目录（上游永远不碰这里），
  而不是去魔改 `skills/engineering/tdd/`。两个世界物理隔离，追踪才长期无痛。

## 待办：裁剪（下一次会话的主任务）

基座是 v0.3 期 ~38 个 skill。按下表对 `skills/*/` 执行 `git rm -r`（先 `ls skills/*/`
核实真实路径，分类目录有 engineering/productivity/misc/personal/in-progress/deprecated）：

| 动作 | Skill（按名） | 理由 |
|------|--------------|------|
| 留·编码主循环 | research, codebase-design, domain-modeling, tdd, implement, diagnosing-bugs, code-review | 理解->设计->测试->实现->修bug->审 的骨架；domain-modeling 是 mattpocock 签名（DDD 进 loop） |
| 留·编排 | wayfinder（规划大工作）, handoff（跨 session 交接） | 多步任务骨架 |
| 留·护栏 | git-guardrails-claude-code, setup-pre-commit | 便宜的安全网 |
| 留·接入 | setup-matt-pocock-skills | 一次性接通 issue tracker/label/docs 位置 |
| 留·元 | writing-great-skills, grilling | 前者让我能写自己的新 skill；后者是"审讯需求"可复用原语 |
| 看情况 | to-prd, to-issues, triage（ticket 驱动才留）; prototype（做 UI 才留）; improve-codebase-architecture; resolving-merge-conflicts | 按实际流程定 |
| 删·非编码 | teach, scaffold-exercises, obsidian-vault, edit-article, writing-beats, writing-fragments, writing-shape, ask-matt, grill-me, migrate-to-shoehorn, multilingual, wizard, loop-me, deprecated/* | 他个人生活/写作/特定库的，与编码流无关 |

裁剪原则：**删得比留得狠**——留着不触发的 skill 会污染 model 的 skill 选择 + 增加维护负担。

**删 skill 时同步删 `.claude-plugin/plugin.json` 里 `skills[]` 的对应条目**，否则清单指向不存在的目录
（仅当以 Claude 插件方式安装才生效；若走 symlink 进 `~/.claude/skills/` 则可无视 plugin.json）。
注：`plugin.json` 和 `CLAUDE.md`/`bin/` 一样属于**"我拥有的、允许偏离上游"的文件**，不在"保持 pristine
以便 cherry-pick"的约束内。

### 裁完顺手做两件事
1. 给每个留下的 skill 归类 **User-invoked（我手动 `/` 喊的编排器）** vs
   **Model-invoked（该自动触发的纪律）**，触发不准就调 description。
2. 跑几个真实任务，验证没有两个 skill 描述撞车导致选错。

### 最好先做：从真实痛点倒推种子集
别照搬上表。先回顾**过去两周最烦的 3-5 个 Claude Code 卡点**，据此定"必留"清单，
再拿上表做减法。个人化工作流的种子应该长在真实摩擦上。

## 激活（裁剪稳定后）

把 `skills/` symlink 进 Claude Code 能发现的位置，或用它自带的 plugin 机制 /
`npx skills`。然后在目标项目里跑 `/setup-matt-pocock-skills` 接通 issue tracker。

## 相关背景

分析笔记见我的研究仓库 ai-dev-field-note：R54 mattpocock 深度分析、
R125「方法论 skill 集两条收敛轴」（User/Model-invoked 二分法出处）。
