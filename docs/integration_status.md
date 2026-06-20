# 集成状态

本文档用于记录 E 模块对 A/B/C/D 的接入状态。各模块通过 adapter 暴露稳定 API，缺失数据时可降级为 demo 或 blocked 状态。

## 当前状态

| 模块 | 状态 | E 当前接入位置 | 说明 |
| --- | --- | --- | --- |
| A | ready/missing | `backend/app/adapters/module_a.py` | 读取 `storage/collector.jsonl`、`storage/learn.jsonl`、`storage/mail.jsonl`、`storage/jwch.jsonl` 中的任务与课表记录 |
| B | ready/missing | `backend/app/adapters/module_b.py` | 读取 `storage/material_chunks.jsonl` 中的标准化资料分块 |
| C | ready (keyword) / in_progress (vector) | `backend/app/adapters/module_c.py` | 已实现 `src/knowledge/` 知识库核心：关键词索引（jieba+TF-IDF）可用；向量索引（sentence-transformers）为可选依赖 |
| D | ready/blocked | `backend/app/adapters/module_d.py` | 已接入三阶段 LLM pipeline，提供课程问答、学习总结、作业助手；LLM 配置缺失时返回中文错误和 retryable 标志 |
| E | ready | `backend/app/main.py`、`frontend/src/App.tsx` | 提供统一 API、前端页面和“同步 -> 导出资料并构建知识库”的演示链路 |

## 成员补充格式

```text
接口名：
负责人：
当前状态：ready / mock / in_progress / blocked
调用方式：函数 / 脚本 / HTTP API / JSONL
请求示例：
响应示例：
错误响应：
E 当前 Mock 文件/路由：
验收方式：
所属页面：Dashboard / 任务中心 / 资料页 / 问答页 / 总结页 / 作业页
```

## 接入维护步骤

1. 在对应 `backend/app/adapters/module_*.py` 中接入真实函数、脚本或 HTTP API。
2. 保持 `docs/interface_contracts.md` 中的 E 层响应字段稳定。
3. 如果真实模块字段不同，只在 adapter 中转换，不让前端直接依赖内部字段。
4. 更新本文档状态。
5. 运行 `python scripts\run_harness.py`、`python scripts\verify_e2e.py` 和前端构建。
