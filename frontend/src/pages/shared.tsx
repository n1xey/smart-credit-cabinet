export const FINAL_OK = ['OFFER', 'COUNTER_OFFER', 'ACCEPTED', 'DISBURSED'];
export const FINAL_BAD = ['REJECTED', 'CANCELLED', 'EXPIRED'];
export const WAIT = ['SUBMITTED', 'DATA_CHECK', 'ENRICHMENT', 'SCORING', 'MANUAL_REVIEW', 'SIGNING', 'NEEDS_INFO', 'DRAFT'];
// Подписи берутся из контракта (STATE_MACHINE.md); на странице заявки основной текст всегда из API (status_title)
const LABEL: Record<string, string> = { DRAFT: 'Черновик', SUBMITTED: 'Принята', DATA_CHECK: 'Проверка данных', NEEDS_INFO: 'Нужны уточнения', ENRICHMENT: 'Сверка сведений', SCORING: 'Оценка', MANUAL_REVIEW: 'Разбор специалистом', OFFER: 'Есть предложение', COUNTER_OFFER: 'Другие условия', ACCEPTED: 'Условия приняты', SIGNING: 'Подписание', DISBURSED: 'Выдача (демо)', REJECTED: 'Отказ', CANCELLED: 'Отменена', EXPIRED: 'Срок истёк' };
export const StatusBadge = ({ s, title }: { s: string; title?: string }) =>
  <span className={'badge ' + (FINAL_BAD.includes(s) ? 'bad' : FINAL_OK.includes(s) ? 'ok' : 'wait')}>{title ?? LABEL[s] ?? s}</span>;
export const Hint = ({ children }: { children: React.ReactNode }) => <small className="muted" style={{ display: 'block' }}>{children}</small>;
