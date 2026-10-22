import { describe, expect, it, vi } from 'vitest';
import { parseSse, subscribeStatus } from './events';
import { setToken } from './client';

describe('parseSse', () => {
  it('отделяет полные события, heartbeat пропускает, хвост оставляет', () => {
    const { events, rest } = parseSse(': ping\n\ndata: {"status":"SCORING"}\n\ndata: {"sta');
    expect(events).toEqual(['{"status":"SCORING"}']);
    expect(rest).toBe('data: {"sta');
  });
  it('понимает CRLF и многострочные data', () => expect(parseSse('data: a\r\ndata: b\r\n\r\n').events).toEqual(['a\nb']));
});

describe('subscribeStatus', () => {
  it('читает поток через fetch с Authorization, токена в адресе нет', async () => {
    setToken('secret-jwt');
    const enc = new TextEncoder();
    const body = new ReadableStream({ start(c) { c.enqueue(enc.encode('data: {"application_id":"1","status":"OFFER","version":5,"updated_at":"x"}\n\n')); c.close(); } });
    const f = vi.fn(async (_: string, _i?: RequestInit) => new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })); vi.stubGlobal('fetch', f);
    const onEvent = vi.fn(); const onFail = vi.fn();
    subscribeStatus('1', onEvent, onFail);
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ status: 'OFFER', version: 5 })));
    const [url, init] = f.mock.calls[0];
    expect(url).toBe('/api/v1/applications/1/events');
    expect(url).not.toContain('secret-jwt');
    expect(new Headers(init!.headers).get('Authorization')).toBe('Bearer secret-jwt');
    await vi.waitFor(() => expect(onFail).toHaveBeenCalled()); // поток закрылся — страница вернётся к частому опросу
  });
  it('при ошибке сервера сообщает onFail', async () => {
    vi.stubGlobal('fetch', async () => new Response(null, { status: 404 }));
    const onFail = vi.fn(); subscribeStatus('1', () => {}, onFail);
    await vi.waitFor(() => expect(onFail).toHaveBeenCalled());
  });
});
