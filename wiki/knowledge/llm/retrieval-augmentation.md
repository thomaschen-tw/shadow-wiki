---
known_issues: []
last_updated: '2026-05-29'
module: knowledge/llm/retrieval-augmentation
owners: []
recent_prs: []
slack_threads: []
tags: []
---



## Overview
RAG（检索增强生成）与KAG（知识增强生成）是解决大语言模型知识滞后、幻觉及私有数据接入问题的两种核心架构。RAG基于向量相似度检索文本片段，而KAG依托知识图谱进行结构化查询与逻辑推理。两者在知识表示、检索机制及适用场景上各有侧重，正逐步向混合架构演进。

## Key Concepts
- **RAG（Retrieval-Augmented Generation）**：通过文本向量化与相似度匹配检索相关片段，辅助大模型生成答案。
- **KAG（Knowledge-Augmented Generation）**：基于知识图谱的实体-关系结构，通过图遍历与显式逻辑推理增强模型理解。
- **GraphRAG**：融合向量检索与图谱推理的混合架构，兼顾语义理解与结构化关系挖掘。
- **多跳推理（Multi-hop Reasoning）**：跨多个实体与关系进行链式推导的能力，KAG原生支持而RAG较弱。
- **知识表示范式**：RAG依赖非结构化向量嵌入，KAG依赖结构化三元组图谱。

## Key Insights
- **选型需权衡成本与复杂度**：RAG部署快、维护成本低，适合常规问答与文档检索；KAG构建门槛高，但擅长复杂关系挖掘与逻辑推理。
- **检索机制决定能力边界**：向量相似度匹配易受“语义相似但事实无关”干扰，图查询则提供可解释、高精确度的推理路径。
- **知识维护是KAG的核心挑战**：图谱的完整性与更新频率直接影响生成质量，需配套自动化抽取与治理流程。
- **融合趋势不可逆**：GraphRAG等混合方案通过“向量补语义、图谱补结构”正成为企业级知识库系统的首选方向。

## Sources
- [一文读懂 RAG 与 KAG](../raw/articles/rag-and-kag-guide.md)

## Related Topics
- 大语言模型幻觉缓解机制 (LLM Hallucination Mitigation)
- 知识图谱构建与推理 (Knowledge Graph Construction & Reasoning)
- 向量数据库与语义搜索 (Vector Databases & Semantic Search)
- 混合检索架构 (Hybrid Retrieval Architectures)
- 企业级知识库系统 (Enterprise Knowledge Base Systems)