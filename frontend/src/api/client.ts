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
export interface Application { id: string; status: string; product_code: string; amount_rub: number; term_months: number; company_name?: string; updated_at: string; version?: number; status_title?: string; status_description?: string; next_action?: 'NONE' | 'FILL_DRAFT' | 'ANSWER_INFO_REQUEST' | 'REVIEW_OFFER' | 'SIGN'; reason_messages?: string[]; expires_at?: string; purpose?: string; revenue_12m_rub?: number; net_profit_12m_rub?: number; existing_monthly_payments_rub?: number }
export interface HistoryItem { from_status?: string; to_status: string; actor_type?: string; comment?: string; created_at: string }
export interface Company { inn: string; name: string; legal_form: 'OOO' | 'IP'; registration_date?: string; okved?: string; address?: string }
export class ApiError extends Error { constructor(public status: number, public code: string, message: string) { super(message); } }

let token: string | null = sessionStorage.getItem('token'); // только токен; бизнес-данные в браузере не храним
let onUnauthorized: () => void = () => {};
export const setToken = (t: string | null) => { token = t; t ? sessionStorage.setItem('token', t) : sessionStorage.removeItem('token'); };
export const getToken = () => token;
export const setUnauthorizedHandler = (f: () => void) => { onUnauthorized = f; };

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) { headers.set('Content-Type', 'application/json'); body = JSON.stringify(init.json); }
  let res: Response;
  try { res = await http(BASE + path, { ...init, headers, body }); }
  catch { throw new ApiError(0, 'NETWORK', 'Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.'); }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token) { setToken(null); onUnauthorized(); }
    throw new ApiError(res.status, data?.error?.code ?? 'ERROR', data?.error?.message ?? 'Что-то пошло не так');
  }
  return data as T;
}
export const money = (n: number) => new Intl.NumberFormat('ru-RU').format(n) + ' ₽';
export const dt = (s: string) => new Date(s).toLocaleString('ru-RU');
// Аннуитетный платёж (оценка для слайдера; итог считает банк)
export const payment = (amount: number, months: number, ratePct: number) => {
  const r = ratePct / 1200; return Math.round(r === 0 ? amount / months : (amount * r) / (1 - Math.pow(1 + r, -months)));
};
export const sseUrl = (id: string) => `${BASE}/applications/${id}/events?token=${encodeURIComponent(token ?? '')}`;
