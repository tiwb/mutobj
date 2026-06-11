# Benchmarks

`AttributeDescriptor` 性能基准测试，基于 [pyperf](https://pyperf.readthedocs.io/)。

## 快速上手

```bash
# 保存基线
python benchmarks/bench_descriptor.py -o baseline.json --fast --quiet

# 修改代码后，跑新数据
python benchmarks/bench_descriptor.py -o v2.json --fast --quiet

# 对比
python -m pyperf compare_to baseline.json v2.json --table
```

`--fast` 减少校准轮次，适合开发迭代；正式提交前去掉可获更精确数据。
`--quiet` 隐藏稳定性警告（纳秒级 benchmark 在 Windows 上固有抖动）。

## 场景覆盖

| 名称 | 说明 |
|------|------|
| `baseline: dict get (hit)` | 直接 dict 取值，理论上限 |
| `baseline: dict get (miss→default)` | dict.get 兜底值 |
| `baseline: dict set` | 直接 dict 赋值 |
| `desc: get (hit)` | 已赋值字段，storage 命中 |
| `desc: get (default)` | 未赋值字段，走默认值分支 |
| `desc: impl getter` | 有 @impl 自定义 getter |
| `desc: set` | 字段赋值，走 storage |
| `desc: impl setter` | 有 @impl 自定义 setter |
