# Модель данных (v0.2; владелец Участник 2)

```mermaid
erDiagram
    users ||--o| companies : owns
    companies ||--o{ applications : has
    users ||--o{ applications : creates
    applications ||--o{ application_status_history : logs
    applications ||--o{ documents : has
    applications ||--o{ enrichment_results : has
    applications ||--o{ scoring_results : has
    applications ||--o{ decisions : has
    applications ||--o{ offers : has
    applications ||--o{ info_requests : has
    applications ||--o{ jobs : triggers
    products ||--o{ applications : chosen

    users { uuid id PK
      text email UK
      text full_name
      text password_hash
      text role "CLIENT|OPERATOR|ADMIN"
      timestamptz created_at }
    companies { uuid id PK
      uuid owner_id FK,UK "1 компания на пользователя в MVP"
      text inn UK
      text name
      text legal_form "OOO|IP"
      date registration_date
      text okved
      text address
      timestamptz created_at }
    products { text code PK
      text name
      text description
      int min_amount_rub
      int max_amount_rub
      int min_term_months
      int max_term_months
      numeric base_rate_percent
      int auto_limit_rub
      int min_business_age_months "0 если нет ограничения; EXPRESS = 12"
      jsonb required_documents }
    applications { uuid id PK
      uuid company_id FK
      uuid created_by FK
      text product_code FK
      int amount_rub
      int term_months
      text purpose
      bigint revenue_12m_rub
      bigint net_profit_12m_rub
      bigint existing_monthly_payments_rub
      text status
      int version "оптимистичная блокировка"
      text idempotency_key UK "уникален глобально; тот же ключ на другой заявке = 409 IDEMPOTENCY_CONFLICT"
      uuid assigned_operator_id FK
      int info_rounds "сколько раз уходила в NEEDS_INFO"
      timestamptz submitted_at
      timestamptz expires_at
      timestamptz created_at
      timestamptz updated_at }
    application_status_history { uuid id PK
      uuid application_id FK
      text from_status
      text to_status
      text actor_type "CLIENT|OPERATOR|SYSTEM"
      text actor_id
      text reason_code
      text comment
      timestamptz created_at }
    documents { uuid id PK
      uuid application_id FK
      text doc_type
      text filename
      text storage_path
      int size_bytes
      text sha256
      text mime_type
      timestamptz uploaded_at }
    enrichment_results { uuid id PK
      uuid application_id FK
      text source "BKI|EGRUL"
      jsonb payload
      text status "OK|FAILED"
      int attempts
      timestamptz fetched_at }
    scoring_results { uuid id PK
      uuid application_id FK
      int score
      text grade
      jsonb factors
      jsonb knockouts
      text model_version
      timestamptz created_at "берётся последняя запись" }
    decisions { uuid id PK
      uuid application_id FK
      text outcome "OFFER|COUNTER_OFFER|MANUAL_REVIEW|NEEDS_INFO|REJECTED"
      text decided_by "SYSTEM|OPERATOR"
      text decided_by_id
      jsonb reason_codes
      text comment
      timestamptz created_at }
    offers { uuid id PK
      uuid application_id FK
      text kind "ORIGINAL|COUNTER"
      int amount_rub
      int term_months
      numeric rate_percent
      int monthly_payment_rub
      text explanation
      timestamptz valid_until
      text state "ACTIVE|ACCEPTED|DECLINED|EXPIRED"
      timestamptz created_at }
    info_requests { uuid id PK
      uuid application_id FK
      int round "номер раунда, с 1"
      jsonb items "что именно запрошено"
      jsonb response
      text requested_by
      timestamptz created_at
      timestamptz answered_at }
    jobs { uuid id PK
      uuid application_id FK
      text type "data_check|enrichment|scoring_decision|prepare_documents"
      text step_key "идемпотентность: например version заявки"
      jsonb payload
      text state "PENDING|RUNNING|DONE|FAILED"
      int attempts
      timestamptz run_after
      timestamptz locked_at
      text last_error
      timestamptz created_at
      timestamptz updated_at }
```

## Ограничения и индексы
- `applications.status` — `CHECK` по списку статусов из `STATE_MACHINE.md`; `product_code` — FK на `products`.
- `companies`: `CHECK` длины ИНН по форме (`OOO` — 10 цифр, `IP` — 12); один пользователь — одна компания (unique `owner_id`).
- `offers`: частичный unique `(application_id) WHERE state = 'ACTIVE'` — одна активная оферта на заявку.
- `jobs`: unique `(application_id, type, step_key)`; индекс `(state, run_after)` для выборки `FOR UPDATE SKIP LOCKED`.
- Индексы: `applications (status, updated_at DESC)`, `applications (company_id)`, `application_status_history (application_id, created_at)`, `enrichment_results (application_id, source)`.
- `scoring_results` и `decisions` только добавляются; актуальной считается последняя запись по `created_at`.

## Принципы
- Статус хранится в `applications.status`, история — в `application_status_history` (запись в одной транзакции с изменением).
- `applications.version` увеличивается при каждом изменении, обновления идут с проверкой версии.
- `idempotency_key` + уникальный индекс: повторная подача заявки не создаёт дубль.
- Данные скоринга и решения не перезаписываются, а добавляются (аудит: что и на каких данных было решено).
- `application_status_history.actor_id`: для `SYSTEM` — имя воркера, для остальных — id пользователя (text, без FK). Аудит `take` пишется строкой истории с `from_status = to_status = MANUAL_REVIEW` и `reason_code = TAKEN`.
- Документы: файл в томе `uploads/`, в БД только метаданные и `sha256`.
- Персональные и чувствительные поля не попадают в логи.
