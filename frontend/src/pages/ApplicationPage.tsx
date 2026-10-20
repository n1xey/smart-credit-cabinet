import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, Application, HistoryItem, Offer, dt, money, sseUrl } from '../api/client';
import { StatusBadge, FINAL_BAD } from './shared';
const TERMINAL = ['REJECTED', 'CANCELLED', 'EXPIRED', 'DISBURSED'];
export default function ApplicationPage() {
  const { id } = useParams(); const [a, setA] = useState<Application | null>(null); const [hist, setHist] = useState<HistoryItem[]>([]);
  const [err, setErr] = useState(''); const etag = useRef<string | null>(null);
  const refresh = useCallback(async () => { // опрос с If-None-Match: запасной вариант к SSE
    try {
      const h: Record<string, string> = etag.current ? { 'If-None-Match': etag.current } : {};
      const res = await fetch(`${import.meta.env.VITE_API_URL || '/api/v1'}/applications/${id}`, { headers: { ...h, Authorization: `Bearer ${sessionStorage.getItem('token')}` } });
      if (res.status === 304) return; if (!res.ok) throw new Error('Не удалось загрузить заявку');
      etag.current = res.headers.get('ETag'); setA(await res.json()); setHist(await api<HistoryItem[]>(`/applications/${id}/history`));
    } catch (e: any) { setErr(e.message); }
  }, [id]);
  useEffect(() => {
    refresh(); const t = setInterval(refresh, 3000);
    let es: EventSource | undefined; try { es = new EventSource(sseUrl(id!)); es.onmessage = () => { etag.current = null; refresh(); }; es.onerror = () => es?.close(); } catch { /* остаётся опрос */ }
    return () => { clearInterval(t); es?.close(); };
  }, [id, refresh]);
  if (!a) return err ? <p className="err" role="alert">{err}</p> : <p>Загрузка…</p>;
  const act = async (path: string) => { setErr(''); try { await api(`/applications/${id}/${path}`, { method: 'POST' }); etag.current = null; refresh(); } catch (e: any) { setErr(e.message); } };
  return <>
    <p><Link to="/">← Все заявки</Link></p>
    <div className="card"><StatusBadge s={a.status} title={a.status_title} />
      <p className="big">{a.status_title}</p><p>{a.status_description}</p>
      <small className="muted">{money(a.amount_rub)} на {a.term_months} мес. {a.expires_at && !TERMINAL.includes(a.status) && <>· действует до {dt(a.expires_at)}</>}</small>
      {!TERMINAL.includes(a.status) && !['OFFER','COUNTER_OFFER'].includes(a.status) && <small className="muted" style={{ display: 'block' }} role="status">Страница обновляется сама — ничего нажимать не нужно.</small>}</div>
    {err && <p className="err" role="alert">{err}</p>}
    {a.next_action === 'ANSWER_INFO_REQUEST' && <InfoForm id={id!} onDone={refresh} />}
    {a.next_action === 'REVIEW_OFFER' && <OfferBox id={id!} onAccept={() => act('offer/accept')} onDecline={() => act('offer/decline')} />}
    {a.next_action === 'SIGN' && <div className="card"><h2>Подпишите документы</h2><p>Мы подготовили кредитный договор. Это демо: подпись ни к чему вас не обязывает.</p><button onClick={() => act('sign')}>Подписать</button></div>}
    {a.status === 'DISBURSED' && <div className="card"><h2>Готово! 🎉</h2><p>Средства выданы. <strong>Это демонстрация</strong>: реальных денег и договоров нет.</p></div>}
    {FINAL_BAD.includes(a.status) && (a.reason_messages?.length ?? 0) > 0 && <div className="card"><h2>Почему так получилось</h2><ul>{a.reason_messages!.map(m => <li key={m}>{m}</li>)}</ul>
      <p>Что можно сделать: подайте новую заявку с другой суммой или сроком.</p><Link className="btn" to="/apply">Новая заявка с другими условиями</Link></div>}
    <div className="card"><h2>Как шла заявка</h2><ol className="tl">{[...hist].reverse().map((h, i) => <li key={i}><StatusBadge s={h.to_status} /> <small>{dt(h.created_at)}</small>{h.comment && <div className="muted">{h.comment}</div>}</li>)}</ol></div>
  </>;
}
function OfferBox({ id, onAccept, onDecline }: { id: string; onAccept(): void; onDecline(): void }) {
  const [o, setO] = useState<Offer | null>(null); useEffect(() => { api<Offer>(`/applications/${id}/offer`).then(setO).catch(() => {}); }, [id]);
  if (!o) return null;
  return <div className="card"><h2>{o.kind === 'COUNTER' ? 'Банк предлагает другие условия' : 'Банк одобрил вашу заявку'}</h2>
    {o.kind === 'COUNTER' && <p>{o.explanation ?? 'Мы можем предложить меньшую сумму.'}</p>}
    <div className="grid"><div><small>Сумма</small><p className="big">{money(o.amount_rub)}</p></div><div><small>Срок</small><p className="big">{o.term_months} мес.</p></div>
      <div><small>Ставка (годовых)</small><p className="big">{o.rate_percent}%</p></div><div><small>Платёж в месяц</small><p className="big">{money(o.monthly_payment_rub)}</p></div></div>
    <p className="muted">Предложение действует до {dt(o.valid_until)}.</p><div className="row"><button onClick={onAccept}>Принять</button><button className="sec" onClick={onDecline}>Отказаться</button></div></div>;
}
function InfoForm({ id, onDone }: { id: string; onDone(): void }) {
  const [req, setReq] = useState<any>(null); const [comment, setComment] = useState(''); const [err, setErr] = useState('');
  useEffect(() => { api<any>(`/applications/${id}/info-request`).then(setReq).catch(e => setErr(e.message)); }, [id]);
  const upload = async (type: string, file: File) => { const fd = new FormData(); fd.append('doc_type', type); fd.append('file', file); try { await api(`/applications/${id}/documents`, { method: 'POST', body: fd }); setErr(''); } catch (e: any) { setErr(e.message); } };
  const send = async () => { try { await api(`/applications/${id}/info-request`, { method: 'POST', json: { comment } }); onDone(); } catch (e: any) { setErr(e.message); } };
  return <div className="card"><h2>Что нужно сделать</h2>
    {req?.items?.map((it: any, i: number) => <div key={i}><p><strong>{it.message}</strong></p>{it.doc_type && <input aria-label={it.message} type="file" onChange={e => e.target.files?.[0] && upload(it.doc_type, e.target.files[0])} />}</div>)}
    <label htmlFor="c">Комментарий для банка</label><textarea id="c" maxLength={1000} value={comment} onChange={e => setComment(e.target.value)} />
    {err && <p className="err" role="alert">{err}</p>}<p><button onClick={send}>Отправить ответ</button></p></div>;
}
