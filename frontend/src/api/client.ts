// Тонкая обёртка над fetch. Типы схем: npm run gen:api -> src/api/schema.d.ts (openapi-typescript).
const BASE: string = import.meta.env.VITE_API_URL || '/api/v1';
// VITE_API_URL=mock — встроенный демо-мок без бэкенда (src/api/mock.ts); в обычную сборку он не попадает
export const MOCK = BASE === 'mock';
export const http = (url: string, init?: RequestInit): Promise<Response> => MOCK ? import('./mock').then(m => m.mockFetch(url, init)) : fetch(url, init);
export const API_BASE = BASE;
export type Role = 'CLIENT' | 'OPERATOR' | 'ADMIN';
export interface User { id: string; email: string; full_name?: string; role: Role }
export interface Product { code: string; name: string; description?: string; min_amount_rub: number; max_amount_rub: number; min_term_months: number; max_term_months: number; base_rate_percent: number; auto_limit_rub?: number; required_documents: string[] }
export interface Offer { kind: 'ORIGINAL' | 'COUNTER'; amount_rub: number; term_months: number; rate_percent: number; monthly_payment_rub: number; valid_until: string; explanation?: string }
export interface Application { id: string; status: string; product_code: string; amount_rub: number; term_months: number; company_name?: string; updated_at: string; version?: number; status_title?: string; status_description?: string; next_action?: 'NONE' | 'FILL_DRAFT' | 'ANSWER_INFO_REQUEST' | 'REVIEW_OFFER' | 'SIGN'; reason_messages?: string[]; expires_at?: string; purpose?: string; revenue_12m_rub?: number; net_profit_12m_rub?: number; existing_monthly_payments_rub?: number; reason_codes?: string[]
  // Ожидается в контракте (SCORING.md, «Объяснение решения клиенту»), PR contract ещё не сделан: пока поле может отсутствовать
  decision_highlights?: string[] }
export interface HistoryItem { from_status?: string; to_status: string; actor_type?: string; comment?: string; created_at: string }
export interface Company { inn: string; name: string; legal_form: 'OOO' | 'IP'; registration_date?: string; okved?: string; address?: string }
export interface ErrorDetail { field?: string; message?: string }
export class ApiError extends Error { constructor(public status: number, public code: string, message: string, public details: ErrorDetail[] = []) { super(message); } }
// Текст ошибки для пользователя: сообщение + список полей из 422 (`details`)
export const errorText = (e: unknown) => e instanceof ApiError && e.details.length
  ? `${e.message}: ${e.details.map(d => [d.field, d.message].filter(Boolean).join(' — ')).join('; ')}` : (e as Error).message;
export const isVersionConflict = (e: unknown) => e instanceof ApiError && e.code === 'VERSION_CONFLICT';

let token: string | null = sessionStorage.getItem('token'); // только токен; бизнес-данные в браузере не храним
let onUnauthorized: () => void = () => {};
export const setToken = (t: string | null) => { token = t; t ? sessionStorage.setItem('token', t) : sessionStorage.removeItem('token'); };
export const getToken = () => token;
export const setUnauthorizedHandler = (f: () => void) => { onUnauthorized = f; };

// ifMatch — версия заявки: сервер вернёт 409 VERSION_CONFLICT, если заявку уже изменили
type Init = RequestInit & { json?: unknown; ifMatch?: number };
async function request(path: string, init: Init = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.ifMatch !== undefined) headers.set('If-Match', `"${init.ifMatch}"`);
  let body = init.body;
  if (init.json !== undefined) { headers.set('Content-Type', 'application/json'); body = JSON.stringify(init.json); }
  let res: Response;
  try { res = await http(BASE + path, { ...init, headers, body }); }
  catch { throw new ApiError(0, 'NETWORK', 'Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.'); }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    if (res.status === 401 && token) { setToken(null); onUnauthorized(); }
    const code = data?.error?.code ?? 'ERROR';
    const message = code === 'VERSION_CONFLICT' ? 'Заявка уже изменилась. Мы обновили данные — проверьте их и повторите действие.' : data?.error?.message ?? 'Что-то пошло не так';
    throw new ApiError(res.status, code, message, Array.isArray(data?.error?.details) ? data.error.details : []);
  }
  return res;
}
export async function api<T>(path: string, init: Init = {}): Promise<T> {
  const res = await request(path, init);
  if (res.status === 204) return undefined as T;
  return await res.json().catch(() => null) as T;
}
// Постраничные списки: limit/offset в query, общее число в заголовке X-Total-Count
export const PAGE = 20;
export async function apiPage<T>(path: string, offset: number, limit = PAGE): Promise<{ items: T[]; total: number }> {
  const sep = path.includes('?') ? '&' : '?';
  const res = await request(`${path}${sep}limit=${limit}&offset=${offset}`);
  const items = (await res.json()) as T[];
  const total = Number(res.headers.get('X-Total-Count'));
  return { items, total: Number.isFinite(total) && res.headers.has('X-Total-Count') ? total : offset + items.length };
}
export const money = (n: number) => new Intl.NumberFormat('ru-RU').format(n) + ' ₽';
export const dt = (s: string) => new Date(s).toLocaleString('ru-RU');
// Аннуитетный платёж (оценка для слайдера; итог считает банк)
export const payment = (amount: number, months: number, ratePct: number) => {
  const r = ratePct / 1200; return Math.round(r === 0 ? amount / months : (amount * r) / (1 - Math.pow(1 + r, -months)));
};
