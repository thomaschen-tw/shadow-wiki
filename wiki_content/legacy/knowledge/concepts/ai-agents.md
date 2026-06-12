---
known_issues: []
last_updated: '2026-05-29'
module: knowledge/concepts/ai-agents
owners: []
recent_prs: []
slack_threads: []
tags: []
---



## Overview
Agent 框架是在大语言模型（LLM）之上构建的完整认知循环系统，旨在将 AI 能力从简单的文本补全扩展至复杂任务执行。它通过实现"感知-推理-行动-观察"的闭环，赋予智能体思考、记忆、工具调用及状态管理等核心能力，推动 AI 应用向自主化与生产级演进。

## Key Concepts
*   **认知循环**：感知（输入）→ 推理（分析）→ 行动（执行）→ 观察（结果反馈）的闭环机制。
*   **核心抽象**：
    *   **Chain**：将多个步骤串联执行（类比工厂流水线）。
    *   **AgentExecutor**：循环调用 LLM 与工具直至任务完成。
    *   **Tool**：LLM 可调用的外部能力接口。
    *   **Memory**：多轮对话间的上下文保持。
    *   **Retriever**：从外部数据源检索信息。
*   **代际演进**：
    *   *第一代*：LangChain，标准化链式调用与 ReAct 模式，低门槛但状态隐式。
    *   *第二代*：LangGraph，引入显式状态、持久化及生产级控制。
    *   *第三代*：DeepAgents，实现自治规划、子 Agent 委派与自我管理。
*   **ReAct 模式**：结合推理（Reasoning）与行动（Acting）的基础执行范式。

## Key Insights
*   **生产级成熟度**：显式状态管理、持久化存储、故障恢复及人工审批是 Agent 从 Demo 走向生产环境的关键门槛。
*   **自治化趋势**：框架正从被动执行向"Agent 自我管理"演进，具备子任务委派、自动规划及上下文自适应能力。
*   **架构灵活性**：突破线性执行限制，支持条件分支与循环结构，以适应复杂任务逻辑。
*   **能力边界扩展**：通过 Tool 与 Retriever 集成，LLM 能够实时交互外部世界，突破模型内部知识局限。

## Sources
*   [Agent 框架演化三部曲：从 LangChain 到 LangGraph 再到 DeepAgents](../raw/articles/agent-framework-evolution.md)

## Related Topics
*   大语言模型（LLM）
*   ReAct 模式
*   多智能体系统（Multi-Agent Systems）
*   智能体记忆与上下文管理
*   工具调用（Function Calling）
*   LangChain 与 LangGraph 生态