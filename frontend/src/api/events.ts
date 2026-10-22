// SSE `GET /applications/{id}/events` через fetch со стримом и заголовком Authorization (контракт v0.2:
// EventSource не используем, токен в query не передаём — он попал бы в логи nginx).
import { API_BASE, getToken, http } from './client';
export interface StatusEvent { application_id: string; status: string; version: number; updated_at: string }

// Разбор потока text/event-stream: события разделены пустой строкой, данные в строках `data:`; комментарии (`:`) — heartbeat
export function parseSse(buffer: string): { events: string[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n');
  const rest = blocks.pop() ?? '';
  const events = blocks.map(b => b.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).replace(/^ /, '')).join('\n')).filter(Boolean);
  return { events, rest };
}

// Возвращает функцию отписки. onFail вызывается, если поток недоступен или оборвался: тогда остаётся опрос с ETag.
export function subscribeStatus(id: string, onEvent: (e: StatusEvent) => void, onFail: () => void = () => {}): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await http(`${API_BASE}/applications/${id}/events`, { headers: { Authorization: `Bearer ${getToken()}`, Accept: 'text/event-stream' }, signal: ctrl.signal });
      if (!res.ok || !res.body) throw new Error('SSE недоступен');
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const parsed = parseSse(buf + value); buf = parsed.rest;
        for (const data of parsed.events) { try { onEvent(JSON.parse(data)); } catch { /* битое событие пропускаем */ } }
      }
      if (!ctrl.signal.aborted) onFail();
    } catch { if (!ctrl.signal.aborted) onFail(); }
  })();
  return () => ctrl.abort();
}
