# 深度登记 卫星条带覆盖与云区筛选

- 规模：中型
- 使用者与工作流：遥感影像采购数据员，读取轨道条带清单，筛选能覆盖目标纬带的可用影像。
- 核心规则：目标经度区间支持跨180度拆分；覆盖只算并集，云掩膜从有效条带扣除，重复条带不增加面积。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 条带接收 | 运行条带接收并复核证据 | `POST /api/m1`；`/work/1` | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py` |
| M2 坐标契约 | 运行坐标契约并复核证据 | `POST /api/m2`；`/work/2` | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py` |
| M3 云区剔除 | 运行云区剔除并复核证据 | `POST /api/m3`；`/work/3` | `app/modules/m3_cloud/rules.py` | `tests/test_m3.py` |
| M4 覆盖并集 | 运行覆盖并集并复核证据 | `POST /api/m4`；`/work/4` | `app/modules/m4_union/rules.py` | `tests/test_m4.py` |
| M5 缺口定位 | 运行缺口定位并复核证据 | `POST /api/m5`；`/work/5` | `app/modules/m5_gaps/rules.py` | `tests/test_m5.py` |
| M6 采购候选 | 运行采购候选并复核证据 | `POST /api/m6`；`/work/6` | `app/modules/m6_purchase/rules.py` | `tests/test_m6.py` |
| M7 交付核验 | 运行交付核验并复核证据 | `POST /api/m7`；`/work/7` | `app/modules/m7_delivery/rules.py` | `tests/test_m7.py` |
| M8 采购对账 | 按当前目录出候选，对照合同原号与付款 | `POST /api/m8`；`/work/8` | `app/modules/m8_reconciliation/rules.py`、`app/reconcile.py`、`app/ledger.py` | `tests/test_m8.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | BOM | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py::test_bom_strip` |
| TRAP-06 | 全角坐标 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_number_fullwidth` |
| TRAP-07 | 缺失坐标 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_missing_coordinate` |
| TRAP-14 | 重复场景 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_duplicate_does_not_cover_twice` |
| TRAP-19 | 质量优先 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m3_cloud/rules.py` | `tests/test_m3.py::test_quality_priority` |
| TRAP-22 | 别名等价类 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_alias_equivalence` |
| TRAP-23 | 跨日界线 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_dateline_split` |
| TRAP-25 | 版本有效性 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_newest_version_rules` |
| TRAP-30 | 目录修订并号 | 按任一旧号采购，重复买单 | 计划按当前规范号合并，合同保留原号 | `app/reconcile.py` | `tests/test_m8.py::test_revision_merges_old_numbers_into_one_plan_row` |
| TRAP-31 | 改写已签合同号 | 历史合同失去原件对应 | 合同只追加，场景号锁定，仅对账解析当前号 | `app/ledger.py` | `tests/test_m8.py::test_contract_cannot_be_rewritten` |
| TRAP-32 | 重试重复签约 | 同一批次多份合同 | 批次号为幂等键，重试只回放 | `app/ledger.py` | `tests/test_m8.py::test_retry_same_batch_adds_no_contracts` |
| TRAP-33 | 目录切换失败 | 页面落到半套数据 | 切换单事务，失败保留上一版 | `app/catalog.py` | `tests/test_m8.py::test_catalogue_switch_failure_keeps_previous_revision_active` |
| TRAP-34 | 双重旧号均签约 | 同一影像两次付款 | 对账标出重复签约与重复金额，不删改 | `app/reconcile.py` | `tests/test_m8.py::test_signed_contract_keeps_original_number_and_blocks_duplicate_purchase` |

## 对账规则

输入记录 = 采信记录 + 隔离记录 + 相同行重复。采购对账 = 当前目录计划（新增采购/已签约）+ 合同台账 + 付款台账；合同与付款按原号留档，对账按当期身份映射给出当前编号、对照状态与重复签约金额。重复表头与空行单独记数。业务合计按阶段中的守恒或差值列复核。运行清单有原文SHA256、规则版本与耗时；相同规则版本下同文重复提交复用批次。

## 已知不覆盖

部署为本地单用户工具，不连接外部上游系统。CSV单文件5MB及一万条业务记录上限；不推断未提供的未知数据。
