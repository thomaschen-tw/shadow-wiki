---
known_issues: []
last_updated: '2026-05-29'
module: knowledge/ai/llm-development
owners: []
recent_prs: []
slack_threads: []
tags: []
---

## 概述

Agent 框架在过去三年经历了从链式构建到图编排再到自治管理的三次范式跃迁，形成了 LangChain、LangGraph 与 DeepAgents 三层递进的架构体系。这三者呈能力叠加而非替代关系，开发者可依据需求在快速原型、生产级精确控制及高层自治编排之间进行组合选型，构建适应不同复杂度场景的 Agent 解决方案。

## 关键概念

*   **代际演进与层叠架构**：LangChain（第一代，链式范式）、LangGraph（第二代，有向图）、DeepAgents（第三代，自治编排）代表不同抽象层级；DeepAgents 本质上是 LangGraph 的高层封装，天然兼容其底层能力。
*   **状态管理与执行模型**：LangChain 依赖隐式状态且仅支持线性执行；LangGraph 引入显式 TypedDict 状态、原生支持任意循环/分支及持久化检查点；DeepAgents 通过虚拟文件系统自动管理跨会话状态与上下文摘要。
*   **生产级核心特性**：LangGraph 提供 Checkpointer、Human-in-the-Loop（中断审批）、时间旅行调试等工业级能力；DeepAgents 内置子 Agent 委派机制，通过隔离上下文窗口解决主 Agent 的上下文膨胀问题。
*   **成本与效率权衡**：LangChain 和 LangGraph 具有较高的 Token 效率；DeepAgents 为换取自动化规划和构建便利性，Token 开销约为手动实现的 20 倍，体现了"便利性 vs 成本"的 Trade-off。
*   **混合实施策略**：推荐采用分层架构：应用层使用 DeepAgents 进行目标自治，编排层使用 LangGraph 处理关键工作流与人机交互，基础层复用 LangChain Core 实现 Prompt 和工具集成。

## 关键洞察

*   **选型决策逻辑**：RAG 和简单原型验证首选 LangChain；涉及敏感操作、需持久化恢复及精确流程控制的企业应用必须选择 LangGraph；针对目标开放、需自主分解任务的复杂场景且能承担高算力成本时，选用 DeepAgents。
*   **LangChain 的演进终点**：`AgentExecutor` 已正式弃用并进入维护模式（至 2026 年底），新项目应避免基于旧版 Agent 开发，直接迁移至 LangGraph 以降低技术债务。
*   **AI 生成图的范式转移**：DeepAgents 的出现标志着框架重心从"开发者设计图结构"转向"开发者定义意图"，由 AI 自动生成分解步骤和执行路径，大幅降低复杂逻辑的开发门槛。
*   **上下文治理的关键性**：子 Agent 委派机制证实了在主 Agent 中保持精简上下文的必要性，通过独立隔离子任务上下文并返回聚合结果，可有效防止长链条执行中的信息污染和性能衰退。
*   **工业成熟度现状**：截至 2026 年，LangGraph 已发布 LTS 版本并在多家科技大厂生产环境验证，确立了生产部署的标准地位；DeepAgents 则代表了向完全自治演进的下一代方向。

## 来源

*   Agent 框架演化三部曲 (`../raw/articles/agent-framework-evolution.md`)
*   Agent 框架演化对比：LangChain vs LangGraph vs DeepAgents

## 相关主题

*   knowledge/ai/multi-agent-systems
*   knowledge/ai/human-in-the-loop-design
*   knowledge/software-engineering/orchestration-patterns
*   knowledge/ai/rag-implementation-strategies
*   knowledge/ai/state-management-for-llms