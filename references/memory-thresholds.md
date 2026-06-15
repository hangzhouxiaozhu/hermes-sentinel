# 内存阈值配置

本文件定义 Hermes Guardian 硬件监控的分级阈值。
可根据实际硬件配置（8GB/16GB/32GB/64GB）调整参数。

## 当前配置 (Apple M4, 16GB 统一内存)

```yaml
memory:
  total_gb: 16
  warn_pct: 70      # 内存使用 > 70% → 预警
  danger_pct: 85    # 内存使用 > 85% → 危险（强制压缩）

swap:
  total_mb: 3072
  warn_pct: 30      # Swap 使用 > 30% → 预警
  danger_pct: 60    # Swap 使用 > 60% → 危险

cpu:
  cores: 10
  load_warn: 5.0    # 1min 负载 > 5.0 → 预警

disk:
  warn_pct: 90      # 磁盘使用 > 90% → 预警

guard:
  check_interval: 600    # 巡检间隔 (秒, 默认600=10分钟)
  log_retention: 30      # 日志保留天数
  emergency_save_dir: ~/.hermes/cache/guardian/
```

## 其他配置参考

### 8GB 机型
```yaml
memory:
  total_gb: 8
  warn_pct: 65
  danger_pct: 80
cpu:
  load_warn: 3.0
```

### 32GB 机型
```yaml
memory:
  total_gb: 32
  warn_pct: 75
  danger_pct: 88
cpu:
  load_warn: 8.0
```
