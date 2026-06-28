你是资深 AI Agent 工程师、全栈工程师、小说创作工具产品架构师。请帮我从零实现一个“网文小说创作 Agent Harness”工程。

重要限制：

1. 不得使用、复制、反编译、参考任何泄露源码、非授权源码或商业闭源项目源码。
2. 可以参考公开资料、公开论文、公开文档、开源项目的设计思想，但必须独立实现。
3. 代码必须清晰、模块化、可测试、可扩展。
4. 先完成 MVP，再逐步扩展，不要一开始堆砌过度复杂的功能。
5. 所有 LLM 调用、搜索调用、向量库调用都要做成可替换 Provider，不要绑定单一厂商。

项目目标：
实现一个可以辅助网文作者进行长篇小说创作的 Agent Harness。它应该能帮助作者完成：

* 从作者已有文本中提取文风、叙事节奏、人物对白习惯、常用修辞、段落结构；
* 按已有文风续写小说，但要求生成内容必须是原创表达，不能大段复刻原文；
* 根据小说类型和设定自动做资料研究；
* 对历史小说、穿越小说、娱乐文、都市文、玄幻文等不同类型，搜索并整理相关资料；
* 为小说建立长期一致的 Story Bible，包括世界观、势力、人物、时间线、伏笔、已发生事件、未回收悬念；
* 帮作者完善人物设定、世界观设定、虚拟势力分布、剧情阶段目标；
* 生成下一阶段故事走向候选方案；
* 设计高潮、反转、伏笔、回收伏笔、爽点、冲突升级；
* 在续写前检查设定一致性、历史常识、人物动机、时间线冲突；
* 输出内容时附带“创作说明”和“事实依据摘要”，方便作者判断是否采用。

推荐技术栈：

* 后端：Python 3.11+
* CLI：Typer 或 Click
* API：FastAPI
* 数据模型：Pydantic
* 存储：SQLite + SQLModel 或 SQLAlchemy
* 向量库：先用 Chroma 或 LanceDB，本地优先
* 文档解析：Markdown / txt / docx / pdf 基础支持
* 搜索 Provider：抽象接口，先实现一个 MockSearchProvider，后续可接 Tavily、SerpAPI、Bing Search、Brave Search 等
* LLM Provider：抽象接口，先实现 MockLLMProvider，后续可接 OpenAI-compatible API、本地 llama.cpp、Ollama、vLLM 等
* 测试：pytest
* 配置：.env + pydantic-settings
* 日志：structlog 或标准 logging

请按照以下阶段工作。

第一阶段：生成工程骨架
请创建如下结构：

novel_harness/
pyproject.toml
README.md
.env.example
src/novel_harness/
**init**.py
cli.py
api.py
config.py
models/
project.py
style.py
research.py
story_bible.py
character.py
plot.py
generation.py
core/
orchestrator.py
context_manager.py
task_router.py
pipeline.py
providers/
llm/base.py
llm/mock.py
search/base.py
search/mock.py
vectorstore/base.py
vectorstore/local.py
agents/
style_analyzer.py
research_agent.py
worldbuilding_agent.py
character_agent.py
plot_planner.py
continuity_checker.py
foreshadowing_agent.py
scene_writer.py
revision_agent.py
fact_checker.py
services/
project_service.py
document_service.py
story_bible_service.py
generation_service.py
research_service.py
prompts/
style_analyzer.md
research_agent.md
plot_planner.md
scene_writer.md
continuity_checker.md
fact_checker.md
storage/
sqlite.py
repositories.py
tests/
test_style_analyzer.py
test_story_bible.py
test_plot_planner.py
test_continuity_checker.py

第二阶段：定义核心数据模型
请实现以下核心模型：

1. NovelProject
   字段包括：

* id
* name
* genre
* sub_genre
* premise
* target_audience
* tone
* created_at
* updated_at

2. StyleProfile
   字段包括：

* narrative_pov
* tense
* sentence_length
* paragraph_length
* dialogue_ratio
* common_phrases
* rhetorical_devices
* pacing
* emotional_temperature
* taboo_patterns
* style_summary
* continuation_guidelines

3. ResearchNote
   字段包括：

* topic
* query
* source_title
* source_url
* source_type
* credibility_score
* extracted_facts
* writing_implications
* contradictions
* created_at

4. StoryBible
   字段包括：

* world_summary
* rules
* factions
* characters
* timeline
* locations
* unresolved_threads
* foreshadowing_items
* resolved_threads
* canon_events

5. CharacterProfile
   字段包括：

* name
* role
* age
* background
* motivation
* desire
* fear
* secret
* relationship_map
* speech_style
* arc_stage
* constraints

6. PlotPlan
   字段包括：

* current_arc
* arc_goal
* conflict
* stakes
* turning_points
* climax_options
* foreshadowing_to_plant
* foreshadowing_to_payoff
* next_chapter_options

第三阶段：实现核心 Agent
请实现以下 Agent 的基础能力，先使用 MockLLMProvider 返回结构化假数据，保证工程可运行：

1. StyleAnalyzer
   输入：一段或多段作者已有文本
   输出：StyleProfile
   能力：

* 分析叙事视角
* 分析句长、段落长度、对白比例
* 提取常见表达习惯
* 提取节奏和情绪风格
* 生成“续写约束”

2. ResearchAgent
   输入：小说类型、时代背景、关键词、当前剧情需求
   输出：ResearchNote 列表
   能力：

* 自动生成搜索 query
* 调用 SearchProvider
* 整理事实
* 判断资料与写作的关系
* 生成“写作可用素材”
* 标注不确定性

3. StoryBibleService
   能力：

* 创建 Story Bible
* 更新人物、地点、势力、规则、时间线
* 记录伏笔
* 记录未回收悬念
* 回收伏笔后更新状态

4. PlotPlanner
   输入：StoryBible、当前章节摘要、作者目标
   输出：PlotPlan
   能力：

* 给出 3 个下一阶段走向
* 每个走向包含冲突、爽点、风险、需要铺垫的伏笔
* 提醒可能违反设定的地方

5. SceneWriter
   输入：StyleProfile、StoryBible、PlotPlan、ResearchNote、场景目标
   输出：章节草稿
   能力：

* 按指定文风生成原创章节草稿
* 保持人物设定一致
* 使用研究资料中的事实细节
* 避免硬伤
* 输出“正文”和“创作说明”

6. ContinuityChecker
   输入：章节草稿、StoryBible
   输出：问题列表
   能力：

* 检查人物动机是否冲突
* 检查时间线是否冲突
* 检查设定是否冲突
* 检查伏笔是否被遗忘
* 给出修改建议

7. FactChecker
   输入：章节草稿、ResearchNote
   输出：事实风险列表
   能力：

* 检查历史、风俗、地理、职业、娱乐行业等常识风险
* 标注确定、可能有问题、不确定
* 给出需要二次搜索的主题

第四阶段：实现 CLI
请实现以下命令：

novel-harness init PROJECT_NAME --genre 历史 --sub-genre 西汉
novel-harness ingest-style PROJECT_ID path/to/sample.txt
novel-harness research PROJECT_ID "西汉长安社会风俗"
novel-harness bible show PROJECT_ID
novel-harness bible add-character PROJECT_ID character.json
novel-harness plan PROJECT_ID --current "当前剧情摘要"
novel-harness write PROJECT_ID --goal "写下一章，主角第一次进入长安"
novel-harness check PROJECT_ID path/to/chapter.md

第五阶段：实现 API
用 FastAPI 暴露基础接口：

* POST /projects
* POST /projects/{id}/style/analyze
* POST /projects/{id}/research
* GET /projects/{id}/bible
* POST /projects/{id}/plot/plan
* POST /projects/{id}/write
* POST /projects/{id}/check

第六阶段：实现提示词文件
请为每个 Agent 创建 prompts/*.md，要求：

* 每个提示词明确输入、输出、约束
* 输出尽量为 JSON
* 所有事实性内容必须要求模型标注来源或不确定性
* 续写时必须尊重 Story Bible
* 不得编造真实世界新闻、历史事实、法律、医学、职业流程等事实
* 如果资料不足，必须输出“需要进一步研究”的主题
* 文风提取只能总结风格特征，不能要求模型复制某个作者的具体段落

第七阶段：测试
请写 pytest 测试，至少覆盖：

* StyleAnalyzer 能返回 StyleProfile
* ResearchAgent 能返回 ResearchNote
* StoryBible 能添加人物和伏笔
* PlotPlanner 能返回多个剧情走向
* ContinuityChecker 能发现简单设定冲突

第八阶段：文档
README.md 需要包含：

* 项目定位
* 安装方式
* CLI 使用示例
* API 使用示例
* 如何接入真实 LLM Provider
* 如何接入真实 Search Provider
* 如何扩展新的 Agent
* 安全与版权说明

请先输出你的实现计划，然后开始创建文件。每完成一个阶段，请运行测试或至少运行基础 CLI 命令验证工程可用。

