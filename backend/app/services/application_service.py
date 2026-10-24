"""Сервисная логика для работы с заявками клиента."""
import datetime

from app.api.schemas.applications import ApplicationResponse
from app.enums import ApplicationStatus, ErrorCode, NextAction
from app.errors import ApiError
from app.models.tables import Application, Company, Decision, Product

STATUS_DETAILS: dict[ApplicationStatus, tuple[str, str]] = {
    ApplicationStatus.DRAFT: ("Черновик", "Заполните заявку и отправьте на рассмотрение"),
    ApplicationStatus.SUBMITTED: ("Принята", "Мы получили заявку и скоро начнём проверку"),
    ApplicationStatus.DATA_CHECK: ("Проверка полноты и корректности", "Проверяем данные и документы"),
    ApplicationStatus.NEEDS_INFO: ("Нужны уточнения", "Нам не хватает информации: ответьте на вопросы ниже"),
    ApplicationStatus.ENRICHMENT: ("Запрос данных из БКИ и госреестров", "Сверяем сведения о компании"),
    ApplicationStatus.SCORING: ("Оценка риска и решение", "Оцениваем заявку"),
    ApplicationStatus.MANUAL_REVIEW: ("Разбор оператором", "Заявку рассматривает специалист банка"),
    ApplicationStatus.OFFER: ("Предложение на запрошенных условиях", "Банк одобрил заявку, посмотрите условия"),
    ApplicationStatus.COUNTER_OFFER: ("Предложение других условий", "Банк готов предложить другие условия"),
    ApplicationStatus.ACCEPTED: ("Клиент принял", "Условия приняты, готовим документы"),
    ApplicationStatus.SIGNING: ("Подписание (имитация)", "Подпишите документы"),
    ApplicationStatus.DISBURSED: ("Выдача (имитация)", "Средства выданы (демо)"),
    ApplicationStatus.REJECTED: ("Отказ", "Банк не может одобрить заявку"),
    ApplicationStatus.CANCELLED: ("Отмена клиентом", "Заявка отменена"),
    ApplicationStatus.EXPIRED: ("Истёк срок действия", "Срок действия заявки/оффера истёк"),
}

NEXT_ACTIONS: dict[ApplicationStatus, NextAction] = {
    ApplicationStatus.DRAFT: NextAction.FILL_DRAFT,
    ApplicationStatus.NEEDS_INFO: NextAction.ANSWER_INFO_REQUEST,
    ApplicationStatus.OFFER: NextAction.REVIEW_OFFER,
    ApplicationStatus.COUNTER_OFFER: NextAction.REVIEW_OFFER,
    ApplicationStatus.SIGNING: NextAction.SIGN,
}

REASON_MESSAGES: dict[str, str] = {
    "REGISTRY_NOT_ACTIVE": "Статус компании в реестре не является активным",
    "BKI_OVERDUE_90": "Действующая просрочка по кредитной истории более 90 дней",
    "NEGATIVE_REVENUE": "Недостаточные показатели выручки за последние 12 месяцев",
    "AGE_TOO_LOW": "Возраст бизнеса меньше минимально допустимого",
    "LOW_SCORE": "Совокупная оценка заявки ниже требуемой",
    "INSUFFICIENT_CAPACITY": "Платёжеспособность не позволяет одобрить минимальную сумму продукта",
    "DOCUMENT_MISSING": "Необходимо приложить недостающий документ",
    "REGISTRY_MISMATCH": "Сведения в заявке отличаются от данных реестра",
    "AMOUNT_REDUCED": "Банк готов предложить меньшую сумму кредита",
    "SOURCE_UNAVAILABLE": "Не удалось получить внешние данные проверки, заявку проверит специалист",
    "INVALID_INN": "ИНН указан неверно, проверьте номер",
    "PRODUCT_NOT_AVAILABLE": "Этот продукт недоступен для вашей компании (минимальный возраст бизнеса 12 мес)",
    "INFO_ROUNDS_EXCEEDED": "Превышен лимит раундов уточнений, заявку проверит специалист банка",
    "PIPELINE_ERROR": "Произошла ошибка автоматической обработки, заявка передана специалисту",
    "CLIENT_CANCELLED": "Заявка отменена клиентом",
    "OFFER_DECLINED": "Клиент отказался от предложенных условий",
}



def build_application_response(
    application: Application,
    company: Company | None,
    latest_decision: Decision | None = None,
) -> ApplicationResponse:
    """Формирует DTO полной карточки заявки с текстами и действиями."""
    status_enum = ApplicationStatus(application.status)
    title, desc = STATUS_DETAILS.get(
        status_enum,
        ("Заявка в обработке", "Статус заявки обновляется"),
    )
    next_action = NEXT_ACTIONS.get(status_enum, NextAction.NONE)

    reason_codes: list[str] = []
    reason_messages: list[str] = []

    if latest_decision is not None and latest_decision.reason_codes:
        reason_codes = list(latest_decision.reason_codes)
        reason_messages = [REASON_MESSAGES.get(code, code) for code in reason_codes]

    company_name = company.name if company is not None else ""

    return ApplicationResponse(
        id=application.id,
        company_name=company_name,
        status=status_enum,
        product_code=application.product_code,
        amount_rub=application.amount_rub,
        term_months=application.term_months,
        purpose=application.purpose,
        revenue_12m_rub=application.revenue_12m_rub,
        net_profit_12m_rub=application.net_profit_12m_rub,
        existing_monthly_payments_rub=application.existing_monthly_payments_rub,
        status_title=title,
        status_description=desc,
        next_action=next_action,
        reason_codes=reason_codes,
        reason_messages=reason_messages,
        expires_at=application.expires_at,
        submitted_at=application.submitted_at,
        updated_at=application.updated_at,
        version=application.version,
    )


def validate_application_for_submit(
    application: Application,
    company: Company | None,
    product: Product,
) -> None:
    """Проверяет полноту заявки и соответствие диапазонам продукта перед подачей (SUBMIT).

    При неполных данных выбрасывает 422 VALIDATION_ERROR со списком полей в details.
    """
    details: list[dict[str, str]] = []

    if company is None:
        details.append({"field": "company", "message": "Профиль компании не найден"})

    if application.amount_rub is None or application.amount_rub <= 0:
        details.append({"field": "amount_rub", "message": "Укажите запрашиваемую сумму"})
    elif not (product.min_amount_rub <= application.amount_rub <= product.max_amount_rub):
        details.append(
            {
                "field": "amount_rub",
                "message": f"Сумма должна быть от {product.min_amount_rub:,} до {product.max_amount_rub:,} ₽",
            }
        )

    if application.term_months is None or application.term_months <= 0:
        details.append({"field": "term_months", "message": "Укажите срок кредитования"})
    elif not (product.min_term_months <= application.term_months <= product.max_term_months):
        details.append(
            {
                "field": "term_months",
                "message": f"Срок должен быть от {product.min_term_months} до {product.max_term_months} мес.",
            }
        )

    if application.revenue_12m_rub is None:
        details.append({"field": "revenue_12m_rub", "message": "Укажите годовую выручку"})
    elif application.revenue_12m_rub <= 0:
        details.append({"field": "revenue_12m_rub", "message": "Годовая выручка должна быть положительной"})

    if application.net_profit_12m_rub is None:
        details.append({"field": "net_profit_12m_rub", "message": "Укажите чистую прибыль за 12 месяцев"})

    if application.existing_monthly_payments_rub is None:
        details.append({"field": "existing_monthly_payments_rub", "message": "Укажите текущие платежи по кредитам"})
    elif application.existing_monthly_payments_rub < 0:
        details.append(
            {"field": "existing_monthly_payments_rub", "message": "Текущие платежи не могут быть отрицательными"}
        )

    # Проверка минимального возраста бизнеса
    if product.min_business_age_months > 0 and company is not None and company.registration_date is not None:
        today = datetime.date.today()
        reg = company.registration_date
        age_months = (today.year - reg.year) * 12 + (today.month - reg.month)
        if age_months < product.min_business_age_months:
            details.append(
                {
                    "field": "product_code",
                    "message": (
                        f"Продукт '{product.code}' доступен при возрасте бизнеса от "
                        f"{product.min_business_age_months} мес. (текущий: {age_months} мес.)"
                    ),
                }
            )

    if details:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="Заявка неполна или параметры вне допустимых диапазонов продукта",
            details=details,
        )
