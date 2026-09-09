# 真实事故回归防线

| 编号 | 问题类型 | 过去为何会漏 | 当前防线 | 自动测试 |
|---|---|---|---|---|
| Incident 001 | 一对一源数据差额未发现 | 工资表内部结果被当作检查依据，未与原始排课全量比较。 | 原始排课独立计算 AA，差异阻止通过。 | `test_unexplained_one_to_one_difference_blocks_pass` |
| Incident 002 | 教师星级错误未发现 | F 列星级来自工资表，工资表在证明自己。 | 独立、带生效期的星级版本与工资表比较。 | `test_wrong_teacher_rating_is_detected` |
| Incident 003 | 档位正确但金额错误未发现 | 只看档位文本或只计算工资表已有参数。 | 权威星级 + AD + 生效期金额规则独立计算 AE。 | `test_correct_band_wrong_amount_is_detected` |
| Incident 004 | 关键格公式异常未发现 | “有结果”被误认为“公式正确”。 | 关键 AE/AF 公式区域按结构模式审计。 | `test_formula_replaced_by_manual_value_is_detected`、`test_formula_row_reference_shift_is_detected`、`test_formula_column_reference_shift_is_detected`、`test_missing_formula_is_detected` |
| Incident 005 | 同一身份待遇不同被错误统一处理 | 把 TRMT 文本直接当作免除或扣除义务课时的规则。 | 独立教师工资政策档案明确记录义务课时、是否扣除和特批。 | `test_same_trmt_identity_can_have_different_obligation_hour_policy`、`test_profile_special_approval_is_not_inferred_from_trmt_text` |

这些测试使用完全脱敏的姓名和数值。未来重构不得删除或弱化它们。
