// Встроенный мок API (VITE_API_URL=mock, `npm run demo`): показать интерфейс без бэкенда.
// Только для просмотра дизайна. Данные синтетические (docs/SCORING.md), живут в памяти вкладки и сбрасываются при перезагрузке.
// Решения ниже упрощены и НЕ являются скорингом продукта: настоящая логика в backend/app/scoring и decision.
import { payment } from './client';
type J = any;
const now = () => new Date().toISOString();
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const later = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();
const uid = () => crypto.randomUUID();

const PRODUCTS = [
  { code: 'WORKING_CAPITAL', name: 'Оборотный кредит', description: 'На закупки, зарплаты и текущие расходы', min_amount_rub: 300_000, max_amount_rub: 10_000_000, min_term_months: 3, max_term_months: 24, base_rate_percent: 18, auto_limit_rub: 3_000_000, min_business_age_months: 0, required_documents: ['FINANCIAL_STATEMENT'] },
  { code: 'EQUIPMENT', name: 'Кредит на оборудование', description: 'Покупка станков, техники и транспорта', min_amount_rub: 500_000, max_amount_rub: 15_000_000, min_term_months: 12, max_term_months: 60, base_rate_percent: 16.5, auto_limit_rub: 5_000_000, min_business_age_months: 0, required_documents: ['FINANCIAL_STATEMENT', 'SUPPLIER_INVOICE'] },
  { code: 'EXPRESS', name: 'Экспресс-кредит', description: 'Быстрое решение без документов, для бизнеса от 12 месяцев', min_amount_rub: 100_000, max_amount_rub: 1_500_000, min_term_months: 3, max_term_months: 12, base_rate_percent: 21, auto_limit_rub: 1_500_000, min_business_age_months: 12, required_documents: [] },
];
const TEXT: Record<string, [string, string]> = {
  DRAFT: ['Черновик', 'Заполните заявку и отправьте на рассмотрение'], SUBMITTED: ['Заявка принята', 'Мы получили заявку и скоро начнём проверку'],
  DATA_CHECK: ['Проверяем данные', 'Проверяем данные и документы'], NEEDS_INFO: ['Нужны уточнения', 'Нам не хватает информации: ответьте на вопросы ниже'],
  ENRICHMENT: ['Сверяем сведения', 'Сверяем сведения о компании'], SCORING: ['Оцениваем заявку', 'Оцениваем заявку'],
  MANUAL_REVIEW: ['Заявку рассматривает специалист', 'Заявку рассматривает специалист банка'], OFFER: ['Банк одобрил заявку', 'Банк одобрил заявку, посмотрите условия'],
  COUNTER_OFFER: ['Есть другие условия', 'Банк готов предложить другие условия'], ACCEPTED: ['Условия приняты', 'Условия приняты, готовим документы'],
  SIGNING: ['Подпишите документы', 'Подпишите документы'], DISBURSED: ['Средства выданы', 'Средства выданы (демо)'],
  REJECTED: ['Отказ', 'Банк не может одобрить заявку. Причины ниже'], CANCELLED: ['Заявка отменена', 'Заявка отменена'], EXPIRED: ['Срок истёк', 'Срок действия заявки/оффера истёк'],
};
const REASON: Record<string, string> = { REGISTRY_NOT_ACTIVE: 'По данным реестра, компания не ведёт деятельность', BKI_OVERDUE_90: 'Есть длительная просрочка по действующим обязательствам', AMOUNT_REDUCED: 'Мы можем предложить меньшую сумму', DOCUMENT_MISSING: 'Необходимо приложить документ' };
const NEXT: Record<string, string> = { DRAFT: 'FILL_DRAFT', NEEDS_INFO: 'ANSWER_INFO_REQUEST', OFFER: 'REVIEW_OFFER', COUNTER_OFFER: 'REVIEW_OFFER', SIGNING: 'SIGN' };

// Компании и исходы — из таблицы «Тестовые компании» (docs/SCORING.md)
const SEED: [string, string, 'OOO' | 'IP', string, string, J][] = [
  ['0000001011', 'ООО «Ромашка Логистик»', 'OOO', '62', 'OFFER', { product_code: 'WORKING_CAPITAL', amount_rub: 2_000_000, term_months: 12, revenue_12m_rub: 48_000_000, net_profit_12m_rub: 6_700_000, existing_monthly_payments_rub: 40_000, score: 95, grade: 'A' }],
  ['0000002022', 'ООО «СтройДом Юг»', 'OOO', '43', 'COUNTER_OFFER', { product_code: 'WORKING_CAPITAL', amount_rub: 8_000_000, term_months: 24, revenue_12m_rub: 30_000_000, net_profit_12m_rub: 2_400_000, existing_monthly_payments_rub: 60_000, score: 67, grade: 'B', offer: [780_000, 24, 20] }],
  ['0000003033', 'ООО «Печатный двор»', 'OOO', '18', 'NEEDS_INFO', { product_code: 'EQUIPMENT', amount_rub: 2_500_000, term_months: 36, revenue_12m_rub: 15_000_000, net_profit_12m_rub: 1_500_000, existing_monthly_payments_rub: 30_000 }],
  ['0000004044', 'ООО «Свежий хлеб»', 'OOO', '10.71', 'MANUAL_REVIEW', { product_code: 'WORKING_CAPITAL', amount_rub: 1_500_000, term_months: 12, revenue_12m_rub: 6_000_000, net_profit_12m_rub: 360_000, existing_monthly_payments_rub: 0, score: 44, grade: 'D' }],
  ['0000005055', 'ООО «Тихая Гавань»', 'OOO', '56', 'REJECTED', { product_code: 'EXPRESS', amount_rub: 500_000, term_months: 6, revenue_12m_rub: 9_000_000, net_profit_12m_rub: 400_000, existing_monthly_payments_rub: 0, knockouts: ['REGISTRY_NOT_ACTIVE'] }],
  ['0000006066', 'ООО «Вектор Сервис»', 'OOO', '47', 'REJECTED', { product_code: 'WORKING_CAPITAL', amount_rub: 1_500_000, term_months: 12, revenue_12m_rub: 20_000_000, net_profit_12m_rub: 2_000_000, existing_monthly_payments_rub: 50_000, knockouts: ['BKI_OVERDUE_90'] }],
  ['000000070777', 'ИП Соколов А.', 'IP', '56', 'OFFER', { product_code: 'EXPRESS', amount_rub: 400_000, term_months: 6, revenue_12m_rub: 5_000_000, net_profit_12m_rub: 2_000_000, existing_monthly_payments_rub: 0, score: 91, grade: 'A' }],
];
const companies = new Map<string, J>(); // email -> компания
const apps: J[] = [];
const rate = (code: string) => PRODUCTS.find(p => p.code === code)!.base_rate_percent;
function factors(a: J) {
  return [['Возраст бизнеса', '4 года', 10, 15], ['Покрытие запроса выручкой', (a.revenue_12m_rub / a.amount_rub).toFixed(1), 15, 20], ['Рентабельность', Math.round(a.net_profit_12m_rub / a.revenue_12m_rub * 100) + '%', 10, 15],
    ['Долговая нагрузка', Math.round(a.existing_monthly_payments_rub / (a.revenue_12m_rub / 12) * 100) + '%', 15, 15], ['Кредитная история', a.grade === 'D' ? '430' : '780', a.grade === 'D' ? 0 : 20, 20], ['Статус и флаги ФНС', 'нет флагов', 5, 5], ['Отраслевой риск', 'средний', 6, 10]]
    .map(([factor, value, points, max_points]) => ({ factor, value, points, max_points, comment: '' }));
}
function move(a: J, to: string, actor = 'SYSTEM', comment?: string, reason?: string) {
  a.history.push({ from_status: a.status, to_status: to, actor_type: actor, comment, reason_code: reason, created_at: now() });
  a.status = to; a.version++; a.updated_at = now();
  a.expires_at = to === 'NEEDS_INFO' ? later(72) : ['OFFER', 'COUNTER_OFFER'].includes(to) ? a.offer?.valid_until : to === 'SIGNING' ? later(48) : undefined;
}
function makeOffer(a: J, kind: 'ORIGINAL' | 'COUNTER', amount: number, term: number, r: number, explanation?: string) {
  a.offer = { kind, amount_rub: amount, term_months: term, rate_percent: r, monthly_payment_rub: payment(amount, term, r), valid_until: later(72), state: 'ACTIVE', explanation };
}
for (const [i, [inn, name, legal_form, okved, status, d]] of SEED.entries()) {
  const email = `client${i + 1}@demo.local`;
  companies.set(email, { id: uid(), inn, name, legal_form, okved, address: 'г. Москва, ул. Примерная, д. ' + (i + 1), registration_date: '2021-03-15' });
  const a: J = { id: uid(), owner: email, company_name: name, status: 'DRAFT', version: 1, docs: [], history: [], submitted_at: ago(60), updated_at: ago(60), ...d };
  a.history.push({ to_status: 'SUBMITTED', actor_type: 'CLIENT', created_at: ago(60) });
  for (const s of ['DATA_CHECK', 'ENRICHMENT', 'SCORING']) a.history.push({ from_status: a.history.at(-1).to_status, to_status: s, actor_type: 'SYSTEM', created_at: ago(59) });
  if (status === 'OFFER') makeOffer(a, 'ORIGINAL', a.amount_rub, a.term_months, rate(a.product_code));
  if (status === 'COUNTER_OFFER') makeOffer(a, 'COUNTER', d.offer[0], d.offer[1], d.offer[2], 'С учётом текущей платёжной нагрузки мы можем одобрить меньшую сумму.');
  if (status === 'NEEDS_INFO') a.info = { id: uid(), round: 1, requested_by: 'SYSTEM', created_at: ago(58), items: [{ code: 'DOCUMENT_MISSING', message: 'Приложите счёт поставщика на оборудование', doc_type: 'SUPPLIER_INVOICE' }] };
  if (status === 'REJECTED') a.reason_codes = d.knockouts;
  a.status = 'SCORING'; move(a, status, 'SYSTEM', status === 'MANUAL_REVIEW' ? 'Группа D: нужна проверка специалистом' : undefined);
  apps.push(a);
}
// Упрощённый конвейер для демо: через несколько секунд заявка проходит этапы, исход зависит от суммы и документов
function pipeline(a: J) {
  const p = PRODUCTS.find(x => x.code === a.product_code)!;
  const steps: [number, () => void][] = [[0, () => move(a, 'SUBMITTED', 'CLIENT')], [1500, () => move(a, 'DATA_CHECK')], [3000, () => {
    const missing = p.required_documents.filter(t => !a.docs.some((d: J) => d.doc_type === t));
    if (missing.length && !a.info) { a.info = { id: uid(), round: 1, requested_by: 'SYSTEM', created_at: now(), items: missing.map(t => ({ code: 'DOCUMENT_MISSING', message: 'Приложите документ: ' + (t === 'SUPPLIER_INVOICE' ? 'счёт поставщика' : 'финансовая отчётность'), doc_type: t })) }; move(a, 'NEEDS_INFO', 'SYSTEM', undefined, 'DOCUMENT_MISSING'); return 'stop'; }
    move(a, 'ENRICHMENT');
  }], [5000, () => move(a, 'SCORING')], [7000, () => {
    a.score = 78; a.grade = 'A';
    if (a.amount_rub <= p.auto_limit_rub) { makeOffer(a, 'ORIGINAL', a.amount_rub, a.term_months, p.base_rate_percent); move(a, 'OFFER'); }
    else move(a, 'MANUAL_REVIEW', 'SYSTEM', 'Сумма выше автолимита продукта');
  }]];
  let stopped = false;
  for (const [ms, f] of steps) setTimeout(() => { if (!stopped && (f() as unknown) === 'stop') stopped = true; }, ms);
}
const users = new Map<string, J>([['operator@demo.local', { role: 'OPERATOR', full_name: 'Оператор Демо' }], ['admin@demo.local', { role: 'ADMIN', full_name: 'Админ Демо' }],
  ...SEED.map((_, i) => [`client${i + 1}@demo.local`, { role: 'CLIENT', full_name: `Клиент ${i + 1}` }] as [string, J])]);
const me = (email: string) => ({ id: email, email, ...users.get(email) });
const view = (a: J) => { const { owner, docs, offer, info, history, score, grade, knockouts, ...rest } = a;
  return { ...rest, status_title: TEXT[a.status][0], status_description: TEXT[a.status][1], next_action: NEXT[a.status] ?? 'NONE', reason_messages: (a.reason_codes ?? []).map((c: string) => REASON[c] ?? c) }; };
const opView = (a: J) => ({ ...view(a), company: [...companies.entries()].find(([e]) => e === a.owner)?.[1], documents: a.docs, history: a.history,
  enrichment: { bki: { bki_score: a.grade === 'D' ? 430 : 780, overdue_active_days: 0, overdue_closed_12m_count: a.grade === 'D' ? 2 : 0 }, egrul: { registry_status: 'ACTIVE', registry_flags: [] } },
  scoring: a.score ? { score: a.score, grade: a.grade, factors: factors(a), knockouts: a.knockouts ?? [] } : undefined,
  suggested_decision: a.status === 'MANUAL_REVIEW' ? { outcome: 'COUNTER_OFFER', offer: { amount_rub: Math.floor(a.amount_rub / 2 / 10_000) * 10_000, term_months: a.term_months, rate_percent: rate(a.product_code) + 6 } } : undefined });

const res = (status: number, data?: J, headers: Record<string, string> = {}) => new Response(status === 204 || status === 304 ? null : JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...headers } });
const fail = (status: number, code: string, message: string) => res(status, { error: { code, message } });
export async function mockFetch(input: string, init: RequestInit = {}): Promise<Response> {
  await new Promise(r => setTimeout(r, 250)); // имитация сети, чтобы были видны состояния загрузки
  const url = new URL(input.replace(/^mock/, 'http://mock'));
  const path = url.pathname; const method = (init.method ?? 'GET').toUpperCase();
  const h = new Headers(init.headers); const email = h.get('Authorization')?.replace('Bearer mock:', '') ?? '';
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
  const user = users.get(email);
  if (path === '/auth/login') { const u = users.get(body.email?.trim().toLowerCase()); return u && body.password === 'Demo12345!' ? res(200, { access_token: 'mock:' + body.email.trim().toLowerCase(), token_type: 'bearer', user: me(body.email.trim().toLowerCase()) }) : fail(401, 'UNAUTHORIZED', 'Неверный email или пароль. В демо пароль у всех учёток: Demo12345!'); }
  if (path === '/auth/register') { const e = body.email.trim().toLowerCase(); if (users.has(e)) return fail(409, 'CONFLICT', 'Этот email уже зарегистрирован'); users.set(e, { role: 'CLIENT', full_name: body.full_name }); return res(201, { access_token: 'mock:' + e, token_type: 'bearer', user: me(e) }); }
  if (path === '/products') return res(200, PRODUCTS);
  if (!user) return fail(401, 'UNAUTHORIZED', 'Войдите заново');
  if (path === '/auth/me') return res(200, me(email));
  if (path === '/dev/reset-demo') return res(204);
  if (path === '/products/recommend') { const code = { WORKING_CAPITAL: 'WORKING_CAPITAL', EQUIPMENT: 'EQUIPMENT', URGENT_CASH: 'EXPRESS' }[body.purpose as string] ?? 'WORKING_CAPITAL';
    return res(200, { product_code: code, source: 'RULES', explanation: code === 'EXPRESS' ? 'Решение быстрее всего и без документов, если бизнесу больше года.' : code === 'EQUIPMENT' ? 'Длинный срок до 5 лет и ставка ниже — платёж будет комфортнее.' : 'Подходит для закупок и текущих расходов, срок до 2 лет.' }); }
  if (path === '/company') { if (method === 'PUT') { companies.set(email, { id: uid(), ...body }); return res(200, companies.get(email)); } return companies.has(email) ? res(200, companies.get(email)) : fail(404, 'NOT_FOUND', 'Профиль компании ещё не создан'); }
  if (path === '/company/lookup') { const s = SEED.find(x => x[0] === url.searchParams.get('inn')); return s ? res(200, { inn: s[0], name: s[1], legal_form: s[2], okved: s[3], address: 'г. Москва, ул. Примерная, д. 1', registration_date: '2021-03-15' }) : fail(404, 'NOT_FOUND', 'ИНН не найден в реестре. Попробуйте ИНН из демо-данных, например 0000001011'); }
  if (path === '/feed') return res(200, [{ id: 'f1', tag: 'TIP', title: 'Как банк считает платёж', summary: 'Ежемесячный платёж зависит от суммы, срока и ставки. Чем дольше срок, тем меньше платёж.' },
    { id: 'f2', tag: 'EDUCATION', title: 'Какие документы готовить', summary: 'Для оборотного кредита достаточно отчётности за последний год.' }, { id: 'f3', tag: 'STATUS', title: 'Решение онлайн', summary: 'Статус заявки обновляется сам — не нужно звонить в банк.' }]);
  if (path === '/applications' && method === 'GET') return res(200, apps.filter(a => a.owner === email).sort((x, y) => y.updated_at.localeCompare(x.updated_at)).map(view));
  if (path === '/applications' && method === 'POST') { if (!companies.has(email)) return fail(422, 'VALIDATION_ERROR', 'Сначала заполните профиль компании');
    const a: J = { id: uid(), owner: email, company_name: companies.get(email).name, status: 'DRAFT', version: 1, docs: [], history: [], updated_at: now(), ...body }; apps.push(a); return res(201, view(a)); }
  if (path === '/operator/queue') { if (user.role === 'CLIENT') return fail(403, 'FORBIDDEN', 'Нет доступа'); const st = url.searchParams.get('status'); const mine = url.searchParams.get('assigned_to_me') === 'true';
    return res(200, apps.filter(a => a.status !== 'DRAFT' && (!st || a.status === st) && (!mine || a.assigned_operator_id === email)).sort((x, y) => y.updated_at.localeCompare(x.updated_at)).map(view)); }
  const m = path.match(/^\/(operator\/)?applications\/([^/]+)(?:\/(.+))?$/); if (!m) return fail(404, 'NOT_FOUND', 'Нет такого адреса в демо-моке');
  const [, op, id, sub] = m; const a = apps.find(x => x.id === id && (op ? user.role !== 'CLIENT' : x.owner === email)); if (!a) return fail(404, 'NOT_FOUND', 'Заявка не найдена');
  if (op) {
    if (sub === 'take') { a.assigned_operator_id = email; a.history.push({ from_status: a.status, to_status: a.status, actor_type: 'OPERATOR', reason_code: 'TAKEN', comment: 'Взята в работу', created_at: now() }); a.version++; }
    if (sub === 'decision') {
      if (body.outcome === 'OFFER' || body.outcome === 'COUNTER_OFFER') makeOffer(a, body.outcome === 'OFFER' ? 'ORIGINAL' : 'COUNTER', body.offer.amount_rub, body.offer.term_months, body.offer.rate_percent, body.outcome === 'COUNTER_OFFER' ? body.comment : undefined);
      if (body.outcome === 'NEEDS_INFO') a.info = { id: uid(), round: 1, requested_by: email, created_at: now(), items: body.info_items };
      if (body.outcome === 'REJECTED') a.reason_codes = body.reason_codes ?? [];
      move(a, body.outcome, 'OPERATOR', body.comment);
    }
    return res(200, opView(a));
  }
  if (!sub && method === 'GET') { const tag = `"${a.version}"`; return h.get('If-None-Match') === tag ? res(304) : res(200, view(a), { ETag: tag }); }
  if (!sub && method === 'PATCH') { Object.assign(a, body); a.version++; a.updated_at = now(); return res(200, view(a)); }
  if (sub === 'history') return res(200, a.history);
  if (sub === 'submit') { pipeline(a); return res(202, view(a)); }
  if (sub === 'cancel') { move(a, 'CANCELLED', 'CLIENT'); return res(200, view(a)); }
  if (sub === 'documents') { const f = (body as FormData).get('file') as File; const d = { id: uid(), doc_type: (body as FormData).get('doc_type'), filename: f.name, size_bytes: f.size, uploaded_at: now() }; a.docs.push(d); return res(201, d); }
  if (sub === 'info-request') { if (method === 'GET') return a.info ? res(200, a.info) : fail(404, 'NOT_FOUND', 'Запроса уточнений нет');
    move(a, 'DATA_CHECK', 'CLIENT', body.comment); setTimeout(() => move(a, 'ENRICHMENT'), 1500); setTimeout(() => move(a, 'SCORING'), 3000);
    setTimeout(() => { a.score = 73; a.grade = 'B'; makeOffer(a, 'COUNTER', 890_000, a.term_months, 18.5, 'С учётом выручки и текущих платежей мы можем одобрить меньшую сумму.'); move(a, 'COUNTER_OFFER'); }, 5000);
    return res(200, view(a)); }
  if (sub === 'offer') return a.offer && ['OFFER', 'COUNTER_OFFER'].includes(a.status) ? res(200, a.offer) : fail(404, 'NOT_FOUND', 'Активного предложения нет');
  if (sub === 'offer/accept') { a.offer.state = 'ACCEPTED'; move(a, 'ACCEPTED', 'CLIENT'); setTimeout(() => move(a, 'SIGNING'), 2500); return res(200, view(a)); }
  if (sub === 'offer/decline') { a.offer.state = 'DECLINED'; move(a, 'CANCELLED', 'CLIENT'); return res(200, view(a)); }
  if (sub === 'sign') { if (a.status !== 'SIGNING') return fail(409, 'INVALID_TRANSITION', 'Документы ещё готовятся, подождите пару секунд'); move(a, 'DISBURSED', 'CLIENT'); return res(200, view(a)); }
  return fail(404, 'NOT_FOUND', 'Нет такого адреса в демо-моке');
}
