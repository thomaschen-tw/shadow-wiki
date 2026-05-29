---
known_issues: []
last_updated: '2026-05-29'
module: knowledge/ai/rag-vs-kag
owners: []
recent_prs: []
slack_threads: []
tags: []
---



## Overview
RAG（检索增强生成）与 KAG（知识增强生成）是两种用于缓解大语言模型知识滞后、幻觉及私有数据缺失问题的架构方案。RAG 依赖向量相似度匹配检索文本片段，而 KAG 基于知识图谱的“实体-关系”结构进行图遍历与显式逻辑推理。两者在知识表示、检索机制与适用边界上各有侧重，正逐步向混合架构演进。

## Key Concepts
- **RAG（Retrieval-Augmented Generation）**：通过向量化与向量数据库进行语义相似度检索，将相关文本片段作为上下文输入大模型生成答案。
- **KAG（Knowledge-Augmented Generation）**：利用知识图谱的结构化表示，通过实体抽取、图查询与多跳推理获取关系型知识。
- **多跳推理（Multi-hop Reasoning）**：KAG 的核心能力，指沿图谱中的多步关系路径进行逻辑推导以解答复杂问题。
- **GraphRAG**：融合向量检索与图谱推理的混合范式，旨在兼顾语义泛化能力与结构化关系挖掘。

## Key Insights
- **场景适配优先**：企业 FAQ、文档问答等常规任务首选 RAG（部署快、成本低）；关系挖掘、推荐系统与复杂逻辑推理首选 KAG（原生支持多跳与显式关系）。
- **能力边界互补**：RAG 易受“语义相似但事实无关”内容干扰，缺乏复杂关系捕捉能力；KAG 推理透明可解释，但高度依赖图谱完整性且维护成本高。
- **融合是演进方向**：GraphRAG 通过图结构补充向量的语义理解，并用向量检索弥补图谱在稀疏关系上的不足，适合高复杂度混合业务场景。
- **知识工程价值凸显**：从“非结构化文本检索”转向“结构化知识推理”，标志着大模型应用正从单纯的内容拼接迈向可解释、可验证的逻辑计算。

## Sources
- [一文读懂 RAG 与 KAG](../raw/articles/rag-and-kag-guide.md)

## Related Topics
- 大语言模型幻觉抑制机制（Hallucination Mitigation）
- 知识图谱构建与动态维护（Knowledge Graph Engineering）
- 向量数据库与混合检索策略（Vector DBs & Hybrid Search）
- GraphRAG 架构与图神经网络检索（GraphRAG & GNN-based Retrieval）
- 提示工程与上下文窗口优化（Prompt Engineering & Context Window Management）