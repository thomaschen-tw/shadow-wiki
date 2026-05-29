---
known_issues: []
last_updated: '2026-05-29'
module: knowledge/comparisons/ai-agent-frameworks
owners: []
recent_prs: []
slack_threads: []
tags: []
---

## Overview
本文对比了AI Agent框架的三代演进：LangChain、LangGraph与DeepAgents，分别对应“快速原型”、“生产级精确控制”与“高度自治编排”三种技术范式。三者并非相互替代，而是呈层叠互补关系，共同构成从基础LLM组件调用到复杂工作流调度，再到全自动任务规划的完整技术栈。

## Key Concepts
- **范式跃迁路径**：从LangChain的线性链式调用（Chain），演进至LangGraph的显式有向图编排（Graph），最终发展为DeepAgents的自动任务分解与动态路由（Autonomous）。
- **状态管理机制**：由隐式内存（Scratchpad）→ 显式类型安全对象（TypedDict）→ 虚拟文件系统与自动摘要的完全托管模式。
- **生产级特性分层**：LangChain提供标准化Prompt/Tool接口；LangGraph内置人工介入（HITL）、Checkpointer持久化与时间旅行调试；DeepAgents内置`write_todos`自动规划与子Agent隔离委派。
- **效能权衡模型**：自动化程度提升带来开发效率飞跃，但代价显著，DeepAgents的Token消耗通常约为底层LangGraph的20倍。

## Key Insights
- **精准选型指南**：验证想法或标准RAG选LangChain；需严格合规、状态回溯与企业级部署选LangGraph；面向开放目标且预算充足的自治任务选DeepAgents。
- **推荐混合架构**：采用“应用层DeepAgents（高层自治）+ 编排层LangGraph（关键审批/流控）+ 基础层LangChain Core（组件底座）”的分层策略，可实现灵活性与稳定性的最优解。
- **破解上下文膨胀**：DeepAgents通过子Agent独立上下文窗口与结果精简返回机制，有效避免主Agent被冗余中间输出污染，是长程复杂任务的核心解法。
- **生态演进趋势**：官方已明确将传统`AgentExecutor`纳入维护模式，新项目应优先基于LangGraph构建，并根据复杂度向上封装至DeepAgents。

## Sources
- [Agent 框架演化三部曲](../raw/articles/agent-framework-evolution.md)

## Related Topics
- 人机协同（Human-in-the-Loop）AI工作流设计
- RAG 架构优化与检索增强生成策略
- 多智能体系统（Multi-Agent Systems）协作协议
- LLM 上下文窗口压缩与记忆持久化技术
- AI 应用可观测性监控与生产环境治理