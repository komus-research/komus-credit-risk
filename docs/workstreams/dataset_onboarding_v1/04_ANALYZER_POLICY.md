# `04_ANALYZER_POLICY.md`

STATUS: READY_FOR_COORDINATOR

## PURPOSE

Документ фиксирует полностью детерминированное преобразование:

```text
DatasetInspectionReport
→ DatasetPreparationAnalyzer
→ DatasetPreparationProposal
→ STOP
```

Единственный вопрос:

> По каким фиксированным правилам Analyzer преобразует уже рассчитанные factual evidence в неподтверждённые предложения о target, identifier, predictor eligibility и suspicious columns?

`DatasetPreparationAnalyzer` **не читает исходный файл и не получает `DataFrame`**.

---

## 1. POLICY IDENTITY

```text
policy_id      = "tabular-preparation-analyzer"
policy_version = "1"
```

Полная конфигурация policy получает deterministic `policy_hash`.

Изменение threshold, веса, token dictionary, sorting или tie-breaking требует новой версии policy.

---

## 2. INPUT CONTRACT

Единственный input:

```text
DatasetInspectionReport
```

Analyzer может использовать только формально объявленные factual fields.

### Per-column factual evidence

```text
column_name
column_position

physical_dtype
inferred_logical_type
logical_type_evidence

non_null_count
missing_count
missing_fraction

unique_non_null_count
unique_fraction

is_unique
is_constant
is_near_unique
is_all_missing

value_counts
representation_profile
column_warnings
```

`value_counts` обязателен для колонок:

```text
unique_non_null_count <= 50
```

Каждый элемент содержит:

```text
value
count
```

### `representation_profile`

Inspector предоставляет:

```text
observed_value_type_families
mixed_value_types

numeric_all_integral
numeric_has_fractional_values

string_all_digits
median_string_length
```

Неприменимые поля имеют `null`, а не угадываются Analyzer.

### Pairwise factual evidence

Analyzer также может потреблять:

```text
relation_blocks
```

Каждый block содержит:

```text
binary_reference_column
source_column

overlap_non_null_rows
coverage_fraction

joint_counts
source_value_counts_on_overlap
reference_value_counts_on_overlap
```

`joint_counts`:

```text
source_value
reference_value
count
```

Inspector строит relation blocks только для:

```text
binary_reference_column:
    unique_non_null_count == 2

source_column:
    2 <= unique_non_null_count <= 50
```

Inspector **не утверждает**, что binary reference является target.

Если необходимого factual field или relation block нет, соответствующее Analyzer rule не применяется.

Analyzer не имеет права обращаться за недостающими данными к `DataFrame`.

---

## 3. FACT / PROPOSAL BOUNDARY

```text
FACT:
unique_non_null_count == 2

PROPOSAL:
possible target

NOT CONFIRMED:
target
```

```text
FACT:
unique_fraction == 1.0

PROPOSAL:
possible identifier

NOT CONFIRMED:
identifier
```

То же правило относится к suspicious/leakage-like signals.

---

## 4. NAME NORMALIZATION

Порядок:

```text
Unicode NFKC
→ trim
→ CamelCase boundaries
→ letter↔digit boundaries
→ split by _, -, ., /, \, whitespace
→ casefold
→ remove empty tokens
```

Примеры:

```text
DefMark      → ["def", "mark"]
Q_B1_norm    → ["q", "b", "1", "norm"]
customer_id  → ["customer", "id"]
```

Проверяется полный token, не substring.

### Target-like tokens

```text
target
label
class
outcome
response
event
flag
mark
y
цель
метка
класс
исход
событие
флаг
```

### Identifier-like tokens

```text
id
identifier
key
uuid
guid
inn
ogrn
snils
ид
идентификатор
ключ
инн
огрн
```

Несколько совпадений одной категории дают один bonus.

Специальные exact-name rules запрещены.

---

## 5. STRUCTURAL RULES

### Constant

```text
non_null_count > 0
AND
unique_non_null_count == 1
```

### Unique

```text
non_null_count > 0
AND
unique_non_null_count == non_null_count
```

### Near-unique

```text
non_null_count >= 20
AND
unique_fraction >= 0.98
```

Предпочтительное integer comparison:

```text
unique_non_null_count * 100
>=
98 * non_null_count
```

### High-cardinality

```text
non_null_count >= 20
AND
unique_non_null_count >= 50
AND
unique_fraction >= 0.50
```

High-cardinality numeric сама по себе не является suspicious.

Для:

```text
categorical
text
unknown
```

создаётся review signal.

---

## 6. MISSINGNESS

```text
missing_fraction == 0
→ complete

0 < missing_fraction < 0.50
→ missing_values_present

0.50 <= missing_fraction < 0.90
→ high_missingness

missing_fraction >= 0.90
→ almost_empty_column
```

`is_all_missing` остаётся отдельным state.

Missingness не приводит к автоматическому удалению.

---

## 7. TARGET CANDIDATE GATE

Колонка рассматривается только если:

```text
non_null_count >= 2
AND
unique_non_null_count == 2
```

Observed target class values и counts Analyzer берёт только из:

```text
ColumnInspection.value_counts
```

Никакого row-level доступа нет.

---

## 8. TARGET SCORE

Integer score:

```text
0..1000
```

### Base

```text
binary gate → +400
```

### Name

```text
target-like token     → +300
identifier-like token → -300
```

### Missingness

Применяется один уровень:

| Condition               | Points |
| ----------------------- | -----: |
| `missing_fraction == 0` |   +150 |
| `<= 0.05`               |   +100 |
| `<= 0.20`               |    +50 |
| `> 0.20`                |     +0 |

### Class support

Из двух элементов `value_counts` вычисляется:

```text
minimum_class_count
```

| Condition | Points |
| --------- | -----: |
| `>= 5`    |   +100 |
| `>= 2`    |    +50 |
| иначе     |     +0 |

### Canonical boolean pair

Analyzer сравнивает два factual values из `value_counts` с canonical pairs:

```text
{0,1}
{False,True}
{"0","1"}
{"false","true"}
{"no","yes"}
{"n","y"}
{"нет","да"}
```

String normalization:

```text
trim + casefold
```

Совпадение:

```text
+50
```

Это правило вычисляется полностью из `value_counts`.

### Result

```text
score_points = clamp(0, 1000, sum)
```

Candidate threshold:

```text
>= 400
```

Confidence:

```text
HIGH    800–1000
MEDIUM  600–799
LOW     400–599
```

---

## 9. POSITIVE CLASS

Analyzer не выбирает positive class.

Оба factual class values из `value_counts` становятся:

```text
positive_class_candidates
```

Для каждого:

```text
score = null
confidence = UNDETERMINED
requires_confirmation = true
```

Запрещено:

```text
1 → positive
True → positive
minority → positive
semantic-looking value → positive
```

---

## 10. IDENTIFIER CANDIDATE GATE

```text
non_null_count >= 2
AND
unique_fraction >= 0.95
AND
not is_constant
AND
not is_all_missing
```

---

## 11. IDENTIFIER SCORE

### Uniqueness

Применяется один уровень:

| Condition              | Points |
| ---------------------- | -----: |
| `unique_fraction == 1` |   +350 |
| `>= 0.995`             |   +320 |
| `>= 0.98`              |   +280 |
| `>= 0.95`              |   +200 |

### Name

```text
identifier-like token → +350
```

### Missingness

| Condition | Points |
| --------- | -----: |
| `0`       |   +150 |
| `<= 0.01` |   +100 |
| `<= 0.05` |    +50 |
| иначе     |     +0 |

### Identifier-compatible representation

Используется только `representation_profile`.

Если:

```text
physical/string representation
OR
numeric_all_integral == true
OR
string_all_digits == true
```

то:

```text
+100
```

### Penalties

```text
target-like token → -250
```

```text
inferred_logical_type == datetime
→ -250
```

```text
numeric_has_fractional_values == true
→ -200
```

```text
inferred_logical_type == text
AND
median_string_length > 64
→ -200
```

Никакие эти факты Analyzer сам из row values не вычисляет.

### Result

```text
score_points = clamp(0, 1000, sum)
```

Candidate threshold:

```text
>= 450
```

Confidence:

```text
HIGH    800–1000
MEDIUM  600–799
LOW     450–599
```

---

## 12. TARGET / IDENTIFIER CONFLICT

Если одна колонка проходит оба gates:

```text
abs(target_score - identifier_score) < 150
```

то:

```text
proposed_role = REVIEW_REQUIRED
reason_code = target_identifier_role_ambiguity
```

Если:

```text
difference >= 150
```

role получает hypothesis с большим score.

Обе hypotheses остаются в candidate lists.

---

## 13. PREDICTOR ELIGIBILITY

Это proposal, а не `FeatureUsageStatus`.

Допустимые значения:

```text
ELIGIBLE_CANDIDATE
REVIEW_REQUIRED
NOT_RECOMMENDED_CANDIDATE
UNKNOWN
```

### `NOT_RECOMMENDED_CANDIDATE`

Если:

```text
is_all_missing
OR
is_constant
```

### `REVIEW_REQUIRED`

Если присутствует хотя бы одно:

```text
target candidate
identifier candidate
potential leakage-like warning
is_near_unique

high_cardinality
AND logical_type in {categorical, text, unknown}

missing_fraction >= 0.50
logical_type == unknown
representation_profile.mixed_value_types == true
logical_type == datetime
```

### `ELIGIBLE_CANDIDATE`

Если колонка не попала выше, logical type известен и suspicious signal отсутствует.

### `UNKNOWN`

Если report evidence недостаточно.

---

## 14. DTYPE / REPRESENTATION WARNINGS

### Mixed values

Источник:

```text
representation_profile.mixed_value_types
```

Если `true`:

```text
warning_code = mixed_value_types
```

### Unknown logical type

```text
warning_code = unknown_logical_type
```

### Datetime

```text
warning_code = datetime_semantics_unconfirmed
```

Analyzer не утверждает, что дата является `observation_date`.

### Numeric fractional

`numeric_has_fractional_values` используется только как identifier-related evidence.

Сам по себе fractional numeric не является warning.

---

## 15. PAIRWISE RELATION POLICY

Pairwise rules используют **только `relation_blocks`**, рассчитанные `DatasetInspector`.

Analyzer не вычисляет overlap или contingency tables из DataFrame.

Relation block является factual description совместных наблюдений, а не leakage evidence сам по себе.

---

## 16. POTENTIAL TARGET PROXY

Правило запускается только относительно target candidate:

```text
target_score >= 600
```

Нужен relation block, где:

```text
binary_reference_column == target_candidate
```

и source column также имеет:

```text
unique_non_null_count == 2
```

Из factual `joint_counts` Analyzer детерминированно рассчитывает две возможные bijections между классами.

```text
best_binary_bijection_accuracy =
max(correct_count_mapping_1,
    correct_count_mapping_2)
/
overlap_non_null_rows
```

Gate:

```text
overlap_non_null_rows >= 50
AND
coverage_fraction >= 0.80
AND
best_binary_bijection_accuracy >= 0.995
```

Результат:

```text
warning_code = potential_target_proxy
```

Evidence:

```text
related_target_candidate
overlap_non_null_rows
coverage_fraction
best_binary_bijection_accuracy
```

Допустимое объяснение:

> Колонка почти полностью соответствует значениям предполагаемого target. Требуется проверить происхождение и момент доступности колонки.

Недопустимое:

> Колонка является leakage.

---

## 17. POTENTIAL DETERMINISTIC TARGET PROXY

Используется relation block:

```text
binary_reference_column == target_candidate
```

Target candidate:

```text
target_score >= 600
```

Source column:

```text
logical_type in {categorical, boolean}
AND
2 <= unique_non_null_count <= 50
AND
unique_fraction <= 0.20
```

Из factual `joint_counts` Analyzer рассчитывает:

```text
support(source_value)
```

и:

```text
purity(source_value) =
max joint_count(source_value, reference_class)
/
support(source_value)
```

Затем:

```text
weighted_reference_purity =
sum(max joint_count для каждой source category)
/
overlap_non_null_rows
```

Gate:

```text
overlap_non_null_rows >= 50
AND
coverage_fraction >= 0.80
AND
minimum source-category support >= 5
AND
weighted_reference_purity >= 0.995
```

Из анализа исключается source column, если:

```text
is_all_missing
OR
is_constant
OR
identifier_score >= 450
OR
unique_fraction >= 0.95
```

Результат:

```text
warning_code = potential_deterministic_target_proxy
```

Это warning, а не подтверждённый leakage.

---

## 18. PROPOSED COLUMN ROLE

Порядок:

```text
1. all_missing / constant
   → EXCLUDE_CANDIDATE

2. target↔identifier conflict <150
   → REVIEW_REQUIRED

3. potential leakage-like warning
   → REVIEW_REQUIRED

4. target candidate
   → TARGET_CANDIDATE

5. identifier candidate
   → IDENTIFIER_CANDIDATE

6. known logical type
   → FEATURE_CANDIDATE

7. otherwise
   → UNKNOWN
```

`EXCLUDE_CANDIDATE` не означает физическое удаление.

---

## 19. TECHNICAL GROUPS

Группировка остаётся технической и не вводит business semantics.

Порядок:

```text
1. structural stem
2. repeated name token
3. logical type
4. fallback
```

### Structural stem

После name normalization удаляются suffix tokens:

```text
norm
normalized
scaled
std
standardized
encoded
```

Затем удаляется конечный purely numeric token.

Примеры:

```text
Q_A1_norm → q_a
Q_A2_norm → q_a

revenue_2023 → revenue
revenue_2024 → revenue
```

Минимум:

```text
2 matching columns
```

Score:

```text
900 / HIGH
```

### Repeated token

Условия:

```text
token length >= 3
appears in >=2 unassigned columns
not numeric
not stop-token
```

Stop tokens:

```text
id
identifier
key
target
label
class
flag
mark
norm
normalized
scaled
std
standardized
encoded
value
val
feature
column
data
```

Ordering:

```text
token length DESC
matching unassigned count DESC
token lexicographically ASC
```

Применение greedy.

Score:

```text
700 / MEDIUM
```

### Logical type

Для оставшихся:

```text
>=2 columns of same logical type
```

Score:

```text
500 / LOW
```

### Fallback

```text
Прочее / не определено
```

```text
UNDETERMINED
```

Одна колонка принадлежит максимум одной proposed group.

---

## 20. CONFIDENCE

```text
HIGH    >= 800
MEDIUM  600–799
LOW     candidate threshold .. 599
```

Следовательно:

```text
target LOW     = 400–599
identifier LOW = 450–599
```

`UNDETERMINED` используется, когда policy сознательно не выбирает вариант.

Confidence — heuristic compatibility score, не вероятность истинности.

---

## 21. REASON CONTRACT

Каждый важный proposal содержит:

```text
column_name
column_position

proposal_type

score_points
confidence_level

reason_codes
reasons_ru
evidence

requires_confirmation = true
```

`evidence` должно ссылаться только на поля `DatasetInspectionReport` либо на deterministic arithmetic над ними.

---

## 22. TARGET REASON CODES

```text
binary_cardinality
target_name_token
identifier_name_penalty

no_missing_values
low_missingness
moderate_missingness

class_support_at_least_5
class_support_at_least_2

canonical_boolean_pair
```

---

## 23. IDENTIFIER REASON CODES

```text
exact_unique_values
very_high_unique_fraction
near_unique_fraction
identifier_candidate_unique_fraction

identifier_name_token

no_missing_values
very_low_missingness
low_missingness

identifier_compatible_representation

target_name_penalty
datetime_penalty
fractional_numeric_penalty
long_text_penalty
```

---

## 24. SUSPICIOUS / WARNING CODES

```text
all_missing_column
constant_column
near_unique_column
high_cardinality_non_numeric

missing_values_present
high_missingness
almost_empty_column

mixed_value_types
unknown_logical_type
datetime_semantics_unconfirmed

potential_target_proxy
potential_deterministic_target_proxy

target_identifier_role_ambiguity

no_target_candidate
multiple_target_candidates
no_identifier_candidate
multiple_identifier_candidates
target_candidate_has_missing_values
insufficient_evidence
```

---

## 25. REASON ORDERING

Порядок:

```text
1. structural/cardinality
2. name evidence
3. completeness/missingness
4. class/support
5. representation/type
6. penalties/conflicts
7. warnings
```

Внутри категории используется фиксированный policy order.

Unordered containers для user-facing ordering запрещены.

---

## 26. TARGET SORTING

```text
1. score_points DESC
2. missing_count ASC
3. minimum_class_count DESC
4. normalized_name ASC
5. original_column_position ASC
```

`minimum_class_count` берётся из `value_counts`.

Top-ranked candidate остаётся proposal.

---

## 27. IDENTIFIER SORTING

```text
1. score_points DESC
2. unique_fraction DESC
3. missing_count ASC
4. normalized_name ASC
5. original_column_position ASC
```

Fraction comparison производится без округления display value.

---

## 28. POSITIVE CLASS ORDERING

Частота класса не используется для ranking.

Type order:

```text
bool
integer
float
string
datetime
other
```

Внутри:

```text
bool/integer/float → value ASC

string
→ NFKC
→ casefold
→ lexicographic ASC

datetime
→ ISO value ASC

other
→ canonical serialized value ASC
```

Этот порядок не выражает предпочтение positive class.

---

## 29. WARNING SORTING

Общий порядок:

```text
1. severity
2. column_position ASC
3. warning_code ASC
4. related_target_rank ASC
```

Severity:

```text
WARNING
INFO
```

Для pairwise warnings:

```text
1. target candidate rank ASC
2. calculated warning strength DESC
3. warning_code ASC
4. source normalized_name ASC
5. source column_position ASC
```

---

## 30. COLUMN ROLE SORTING

Всегда:

```text
column_position ASC
```

---

## 31. GROUP SORTING

```text
0 structural_prefix
1 repeated_token
2 logical_type
3 fallback
```

Затем:

```text
group_key ASC
```

Колонки внутри:

```text
column_position ASC
```

---

## 32. AMBIGUITY RULES

Analyzer обязан вернуть ambiguity/warning вместо semantic conclusion при:

| Condition                      | Required result                       |
| ------------------------------ | ------------------------------------- |
| нет target candidates          | `no_target_candidate`                 |
| >1 target candidate            | `multiple_target_candidates`          |
| target candidate имеет missing | `target_candidate_has_missing_values` |
| >1 identifier candidate        | `multiple_identifier_candidates`      |
| нет identifier candidate       | `no_identifier_candidate` INFO        |
| target/id conflict <150        | `target_identifier_role_ambiguity`    |
| positive class                 | всегда `UNDETERMINED`                 |
| near-unique                    | `REVIEW_REQUIRED`                     |
| high-card non-numeric          | `REVIEW_REQUIRED`                     |
| pairwise proxy rule            | warning, не leakage fact              |
| mixed/unknown type             | warning/review                        |
| datetime                       | semantics unconfirmed                 |
| данных недостаточно            | `insufficient_evidence`               |

Несколько candidates сохраняются полностью.

Top rank не является confirmation.

---

## 33. DETERMINISM CONTRACT

Для одинакового:

```text
DatasetInspectionReport
+
Analyzer Policy V1
```

должны совпадать:

```text
candidate membership
candidate scores
confidence levels

positive-class alternatives

predictor eligibility
column roles

warning membership
warning evidence

reason codes
reason order

pairwise-derived metrics
group membership
group order

all list ordering

policy_id
policy_version
policy_hash
```

Analyzer не использует:

```text
random
wall-clock time
LLM
external API
ML model
Streamlit state
DataFrame
source file
```

---

## 34. DATA_FINAL REFERENCE

`Data_final.xlsb` используется только как regression/reference check.

Ожидается:

```text
DefMark ∈ target_candidates
INN ∈ identifier_candidates
```

Запрещено:

```text
if column == "DefMark"
if column == "INN"
```

Не является acceptance requirement:

```text
DefMark confirmed target
INN confirmed identifier
positive_class == 1
```

Analyzer V1 вообще не делает таких подтверждений.

---

## 35. PROHIBITED HEURISTICS

Не используются:

```text
LLM
web/external knowledge

model training
SHAP
feature importance

correlation as proof of leakage
correlation as proof of causality

1 as automatic positive class
minority as automatic positive class

unique as automatic identifier

datetime as observation_date

name as confirmed business meaning

KOMUS-specific exact-column rules
```

---

## 36. STOP CONDITION

После:

```text
DatasetPreparationProposal
```

Analyzer прекращает работу.

Не создаются:

```text
DatasetPreparationSpec
DatasetContract
FeatureRegistry
EvaluationPopulation
PreparedDatasetContext

split
final test
ExperimentConfig
ExperimentRunner
model run
LLM interpretation
```

---

# FACTS

Предыдущая версия Policy действительно содержала contract mismatch: часть правил использовала информацию, которой формально не было в объявленном `DatasetInspectionReport`.

Особенно pairwise leakage-like rules невозможно вычислить только из per-column marginal statistics.

Исправленный contract добавляет factual `value_counts`, `representation_profile` и ограниченные `relation_blocks`.

Все эти данные рассчитывает `DatasetInspector`.

`DatasetPreparationAnalyzer` остаётся чистым consumer уже подготовленного factual report.

---

# DECISIONS

Pairwise rules **сохраняются**.

Они не переносятся в Analyzer как доступ к `DataFrame`.

`DatasetInspector` рассчитывает generic factual contingency evidence без знания о том, какая колонка является target.

Analyzer позднее использует эти relation blocks только относительно своих target candidates.

`safe_examples` и factual `value_counts` разделены:

```text
safe_examples
→ presentation/privacy concern

value_counts
→ internal factual evidence для low-cardinality rules
```

Архитектурная цепочка не изменилась:

```text
TabularReader
→ TabularSnapshot
→ DatasetInspector
→ DatasetInspectionReport
→ DatasetPreparationAnalyzer
→ DatasetPreparationProposal
→ STOP
```

BLOCKED/design conflict отсутствует.

---

# LIMITATIONS

Pairwise factual evidence V1 ограничено low-cardinality pairs:

```text
binary reference
+
source cardinality <= 50
```

Это сознательно не является универсальным correlation engine.

Policy не устанавливает causal, temporal или business semantics.

`potential_target_proxy` и `potential_deterministic_target_proxy` остаются только review warnings.

Representation profiles являются техническими наблюдениями и не подтверждают identifier semantics.

---

# OPEN QUESTIONS

Блокирующих вопросов перед Implementation Spec **не осталось**.

После этого исправления каждое правило Analyzer Policy V1 вычисляется только из формально объявленных полей `DatasetInspectionReport`.

`READY_FOR_COORDINATOR`
