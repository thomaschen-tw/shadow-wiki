# PulseWiki Operating SOP (v1.3)

本 SOP 面向企业级值班与交付团队，定义 ETL v1.3 的标准运维流程、背压治理与数据留存策略。

实现对齐基线：
- [scripts/db.py](../scripts/db.py#L226)
- [scripts/distill/worker.py](../scripts/distill/worker.py#L139)
- [scripts/resource_mgr.py](../scripts/resource_mgr.py#L296)
- [scripts/resource_mgr.py](../scripts/resource_mgr.py#L319)

## 1. 运行模式与职责边界

v1.3 的职责切分如下：
1. 启动脚本 [scripts/start_etl_stack.sh](../scripts/start_etl_stack.sh) 只负责进程拉起与日志透出。
2. 调度和背压在 resource_mgr.py etl-loop。
3. 业务处理在 worker.py 的 clean/route/distill。
4. 热表治理、归档与清理在 db.py 与 resource_mgr.py 协同执行。

禁止回退到 Bash while true 作为核心调度器。

## 2. 日常值班 Runbook

### 2.1 开班检查

```bash
uv run python scripts/resource_mgr.py status
uv run python scripts/resource_mgr.py etl-status
uv run python scripts/resource_mgr.py paths
```

验收标准：
1. Pipeline mode 为 etl。
2. Write target 为 etl。
3. Resolved dir 指向 wiki_content/etl。
4. etl-status 能正常输出 hot rows 统计。

### 2.2 启动与停机

启动：
```bash
bash scripts/start_etl_stack.sh
```

建议参数：
```bash
# 演练
uv run python scripts/resource_mgr.py etl-loop --limit 50 --base-sleep 30

# 生产
uv run python scripts/resource_mgr.py etl-loop --apply --limit 50 --base-sleep 30 --max-sleep 180 --max-inflight 8
```

停机原则：
1. 优先终止 etl-loop 进程。
2. 若做维护窗口，先停写入再做清理/回放。

## 3. 背压回路说明 (Adaptive Throttle)

实现入口：
- [scripts/resource_mgr.py](../scripts/resource_mgr.py#L319)

每轮控制信号：
1. pending = get_pending_events_count()
2. inflight = get_inflight_staging_count()
3. recent_failed = get_recent_failed_staging_count(minutes)

控制逻辑：
1. 背压闸门
- 若 inflight >= max_inflight，本轮跳过处理，仅 sleep 后重试。

2. 失败退避
- 若 recent_failed > 0，failure_streak += 1。
- 退避时间采用指数上升，受 max_sleep 上限保护。

3. 动态步长
- 高 pending 时减小休眠并收敛批量上限。
- 空队列时降低批量并提高休眠，减少无效轮询。

4. 清理内联
- 每轮调用 run_etl_once_with_cleanup(...)
- 在业务处理后执行 archive/prune 动作，避免热表无限增长。

运维解读：
- 该控制回路等价于以 inflight 为主压、recent_failed 为风险放大器、pending 为节拍调节器的自适应节流器。

## 4. Staging Retention (数据留存与清理)

### 4.1 口径与对象

热表口径：
- etl-status 仅展示 archived_at IS NULL 的记录。
- 已归档数据不参与 hot 统计。

治理对象：
- etl_staging 热表
- etl_staging_archive 归档表

### 4.2 软归档 (推荐默认)

命令：
```bash
# 预演: 查看将归档多少行
uv run python scripts/resource_mgr.py etl-archive --hours 24

# 执行: 归档并从热表移除
uv run python scripts/resource_mgr.py etl-archive --hours 24 --apply
```

说明：
1. etl-archive 是显式归档命令，等价于 archive 模式的清理调用。
2. 用于保留审计轨迹并减少热表体积。

### 4.3 硬清理

命令：
```bash
# 预演: 查看将删除多少行
uv run python scripts/resource_mgr.py etl-prune --hours 168 --mode prune

# 执行: 永久删除
uv run python scripts/resource_mgr.py etl-prune --hours 168 --mode prune --apply
```

风险提示：
1. prune 为不可逆删除。
2. 必须在审计保留策略允许的前提下执行。

### 4.4 周期建议

1. 每日: etl-archive --hours 24 --apply
2. 每周: etl-prune --hours 720 --mode prune --apply (按合规窗口调整)
3. 每次执行后: 复查 etl-status 与 SQLite 文件体积

## 5. 失败告警与排障断代指引

触发条件：
- 观察到 recent_failed > 0。
- 或循环日志出现 ETL loop degraded ...

### 5.1 第一阶段: 现场止血

1. 切换为 dry-run 以避免继续污染
```bash
uv run python scripts/resource_mgr.py etl-loop --limit 30 --base-sleep 30
```

2. 保留现场
- 导出当前错误日志。
- 记录 pending/inflight/recent_failed 快照。

### 5.2 第二阶段: 根因定位

优先检查：
1. Clean 合同失败
- 关键字: clean_validation_error
- 关注 RawEventContext 字段完整性与类型。

2. Route 合同偏差
- 关键字段: fallback_reason, rule_source, candidate_new_module。
- 判定是否为新模块候选提升路径。

3. Distill 写入失败
- 检查目标目录权限、frontmatter 格式、模型调用错误。

### 5.3 第三阶段: 标准回放

先 dry-run 回放，后 apply：
```bash
uv run python scripts/resource_mgr.py etl-replay \
  --since "2026-06-08 00:00:00" \
  --until "2026-06-08 06:00:00" \
  --limit 200

uv run python scripts/resource_mgr.py etl-replay \
  --since "2026-06-08 00:00:00" \
  --until "2026-06-08 06:00:00" \
  --apply --limit 200
```

回放验收：
1. 失败窗口内事件清零或显著下降。
2. etl-status hot rows 结构恢复稳定。
3. 目标 wiki 模块更新符合预期。

## 6. 变更管控与交付门禁

建议将以下检查设为上线前必过：
1. uv run pytest -q -m p0 --maxfail=1
2. uv run python scripts/qa/full_regression_triage.py
3. uv run python scripts/resource_mgr.py etl-status
4. 至少一次 etl-archive dry-run 输出复核

## 7. 事故后复盘模板

1. 触发时间与检测信号
2. 影响范围
- pending 峰值
- inflight 峰值
- recent_failed 峰值
3. 根因分类
- Clean 合同
- Route 合同
- Distill 写入
- 外部依赖
4. 处置动作
- 限流参数调整
- 归档/清理动作
- 回放窗口与结果
5. 预防措施
- 测试补强
- 规则补强
- 告警阈值修订

## 8. 命令速查

```bash
# 状态
uv run python scripts/resource_mgr.py status
uv run python scripts/resource_mgr.py etl-status

# 自适应循环
uv run python scripts/resource_mgr.py etl-loop --apply --limit 50 --base-sleep 30

# 软归档
uv run python scripts/resource_mgr.py etl-archive --hours 24 --apply

# 硬清理
uv run python scripts/resource_mgr.py etl-prune --hours 168 --mode prune --apply

# 窗口回放
uv run python scripts/resource_mgr.py etl-replay --since "YYYY-MM-DD HH:MM:SS" --until "YYYY-MM-DD HH:MM:SS" --apply --limit 200
```

## 9. 文档元数据

- Document Version: 2026-06-08
- Target System: PulseWiki v1.3
- Owner: Platform Engineering / Ops
- Review Cycle: Weekly
