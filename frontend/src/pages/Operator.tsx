import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, Application, money, dt } from '../api/client';
import { StatusBadge } from './shared';
const STATUSES = ['', 'MANUAL_REVIEW', 'NEEDS_INFO', 'SCORING', 'OFFER', 'COUNTER_OFFER', 'REJECTED'];
export default function Operator() {
  const [st, setSt] = useState('MANUAL_REVIEW'); const [mine, setMine] = useState(false); const [rows, setRows] = useState<Application[] | null>(null); const [err, setErr] = useState('');
  useEffect(() => { setRows(null); const q = new URLSearchParams(); if (st) q.set('status', st); if (mine) q.set('assigned_to_me', 'true');
    api<Application[]>(`/operator/queue?${q}`).then(setRows).catch(e => setErr(e.message)); }, [st, mine]);
  return <><h1>Очередь заявок</h1>
    <div className="row"><label htmlFor="s" style={{ margin: 0 }}>Статус</label><select id="s" value={st} onChange={e => setSt(e.target.value)} style={{ width: 'auto' }}>{STATUSES.map(s => <option key={s} value={s}>{s || 'Все'}</option>)}</select>
      <label style={{ margin: 0 }}><input type="checkbox" style={{ width: 'auto' }} checked={mine} onChange={e => setMine(e.target.checked)} /> Только мои</label></div>
    {err && <p className="err" role="alert">{err}</p>}
    <div className="card scroll">{!rows ? 'Загрузка…' : rows.length === 0 ? 'В очереди пусто' : <table><thead><tr><th>Компания</th><th>Сумма</th><th>Статус</th><th>Обновлена</th></tr></thead>
      <tbody>{rows.map(r => <tr key={r.id}><td><Link to={`/operator/${r.id}`}>{r.company_name ?? r.id.slice(0, 8)}</Link></td><td>{money(r.amount_rub)} / {r.term_months} мес.</td><td><StatusBadge s={r.status} /></td><td>{dt(r.updated_at)}</td></tr>)}</tbody></table>}</div></>;
}
export function OperatorCard() {
  const { id } = useParams(); const [a, setA] = useState<any>(null); const [err, setErr] = useState('');
  const [d, setD] = useState({ outcome: 'OFFER', comment: '', amount: '', term: '', rate: '', info: '' });
  const load = () => api<any>(`/operator/applications/${id}`).then(setA).catch(e => setErr(e.message)); useEffect(() => { load(); }, [id]);
  const take = async () => { try { setA(await api(`/operator/applications/${id}/take`, { method: 'POST' })); } catch (e: any) { setErr(e.message); } };
  const decide = async () => {
    setErr(''); const json: any = { outcome: d.outcome, comment: d.comment };
    if (d.outcome === 'OFFER' || d.outcome === 'COUNTER_OFFER') json.offer = { amount_rub: +d.amount, term_months: +d.term, rate_percent: +d.rate };
    if (d.outcome === 'NEEDS_INFO') json.info_items = [{ code: 'OTHER', message: d.info || d.comment }];
    try { setA(await api(`/operator/applications/${id}/decision`, { method: 'POST', json })); } catch (e: any) { setErr(e.message); }
  };
  if (!a) return err ? <p className="err">{err}</p> : <p>Загрузка…</p>;
  const sc = a.scoring; const sd = a.suggested_decision; const canDecide = a.status === 'MANUAL_REVIEW'; const needsOffer = d.outcome === 'OFFER' || d.outcome === 'COUNTER_OFFER';
  return <><p><Link to="/operator">← Очередь</Link></p>
    <div className="card"><h1>{a.company?.name} <StatusBadge s={a.status} /></h1><p>ИНН {a.company?.inn} · {a.product_code}: {money(a.amount_rub)} на {a.term_months} мес.</p>
      <p className="muted">Выручка {money(a.revenue_12m_rub ?? 0)} · прибыль {money(a.net_profit_12m_rub ?? 0)} · платежи {money(a.existing_monthly_payments_rub ?? 0)}/мес</p>
      {canDecide && !a.assigned_operator_id && <button onClick={take}>Взять в работу</button>}</div>
    {sc && <div className="card scroll"><h2>Скоринг: {sc.score} баллов, группа {sc.grade}</h2>{sc.knockouts?.length > 0 && <p className="err">Стоп-факторы: {sc.knockouts.join(', ')}</p>}
      <table><thead><tr><th>Фактор</th><th>Значение</th><th>Баллы</th><th>Комментарий</th></tr></thead><tbody>{sc.factors?.map((f: any) => <tr key={f.factor}><td>{f.factor}</td><td>{f.value}</td><td>{f.points}/{f.max_points}</td><td>{f.comment}</td></tr>)}</tbody></table></div>}
    <div className="grid"><div className="card"><h3>БКИ</h3><pre>{JSON.stringify(a.enrichment?.bki ?? {}, null, 1)}</pre></div><div className="card"><h3>ЕГРЮЛ</h3><pre>{JSON.stringify(a.enrichment?.egrul ?? {}, null, 1)}</pre></div></div>
    {sd && <div className="card"><h3>Подсказка системы</h3><p>{sd.outcome}{sd.offer && <> — {money(sd.offer.amount_rub)}, {sd.offer.term_months} мес., {sd.offer.rate_percent}%</>}</p></div>}
    {canDecide && <div className="card"><h2>Решение</h2><label htmlFor="o">Что решаем</label><select id="o" value={d.outcome} onChange={e => setD({ ...d, outcome: e.target.value })}>
      <option value="OFFER">Одобрить</option><option value="COUNTER_OFFER">Одобрить на других условиях</option><option value="NEEDS_INFO">Запросить данные</option><option value="REJECTED">Отказать</option></select>
      {needsOffer && <div className="grid"><div><label htmlFor="am">Сумма, ₽</label><input id="am" type="number" value={d.amount} onChange={e => setD({ ...d, amount: e.target.value })} /></div><div><label htmlFor="tm">Срок, мес.</label><input id="tm" type="number" value={d.term} onChange={e => setD({ ...d, term: e.target.value })} /></div><div><label htmlFor="rt">Ставка, %</label><input id="rt" type="number" step="0.1" value={d.rate} onChange={e => setD({ ...d, rate: e.target.value })} /></div></div>}
      {d.outcome === 'NEEDS_INFO' && <><label htmlFor="in">Что запросить у клиента</label><input id="in" value={d.info} onChange={e => setD({ ...d, info: e.target.value })} /></>}
      <label htmlFor="cm">Комментарий (обязательно)</label><textarea id="cm" value={d.comment} onChange={e => setD({ ...d, comment: e.target.value })} />
      {err && <p className="err" role="alert">{err}</p>}<p><button disabled={d.comment.trim().length < 3} onClick={decide}>Сохранить решение</button></p></div>}
    <div className="card"><h3>История</h3><ol className="tl">{a.history?.map((h: any, i: number) => <li key={i}><StatusBadge s={h.to_status} /> <small>{h.actor_type} · {dt(h.created_at)}</small> {h.comment}</li>)}</ol></div></>;
}
