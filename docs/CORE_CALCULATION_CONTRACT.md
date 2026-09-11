# Core Calculation Contract

`payroll_core.calculation` is a new, isolated calculation chain.  It does not
replace, import, or alter the legacy payroll/reconciliation algorithms.  A new
Run must bind the exact `CoreRules.rule_version_id` used for its calculation.
A legacy Run with no `core_rule_version_id` remains on the legacy path and must
be labelled `LEGACY_RULES_UNBOUND`; moving it to Core requires an explicit
rebind, never an implicit recalculation.

## API

```python
calculate_payroll(
    period: str,
    schedule: Iterable[ScheduleRecord | Mapping],
    rules: CoreRules | Mapping,
    ratings: Iterable[RatingAuthority | Mapping] = (),
    profiles: Iterable[CompensationProfile | Mapping] = (),
    reference_ratings: Mapping[str, int | Mapping] = {},
    teacher_contexts: Iterable[TeacherContext | Mapping] = (),
    part_time_rates: Iterable[PartTimeRateProfile | Mapping] = (),
    effective_ac: Mapping[str, Decimal] = {},
) -> PayrollResult

calculate_course(record, rules, *, effective_ac={}) -> CourseContribution
```

`calculate_course` is the one-record, evidence-carrying calculation intended
for course details and a future optional AC contribution callback in source
resolution.  Existing source-resolution behaviour stays unchanged.  A caller
can use `lambda record: calculate_course(record, rules, effective_ac=...)` and
must respect `value=None` rather than coercing it to zero.

`PayrollResult` contains `period`, `rule_version_id`, `rows`, and
`course_contributions`.  A row has `aa`, `ac`, `ad`, `ae`, `af`, and the
separate `part_time_fee`.  The UI core fields are AA/AC/AD/AE/AF, mapped from
the lower-case dataclass attribute names.  Every field is a `CalculatedValue`:

```python
CalculatedValue(value: Decimal | None, state, reason, evidence)
```

Permitted states are `DETERMINED`, `ESTIMATED`, `NEEDS_INPUT`, and
`NOT_APPLICABLE`.  `dataclasses.asdict(result)` preserves normal dataclass
structure.  `result.as_dict()` is JSON safe and serializes `Decimal` as a
string, retaining exact values.

## Rule bundle

`load_core_rules(path=None)` loads one self-contained YAML bundle, with
`CoreRules.from_dict()` and `to_dict()` supporting JSON round trips.  Validation
rejects duplicate class type rules, invalid periods, overlapping/gapped AE
tiers, and invalid coefficients.  The default seed is deliberately limited to
`2026-08` through `2026-09`, sourced from the payroll Skill plus the user's
confirmation; it does not assert a future policy.  A historical bundle can be
loaded independently by path.

All calculation parameters belong in the bundle: grade and small-group
coefficients, special class coefficients, per-lesson factor, AE tiers/star
bonuses, explicit excluded grades, and any AF default candidate.  The first AE
tier's `maximum` is the zero threshold.  Tiers use exact Decimal boundaries:
the preceding tier includes its upper bound and the next tier excludes its
equal lower bound, so 30/60 have one match without an epsilon gap.

## Calculation and uncertainty policy

- AA is one-to-one only. AC is non-one-to-one only. AD is exactly `AA + AC`.
- `1对2` uses `grade × 1.2 × lesson_hour_factor`; `1对3` uses
  `grade × 1.5 × lesson_hour_factor`.  Neither is multiplied by ordinary small
  group attendance coefficients.
- Small group uses configured attendance coefficients 1..10.  Unknown class,
  grade, attendance, or coefficient yields `NEEDS_INPUT`, never zero.
- `领航伴学` is explicitly `NOT_APPLICABLE` in this Core bundle and does not
  enter AA/AC/AD.
- An `effective_ac` value is permitted only as an explicit, already-confirmed
  AC resolution keyed by `course_record_key(record)`; it carries evidence and
  can override an otherwise fully determinable AC calculation only. It cannot
  bypass an unknown class type, grade, attendance, or headcount coefficient.
  For a `ScheduleRecord`, the key is the same provenance-anchored identity as
  `reconcile.ac_resolution.schedule_record_id`; two source coordinates remain
  independently overridable. Ambiguous duplicate keys are rejected when an
  effective override targets them.
- AE at or below the first-tier threshold is zero, as is AF.  Above it, an
  authoritative effective rating gives `DETERMINED`; a submitted
  `reference_ratings` value gives only `ESTIMATED`; no rating is
  `NEEDS_INPUT`.
- A profile rating override works only with approval facts and a complete
  effective period.  An unapproved override blocks calculation instead of
  being silently ignored.
- AF uses an explicit individual, effective-dated policy only.  It honors both
  `deduction_enabled` and the old
  `obligation_hours_deduction_enabled` input name.  A profile without source,
  complete effective dates, or the deduction switch cannot be `DETERMINED`.
  If there is no personal policy, only a bundle's explicit
  `default_policy_candidate` may yield `ESTIMATED`; Core never infers policy
  from a role name.

## Employment contexts and input integrity

`TeacherContext` derives only from an explicit personnel record:
`employment_type` is `FULL_TIME`, `PART_TIME`, or `MANAGEMENT`, and
`allow_no_teaching` is explicit.  Core never parses a role string to guess it.

Part-time teachers do not use AA/AC/AD/AE/AF.  Each active schedule record is
one lesson and uses a confirmed teacher-and-grade `PartTimeRateProfile`; an
exact grade rate wins, otherwise a literal `grade="*"` uniform rate can apply.
The output is `part_time_fee` and the five Core salary fields are
`NOT_APPLICABLE`.

A management context with `allow_no_teaching=True` can produce AA/AC/AD = 0
only when there is no teaching activity *and no unknown contribution*.  It
cannot mask malformed/unknown schedule rows.  A normal teacher supplied only
by context but without any schedule source remains `NEEDS_INPUT`, not a zero
total.  A schedule row missing a teacher or whose period differs from the
requested period is a direct error rather than a silently filtered record.
Only `已上课` is active. A configured, explicit non-teaching status is
`NOT_APPLICABLE`; an empty or unfamiliar status is `NEEDS_INPUT`. Course
evidence includes the numerical inputs, formula, and resulting contribution so
the UI can reproduce AA/AC totals from individual rows.
