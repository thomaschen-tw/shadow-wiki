---
known_issues: []
last_updated: '2026-05-29'
module: knowledge/concepts/multi-agent-systems
owners: []
recent_prs: []
slack_threads: []
tags: []
---



## Overview
多智能体系统（Multi-Agent Systems, MAS）是由多个具备自主决策、信息交互与协同作业能力的智能体组成的分布式系统架构。在人工智能演进中，它通过角色分工与并行处理，成为第三代Agent框架解决复杂任务的核心范式。

## Key Concepts
- **自主性**：各智能体拥有独立决策权，可基于局部环境或输入信息自主行动。
- **可通讯性**：支持智能体间的信息交换，依赖标准化的消息传递协议进行交互。
- **可协作性**：通过任务拆解、子任务委派与并行执行实现目标协同。
- **角色专业化**：系统内智能体承担特定职能（如分析、执行、风控、协调），形成结构化工作流。
- **分布式架构**：去中心化设计，各节点独立运行但通过协调机制保持系统一致性。

## Key Insights
- 多智能体协作显著突破单智能体的能力边界，是处理高复杂度、多步骤任务的关键路径。
- 明确的角色划分与协调员机制能有效降低系统冲突，提升任务执行的稳定性与效率。
- 该架构具有高度可迁移性，除金融交易外，可快速适配代码审查、自动化测试与CI/CD部署等研发场景。
- 智能体间的通信协议质量与任务分解逻辑直接决定整体系统的鲁棒性与可扩展性。

## Sources
- [TradingAgents 深度讲解：AI 智能体团队替你"开交易公司"](../raw/articles/trading-agents-deployment-guide.md)

## Related Topics
- 单智能体架构（Single-Agent Systems）
- 大语言模型代理（LLM-based Agents）
- 分布式人工智能（Distributed AI）
- 任务规划与分解（Task Planning & Decomposition）
- 智能体协调与共识机制（Agent Coordination & Consensus）