---
known_issues: []
last_updated: '2026-06-02'
module: knowledge/llm/multi-agent-systems
owners: []
recent_prs: []
slack_threads: []
tags: []
---

## Overview
TradingAgents is an open-source multi-agent framework that uses Large Language Models (LLMs) to simulate the entire decision-making process of a real financial trading company, including analysis, debate among researchers, and risk control. It moves beyond simple AI stock pickers by modeling complex, collaborative professional workflows.

## Key Concepts
*   **Multi-Agent Simulation:** Simulates roles like fundamental analysts, technical analysts, and sentiment analysts collaborating and debating to reach a conclusion.
*   **Tool Calling (LangGraph):** Agents utilize external tools (e.g., fetching Yahoo Finance data, calculating technical indicators) orchestrated by LangGraph's ToolNode mechanism.
*   **Adversarial Debate:** Research agents are prompted to take opposing stances (bull vs. bear), forcing the system to avoid single-point bias and generate more robust analysis.
*   **Dual LLM Configuration:** Uses different model sizes/capabilities for different tasks (e.g., strong models for deep reasoning, lightweight models for fast tool execution) to balance quality and cost.
*   **Persistent Memory & Reflection:** The framework saves decision logs and incorporates real-time outcome feedback, allowing the LLMs to learn from past decisions and refine future reasoning (long-term learning loop).
*   **State Machine (LangGraph):** The entire trading process is defined as a directed acyclic graph (DAG), where agents act as nodes passing state information between them.

## Key Insights
*   **Learning Framework:** The project provides a blueprint for constructing complex, multi-step reasoning systems using LLMs, demonstrating how to chain specialized AI roles effectively.
*   **Modularity:** The framework is designed with modularity, allowing users to easily swap Agent roles (e.g., from finance to legal review) or integrate private data sources.
*   **Value in Process:** The true value lies not in the final prediction, but in observing how AI handles complex reasoning, information synthesis, and internal conflict within a structured environment.
*   **Caution on Advice:** Users must recognize that this is a research tool, and LLMs are prone to hallucination; the output should never be treated as actual financial or investment advice.
*   **Innovation in Learning:** The integration of persistent reflection mechanisms creates a self-correcting loop essential for developing long-term, adaptive AI agents.

## Sources
*   [TradingAgents 深度讲解](../raw/articles/trading-agents-deployment-guide.md)
*   GitHub: https://github.com/TauricResearch/TradingAgents
*   论文: https://arxiv.org/abs/2412.20138
*   官方网站: https://tauricresearch.github.io/TradingAgents/

## Related Topics
*   Large Language Models (LLMs) and Agent Frameworks
*   LangGraph and State Machine Architectures
*   Multi-Agent Systems (MAS) in AI
*   Quantitative Finance and Algorithmic Trading
*   LLM Reasoning and Chain-of-Thought Prompting