# Payroll Fourth-round UAT: August Baseline Comment Audit

Read-only source audit completed before changing comment code.

## Baseline identity

- Project UAT reference: `/Users/macos/Desktop/8月工资表/2026数学&理化组8月薪资表——基准版.xlsx`
- SHA-256: `d0cbb9c848fabf59f849c56d6075dc0090686a7d3341575f3270c51437a96196`
- The requested sibling `2026数学&理化组8月薪资表——基准版不许抄.xlsx` was not present.
- One visible sheet: `Sheet1`, 35 rows × 49 columns.
- The project UAT artifacts reference the file above as the baseline. Production template selection remains a separate Run-bound `template_path` / active company template; this baseline is not a production business-value source.
- Header rows are 3–4. `C` is teacher name. Relevant fields: `AB` class lesson count, `AC` class converted hours, `AF` total lesson fee, `AN` refund/refusal.

## Comment inventory

- 74 Excel comments/notes total.
- 70 on teacher rows, covering 29 teachers.
- Three are header notes at AH4, AI4 and AJ4; one is a group-level note at AM35.
- By column: AC 24, AN 13, I 8, F 7, J 5, AP 5, AS 3, AF 3, AH 1, AI 1, AJ 1, AB 1, H 1, AM 1.

## Business formats observed (examples redacted)

### Class lesson / converted-hour detail

The primary class explanation field is `AC` (班课折算小时数), with a single class-count explanation at `AB` (课时数). Text is free-form, commonly grouped by grade, then class size and occurrence count. There is no universal heading such as “工资项目 / 明细 / 来源”.

Observed patterns, with names and business values removed:

1. `九年级：\nN人班 M次\n高一：\nP人班 Q次`
2. `九年级班课：\nN人班 M次\n\n高二班课：\nP人班 Q次`
3. `高二：\nN人班 M次\n小升初：\nP人班 Q次`

One longer note explains a calculated class-hour total as two existing components, then states the reason an input was treated differently. That is an exception, not a standard formula note.

### Separate class-performance note

The baseline has no distinct column labeled “班课绩效” and no independently demonstrated class-performance comment format. `AF` is the combined `总课时费`; its three comments are part-time lesson-fee explanations, not a breakdown of full-time class performance. Therefore this audit does not authorize inventing an AF/class-performance annotation.

### Refund notes (`AN`)

Common format: `教师：学生 事项 人头金额/业绩金额` with a parenthetical source month such as `(退费表8月)`. Multiple items appear on separate lines; a multi-item cell may finish with `合计金额`, then the source month. Some legacy manual notes omit a source suffix, so the renderer should follow the source-backed payroll pattern without claiming every historical comment is identical.

Observed patterns, with names and amounts removed:

1. `教师：学生 续费 人头-金额\n(退费表8月)`
2. `教师：学生 新签 人头-金额\n(退费表8月)`
3. `教师：学生 续费 人头-金额业绩-金额\n      学生 续费 业绩-金额(缩单)\n      合计-金额\n(退费表8月)`

Negative values use a leading minus sign. Business type is retained. Multiple entries are separated by line breaks. The standard comments do not use technical IDs, hashes, JSON, internal states, or source row identifiers.

## Rules applied to the implementation

- Support-source comments remain verbatim and follow mapped values; AH/AI/AJ source comments remain support comments.
- No generated renewal explanation comments are added.
- Current approved refund rows remain the sole source for AN value and baseline-style AN text.
- Class explanation is rendered on AC from current Run course evidence in the observed grade/headcount/count style.
- A separate “class performance” annotation remains OPEN because the baseline provides no independent field/comment contract for it.
- This audit contains redacted format patterns only; real workbook comments and payroll values are not copied into the repository.
