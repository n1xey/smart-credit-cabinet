import { describe, expect, it, vi } from 'vitest';
import { api, apiPage, ApiError, errorText, payment } from './client';
const json = (status: number, data: unknown, headers: Record<string, string> = {}) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...headers } });

describe('payment', () => {
  it('считает аннуитетный платёж', () => expect(payment(780_000, 24, 20)).toBe(39_699));
  it('без процентов делит сумму на срок', () => expect(payment(120_000, 12, 0)).toBe(10_000));
});

describe('api', () => {
  it('передаёт If-Match с версией заявки в кавычках', async () => {
    const f = vi.fn(async (_: string, _init?: RequestInit) => json(200, {})); vi.stubGlobal('fetch', f);
    await api('/applications/1/offer/accept', { method: 'POST', ifMatch: 7 });
    expect(new Headers(f.mock.calls[0][1]!.headers).get('If-Match')).toBe('"7"');
  });
  it('VERSION_CONFLICT превращается в понятное сообщение', async () => {
    vi.stubGlobal('fetch', async () => json(409, { error: { code: 'VERSION_CONFLICT', message: 'version mismatch' } }));
    await expect(api('/x')).rejects.toMatchObject({ code: 'VERSION_CONFLICT', message: expect.stringContaining('Заявка уже изменилась') });
  });
  it('errorText показывает поля из details для 422', () => {
    const e = new ApiError(422, 'VALIDATION_ERROR', 'Заявка заполнена не полностью', [{ field: 'revenue_12m_rub', message: 'укажите выручку' }]);
    expect(errorText(e)).toBe('Заявка заполнена не полностью: revenue_12m_rub — укажите выручку');
  });
});

describe('apiPage', () => {
  it('шлёт limit/offset и читает X-Total-Count', async () => {
    const f = vi.fn(async (_: string) => json(200, [{ id: 'a' }], { 'X-Total-Count': '41' })); vi.stubGlobal('fetch', f);
    const p = await apiPage('/operator/queue?status=MANUAL_REVIEW', 20);
    expect(f.mock.calls[0][0]).toBe('/api/v1/operator/queue?status=MANUAL_REVIEW&limit=20&offset=20');
    expect(p).toEqual({ items: [{ id: 'a' }], total: 41 });
  });
});
