# Модель данных (черновик; финализирует Участник 2)

```mermaid
erDiagram
    users ||--o{ companies : owns
    companies ||--o{ applications : has
    users ||--o{ applications : creates
    applications ||--o{ application_status_history : logs
    applications ||--o{ documents : has
    applications ||--o{ enrichment_results : has
    applications ||--o| scoring_results : has
    applications ||--o{ decisions : has
    applications ||--o{ offers : has
    applications ||--o{ info_requests : has
    applications ||--o{ jobs : triggers
    products ||--o{ applications : chosen

    users { uuid id PK
      text email UK
      text password_hash
      text role "CLIENT|OPERATOR|ADMIN"
      timestamptz created_at }
    companies { uuid id PK
      uuid owner_id FK
      text inn UK
      text name
      text legal_form "OOO|IP"
      date registration_date
      text okved
      text address
      timestamptz created_at }
    products { text code PK
      text name
      int min_amount_rub
      int max_amount_rub
      int min_term_months
      int max_term_months
      numeric base_rate_percent
      int auto_limit_rub
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
      text idempotency_key UK
      text assigned_operator_id
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
      timestamptz created_at }
    decisions { uuid id PK
      uuid application_id FK
      text outcome
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
      timestamptz valid_until
      text state "ACTIVE|ACCEPTED|DECLINED|EXPIRED" }
    info_requests { uuid id PK
      uuid application_id FK
      jsonb items "что именно запрошено"
      jsonb response
      text requested_by
      timestamptz created_at
      timestamptz answered_at }
    jobs { uuid id PK
      uuid application_id FK
      text type
      text state "PENDING|RUNNING|DONE|FAILED"
      int attempts
      timestamptz run_after
      text last_error }
```

## Принципы
- Статус хранится в `applications.status`, история — в `application_status_history` (запись в одной транзакции с изменением).
- `applications.version` увеличивается при каждом изменении, обновления идут с проверкой версии.
- `idempotency_key` + уникальный индекс: повторная подача заявки не создаёт дубль.
- Данные скоринга и решения не перезаписываются, а добавляются (аудит: что и на каких данных было решено).
- Документы: файл в томе `uploads/`, в БД только метаданные и `sha256`.
- Персональные и чувствительные поля не попадают в логи.
