# PR `contract`: v0.2 (Участник 2)

Затронуты: `api/openapi.yaml` (0.1.0 → 0.2.0), `STATE_MACHINE.md`, `DATA_MODEL.md`, `SCORING.md` (только таблица кодов причин).

## Для Участника 3 (frontend)
- SSE `/applications/{id}/events` читать через `fetch` со стримом и `Authorization`; `EventSource` не использовать. Резерв: опрос с `If-None-Match`, `ETag` = `"<version>"`.
- `accept` оставляет заявку в `ACCEPTED`; через секунды воркер переводит в `SIGNING`. UI должен это переживать (поллинг/SSE).
- `PATCH /applications/{id}` частичный (`ApplicationPatch`). Неполная заявка на submit даёт 422 со списком полей в `details`.
- Списки: `limit`/`offset`, общее число в `X-Total-Count`. Новый `GET /applications/{id}/documents/{doc_id}/download`.
- Новые коды ошибок: `VERSION_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`.
- Health и `/docs` на корне, без `/api/v1`.

## Для Участника 4 (scoring / decision / integrations / compose)
- Новые коды причин: `INVALID_INN`, `PRODUCT_NOT_AVAILABLE`, `INFO_ROUNDS_EXCEEDED`, `TAKEN` (служебный).
- Формула аннуитета нужна и `decide` (PV), и расчёту `monthly_payment_rub`. Предлагаю один хелпер `annuity_payment` / `annuity_pv` в `backend/app/decision`, `services` его импортирует. Нужно согласие.
- У продукта появилось `min_business_age_months` (EXPRESS = 12): seed и конфиг продуктов обновить.
- Health-проверки compose: `/health/live`, `/health/ready` на корне.
- Env: `MAX_INFO_ROUNDS`, `JOB_LOCK_TIMEOUT_SEC`, `DOC_ALLOWED_MIME`, `DOC_MAX_SIZE_MB` — добавить в `.env.example`.

## Для Участника 1 (docs / tests)
- Границы диапазонов в скоринговой карте не заданы однозначно (например, 36 мес: «12–36» или «> 36»; 5 и 10 для покрытия выручкой). Предложение: левая граница включительно, правая исключительно, кроме явно указанных «≥». Нужно зафиксировать в `SCORING.md` и сверить с seed №3.
- Добавить e2e-сценарии: идемпотентный submit, лимит раундов уточнений, занятая заявка (`take`), чужая заявка → 404.

## Изменения по файлам (кратко)
- **STATE_MACHINE**: актор `DISBURSED` = клиент; `ACCEPTED→SIGNING` задачей `prepare_documents`; лимит раундов; правила отмены, `take`, `expires_at`, watchdog зависших задач.
- **DATA_MODEL**: `users.full_name`; companies 1:1; `scoring_results` 1:N; `products.description/min_business_age_months`; `assigned_operator_id` uuid FK; `info_rounds`; `jobs` (`step_key`, `payload`, `locked_at`, таймстемпы); `offers.explanation/created_at`; блок ограничений и индексов.
- **OpenAPI**: см. список выше + `ApplicationPatch`, пагинация и фильтры очереди, `X-Correlation-ID`, `int64` для денег, публичный `/products`.

## Ревью, раунд 2 (правки по замечаниям)
1. **Единая цепочка после оффера.** В `STATE_MACHINE.md` добавлен раздел «Цепочка после оффера» (таблица: шаг, актор, источник, статус). Остальные места (диаграмма, таблица статусов, `openapi.yaml`) ссылаются на него и не повторяют иначе. `accept` возвращает `ACCEPTED`; `ACCEPTED → SIGNING` только задачей `prepare_documents` (SYSTEM); `sign` допустим только в `SIGNING`.
2. **Ошибки на уровне ручки.** Каждая операция в `openapi.yaml` теперь перечисляет свои коды: HTTP-статус, `code` и условие («CODE — когда»). В `info.description` добавлена общая таблица кодов. Введён заголовок `If-Match` (PATCH заявки, accept, decline, решение оператора) для `VERSION_CONFLICT`. Клиентские ручки отвечают `403 FORBIDDEN` для роли не CLIENT, чужие ресурсы — `404`.
3. **`/operator/queue`.** Зафиксировано: без `status` — все статусы кроме DRAFT; сортировка по умолчанию `updated_at_desc`; пустой результат — `200`, `[]`, `X-Total-Count: 0`. Добавлены примеры ответа (одна заявка и пустой список). UI оператора по умолчанию шлёт `status=MANUAL_REVIEW`.
4. **Защита от расхождений.** В `backend/tests/test_skeleton.py` добавлены тесты: коды в описаниях ошибок соответствуют HTTP-статусу и `ErrorCode`, у всех защищённых ручек есть 401, у `{id}`-путей 404, у `/operator/*` 403.
