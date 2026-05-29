---
known_issues: []
last_updated: '2026-05-29'
module: knowledge/ai/agent-frameworks
owners: []
recent_prs: []
slack_threads: []
tags: []
---



## Overview
Agent 框架是在大语言模型（LLM）之上构建的完整认知循环框架，实现 AI 智能体的感知、推理、行动和观察闭环。它解决了 LLM 从简单文本补全向复杂任务执行演进的核心挑战，赋予系统思考、记忆、工具调用与状态管理等生产级能力。

## Key Concepts
- **认知循环**：感知（输入）→ 推理（分析）→ 行动（执行）→ 观察（结果反馈）的迭代交互模式
- **核心抽象组件**：
  - `Chain`：多步骤串联执行的流水线
  - `AgentExecutor`：循环调用 LLM 与工具直至任务完成的控制器
  - `Tool`：LLM 可调用的外部能力或 API 接口
  - `Memory`：维持多轮交互上下文的记忆模块
  - `Retriever`：从外部数据源检索信息的检索器
- **代际演进路径**：
  - 第一代（LangChain）：低门槛标准化，普及 ReAct 模式
  - 第二代（LangGraph）：显式状态管理、条件分支、持久化与故障恢复，面向生产环境
  - 第三代（DeepAgents）：子 Agent 委派、自动规划、上下文自适应与自治协作

## Key Insights
- **状态管理是生产落地的分水岭**：从隐式线性执行转向显式状态、持久化存储与人工审批/恢复机制，是 Agent 从 Demo 走向稳定生产的核心前提。
- **架构演进指向高度自治**：框架正从“人工硬编码流程”向“智能体自我规划、动态委派与协作”演进，显著降低复杂长程任务的管理成本。
- **标准化接口加速生态繁荣**：统一的 Prompt 执行范式与工具调用协议大幅降低开发门槛，使 LLM 应用能快速迭代并复用社区组件。

## Sources
- [Agent 框架演化三部曲：从 LangChain 到 LangGraph 再到 DeepAgents](../raw/articles/agent-framework-evolution.md)

## Related Topics
- 大语言模型（LLM）应用架构设计
- ReAct 模式与思维链（Chain of Thought）
- 智能体记忆机制（工作记忆/长期记忆/向量检索）
- 工具调用与函数调用（Function Calling）
- 生产级 AI 系统可观测性与评估体系