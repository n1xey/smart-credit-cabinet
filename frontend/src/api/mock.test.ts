import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mockFetch } from './mock';
// mockFetch имитирует задержку сети таймером: тесты двигают время вручную
const call = async (path: string, init: RequestInit = {}) => { const p = mockFetch('mock' + path, init); await vi.advanceTimersByTimeAsync(300); return p; };
const as = (email: string, init: RequestInit = {}): RequestInit => ({ ...init, headers: { Authorization: `Bearer mock:${email}`, ...(init.headers as Record<string, string>) } });
const post = (email: string, body: unknown, headers: Record<string, string> = {}) => as(email, { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json', ...headers } });
beforeEach(() => vi.useFakeTimers());

describe('демо-мок API', () => {
  it('вход с демо-паролем, неверный пароль — 401', async () => {
    expect((await call('/auth/login', { method: 'POST', body: JSON.stringify({ email: 'client1@demo.local', password: 'Demo12345!' }) })).status).toBe(200);
    expect((await call('/auth/login', { method: 'POST', body: JSON.stringify({ email: 'client1@demo.local', password: 'x' }) })).status).toBe(401);
  });
  it('очередь постранично с X-Total-Count', async () => {
    const r = await call('/operator/queue?limit=2&offset=0', as('operator@demo.local'));
    expect(Number(r.headers.get('X-Total-Count'))).toBeGreaterThan(2);
    expect(await r.json()).toHaveLength(2);
  });
  it('решение оператора: занятость, If-Match, обязательные reason_codes', async () => {
    const [app] = await (await call('/operator/queue?status=MANUAL_REVIEW', as('operator@demo.local'))).json();
    const url = `/operator/applications/${app.id}/decision`;
    expect((await call(url, post('operator@demo.local', { outcome: 'REJECTED', comment: 'Отказ' }))).status).toBe(409); // не взята в работу
    const taken = await (await call(`/operator/applications/${app.id}/take`, as('operator@demo.local', { method: 'POST' }))).json();
    expect((await call(`/operator/applications/${app.id}/take`, as('admin@demo.local', { method: 'POST' }))).status).toBe(409);
    const noReasons = await call(url, post('operator@demo.local', { outcome: 'REJECTED', comment: 'Отказ' }));
    expect(noReasons.status).toBe(422);
    expect((await noReasons.json()).error.details[0].field).toBe('reason_codes');
    const stale = await call(url, post('operator@demo.local', { outcome: 'REJECTED', comment: 'Отказ', reason_codes: ['LOW_SCORE'] }, { 'If-Match': '"0"' }));
    expect((await stale.json()).error.code).toBe('VERSION_CONFLICT');
    const ok = await call(url, post('operator@demo.local', { outcome: 'REJECTED', comment: 'Отказ', reason_codes: ['LOW_SCORE'] }, { 'If-Match': `"${taken.version}"` }));
    expect((await ok.json()).status).toBe('REJECTED');
  });
  it('новая заявка проходит конвейер до OFFER; неполная — 422 с полями', async () => {
    const e = 'client7@demo.local';
    const draft = await (await call('/applications', post(e, { product_code: 'EXPRESS', amount_rub: 300_000, term_months: 6 }))).json();
    const incomplete = await call(`/applications/${draft.id}/submit`, post(e, {}, { 'Idempotency-Key': 'key-00001' }));
    expect(incomplete.status).toBe(422);
    expect((await incomplete.json()).error.details.map((d: { field: string }) => d.field)).toEqual(['revenue_12m_rub', 'net_profit_12m_rub']);
    await call(`/applications/${draft.id}`, as(e, { method: 'PATCH', body: JSON.stringify({ revenue_12m_rub: 5_000_000, net_profit_12m_rub: 2_000_000 }) }));
    expect((await call(`/applications/${draft.id}/submit`, post(e, {}, { 'Idempotency-Key': 'key-00002' }))).status).toBe(202);
    expect((await call(`/applications/${draft.id}/submit`, post(e, {}, { 'Idempotency-Key': 'key-00002' }))).status).toBe(202); // повтор с тем же ключом
    await vi.advanceTimersByTimeAsync(8000);
    expect((await (await call(`/applications/${draft.id}`, as(e))).json()).status).toBe('OFFER');
  });
});
