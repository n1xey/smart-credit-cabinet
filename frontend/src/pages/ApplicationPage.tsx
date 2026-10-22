import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@alfalab/core-components-button';
import { Plate } from '@alfalab/core-components-plate';
import { Textarea } from '@alfalab/core-components-textarea';
import { Attach } from '@alfalab/core-components-attach';
import { Typography } from '@alfalab/core-components-typography';
import { Gap } from '@alfalab/core-components-gap';
import { api, http, API_BASE, MOCK, getToken, errorText, isVersionConflict, Application, HistoryItem, Offer, dt, money } from '../api/client';
import { subscribeStatus } from '../api/events';
import { StatusBadge, FINAL_BAD, ErrorPlate, H2, Hint, Loading, LABEL } from './shared';
const TERMINAL = ['REJECTED', 'CANCELLED', 'EXPIRED', 'DISBURSED'];
const POLL_MS = 3000, POLL_WITH_SSE_MS = 15000; // при живом SSE опрос остаётся редкой страховкой
const Big = ({ children }: { children: React.ReactNode }) => <Typography.Text view="primary-large" weight="bold" tag="div">{children}</Typography.Text>;
export default function ApplicationPage() {
  const { id } = useParams(); const nav = useNavigate(); const [a, setA] = useState<Application | null>(null); const [hist, setHist] = useState<HistoryItem[]>([]);
  const [err, setErr] = useState(''); const etag = useRef<string | null>(null);
  const refresh = useCallback(async () => { // опрос с If-None-Match: запасной вариант к SSE
    try {
      const h: Record<string, string> = etag.current ? { 'If-None-Match': etag.current } : {};
      const res = await http(`${API_BASE}/applications/${id}`, { headers: { ...h, Authorization: `Bearer ${getToken()}` } });
      if (res.status === 304) return; if (!res.ok) throw new Error('Не удалось загрузить заявку');
      etag.current = res.headers.get('ETag'); setA(await res.json()); setHist(await api<HistoryItem[]>(`/applications/${id}/history`));
    } catch (e) { setErr(errorText(e)); }
  }, [id]);
  useEffect(() => {
    refresh();
    let t = setInterval(refresh, POLL_MS);
    const repoll = (ms: number) => { clearInterval(t); t = setInterval(refresh, ms); };
    // в демо-моке потока нет: хватает опроса
    const unsubscribe = MOCK ? () => {} : subscribeStatus(id!, () => { repoll(POLL_WITH_SSE_MS); refresh(); }, () => repoll(POLL_MS));
    return () => { clearInterval(t); unsubscribe(); };
  }, [id, refresh]);
  if (!a) return err ? <ErrorPlate text={err} /> : <Loading />;
  const act = async (path: string, ifMatch?: number) => {
    setErr('');
    try { await api(`/applications/${id}/${path}`, { method: 'POST', ifMatch }); }
    catch (e) { setErr(errorText(e)); if (!isVersionConflict(e)) return; }
    etag.current = null; refresh();
  };
  const live = !TERMINAL.includes(a.status) && (a.next_action ?? 'NONE') === 'NONE'; // подсказка «ничего нажимать не нужно» — только когда действительно ждём банк
  return <>
    <Link to="/" className="muted">← Все заявки</Link><Gap size={16} />
    <div className="card"><StatusBadge s={a.status} /><Gap size={12} />
      <Typography.TitleResponsive tag="h1" view="medium" font="system" weight="bold">{a.status_title ?? LABEL[a.status] ?? a.status}</Typography.TitleResponsive>
      {a.status_description && <Typography.Text view="primary-medium" tag="p">{a.status_description}</Typography.Text>}
      <Hint>{money(a.amount_rub)} на {a.term_months} мес.{a.expires_at && !TERMINAL.includes(a.status) && <> · действует до {dt(a.expires_at)}</>}</Hint>
      {live && <><Gap size={8} /><div role="status"><Hint>Страница обновляется сама — ничего нажимать не нужно.</Hint></div></>}</div>
    <ErrorPlate text={err} />
    {a.next_action === 'FILL_DRAFT' && <div className="card"><H2>Заявка ещё не отправлена</H2><Hint>Черновик сохранён. Подайте новую заявку в мастере или удалите этот черновик.</Hint><Gap size={16} />
      <div className="row"><Button view="accent" onClick={() => nav('/apply')}>Заполнить заявку</Button><Button view="secondary" onClick={() => act('cancel')}>Отменить черновик</Button></div></div>}
    {a.next_action === 'ANSWER_INFO_REQUEST' && <InfoForm id={id!} onDone={refresh} />}
    {a.next_action === 'REVIEW_OFFER' && <OfferBox id={id!} onAccept={() => act('offer/accept', a.version)} onDecline={() => act('offer/decline', a.version)} />}
    {a.next_action === 'SIGN' && <div className="card"><H2>Подпишите документы</H2><Typography.Text view="primary-medium" tag="p">Мы подготовили кредитный договор. Это демо: подпись ни к чему вас не обязывает.</Typography.Text><Button view="accent" onClick={() => act('sign')}>Подписать</Button></div>}
    {a.status === 'DISBURSED' && <div className="card"><Plate view="positive" rounded title="Готово! Средства выданы">Это демонстрация: реальных денег и договоров нет.</Plate></div>}
    {FINAL_BAD.includes(a.status) && (a.reason_messages?.length ?? 0) > 0 && <div className="card"><H2>Почему так получилось</H2>
      <ul>{a.reason_messages!.map(m => <li key={m}><Typography.Text view="primary-medium">{m}</Typography.Text></li>)}</ul>
      <Hint>Что можно сделать: подайте новую заявку с другой суммой или сроком.</Hint><Gap size={16} /><Button view="accent" onClick={() => nav('/apply')}>Новая заявка с другими условиями</Button></div>}
    <div className="card"><H2>Как шла заявка</H2><ol className="tl">{[...hist].reverse().map((h, i) => <li key={i}><StatusBadge s={h.to_status} /> <Typography.Text view="primary-small" color="secondary">{dt(h.created_at)}</Typography.Text>{h.comment && <Hint>{h.comment}</Hint>}</li>)}</ol></div>
  </>;
}
function OfferBox({ id, onAccept, onDecline }: { id: string; onAccept(): void; onDecline(): void }) {
  const [o, setO] = useState<Offer | null>(null); useEffect(() => { api<Offer>(`/applications/${id}/offer`).then(setO).catch(() => {}); }, [id]);
  if (!o) return null;
  return <div className="card"><H2>{o.kind === 'COUNTER' ? 'Банк предлагает другие условия' : 'Банк одобрил вашу заявку'}</H2>
    {o.kind === 'COUNTER' && <><Plate view="attention" rounded title="Почему условия другие">{o.explanation ?? 'Мы можем предложить меньшую сумму.'}</Plate><Gap size={16} /></>}
    <div className="grid kv"><div><small>Сумма</small><Big>{money(o.amount_rub)}</Big></div><div><small>Срок</small><Big>{o.term_months} мес.</Big></div>
      <div><small>Ставка (годовых)</small><Big>{o.rate_percent}%</Big></div><div><small>Платёж в месяц</small><Big>{money(o.monthly_payment_rub)}</Big></div></div>
    <Gap size={16} /><Hint>Предложение действует до {dt(o.valid_until)}.</Hint><Gap size={16} />
    <div className="row"><Button view="accent" onClick={onAccept}>Принять</Button><Button view="secondary" onClick={onDecline}>Отказаться</Button></div></div>;
}
function InfoForm({ id, onDone }: { id: string; onDone(): void }) {
  const [req, setReq] = useState<any>(null); const [comment, setComment] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { api<any>(`/applications/${id}/info-request`).then(setReq).catch(e => setErr(errorText(e))); }, [id]);
  const upload = async (type: string, file: File) => { const fd = new FormData(); fd.append('doc_type', type); fd.append('file', file); try { await api(`/applications/${id}/documents`, { method: 'POST', body: fd }); setErr(''); } catch (e) { setErr(errorText(e)); } };
  const send = async () => { setBusy(true); try { await api(`/applications/${id}/info-request`, { method: 'POST', json: { comment } }); onDone(); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); } };
  return <div className="card"><H2>Что нужно сделать</H2>
    <div className="stack">{req?.items?.map((it: any, i: number) => <div key={i}><Plate view="attention" rounded title={it.message} />
      {it.doc_type && <><Gap size={8} /><Attach buttonContent="Загрузить документ" noFileText="Файл не выбран" onChange={(_, { files }) => files[0] && upload(it.doc_type, files[0])} /></>}</div>)}
      <Textarea label="Комментарий для банка" aria-label="Комментарий для банка" block autosize minRows={2} maxLength={1000} showCounter value={comment} onChange={(_, { value }) => setComment(value)} />
    </div><Gap size={16} />
    <ErrorPlate text={err} /><Button view="accent" loading={busy} onClick={send}>Отправить ответ</Button></div>;
}
