import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@alfalab/core-components-button';
import { Select } from '@alfalab/core-components-select';
import { Tag } from '@alfalab/core-components-tag';
import { Table } from '@alfalab/core-components-table';
import { Input } from '@alfalab/core-components-input';
import { Textarea } from '@alfalab/core-components-textarea';
import { Plate } from '@alfalab/core-components-plate';
import { Status } from '@alfalab/core-components-status';
import { Typography } from '@alfalab/core-components-typography';
import { Gap } from '@alfalab/core-components-gap';
import { api, Application, money, dt } from '../api/client';
import { ErrorPlate, H1, H2, Hint, LABEL, Loading, StatusBadge } from './shared';
const STATUSES = ['', 'MANUAL_REVIEW', 'NEEDS_INFO', 'SCORING', 'OFFER', 'COUNTER_OFFER', 'REJECTED'];
const OUTCOMES = [{ key: 'OFFER', content: 'Одобрить' }, { key: 'COUNTER_OFFER', content: 'Одобрить на других условиях' }, { key: 'NEEDS_INFO', content: 'Запросить данные' }, { key: 'REJECTED', content: 'Отказать' }];
const GRADE_COLOR: Record<string, 'green' | 'teal' | 'orange' | 'red'> = { A: 'green', B: 'teal', C: 'orange', D: 'orange', E: 'red' };
export default function Operator() {
  const nav = useNavigate();
  const [st, setSt] = useState('MANUAL_REVIEW'); const [mine, setMine] = useState(false); const [rows, setRows] = useState<Application[] | null>(null); const [err, setErr] = useState('');
  useEffect(() => { setRows(null); const q = new URLSearchParams(); if (st) q.set('status', st); if (mine) q.set('assigned_to_me', 'true');
    api<Application[]>(`/operator/queue?${q}`).then(setRows).catch(e => setErr(e.message)); }, [st, mine]);
  return <><H1>Очередь заявок</H1>
    <div className="row">{STATUSES.map(s => <Tag key={s} size={32} checked={st === s} onClick={() => setSt(s)}>{s ? LABEL[s] : 'Все'}</Tag>)}
      <span style={{ flex: 1 }} /><Tag size={32} view="filled" checked={mine} onClick={() => setMine(!mine)}>Только мои</Tag></div>
    <Gap size={16} /><ErrorPlate text={err} />
    <div className="scroll">{!rows ? <Loading /> : rows.length === 0 ? <div className="card"><Hint>В очереди пусто</Hint></div> : <Table>
      <Table.THead><Table.THeadCell>Компания</Table.THeadCell><Table.THeadCell>Сумма</Table.THeadCell><Table.THeadCell>Статус</Table.THeadCell><Table.THeadCell>Обновлена</Table.THeadCell></Table.THead>
      <Table.TBody>{rows.map(r => <Table.TRow key={r.id} onClick={() => nav(`/operator/${r.id}`)}>
        <Table.TCell><Link to={`/operator/${r.id}`}>{r.company_name ?? r.id.slice(0, 8)}</Link></Table.TCell><Table.TCell>{money(r.amount_rub)} / {r.term_months} мес.</Table.TCell>
        <Table.TCell><StatusBadge s={r.status} /></Table.TCell><Table.TCell>{dt(r.updated_at)}</Table.TCell></Table.TRow>)}</Table.TBody></Table>}</div></>;
}
export function OperatorCard() {
  const { id } = useParams(); const [a, setA] = useState<any>(null); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const [d, setD] = useState({ outcome: 'OFFER', comment: '', amount: '', term: '', rate: '', info: '' });
  const load = () => api<any>(`/operator/applications/${id}`).then(setA).catch(e => setErr(e.message)); useEffect(() => { load(); }, [id]);
  const take = async () => { try { setA(await api(`/operator/applications/${id}/take`, { method: 'POST' })); } catch (e: any) { setErr(e.message); } };
  const decide = async () => {
    setErr(''); setBusy(true); const json: any = { outcome: d.outcome, comment: d.comment };
    if (d.outcome === 'OFFER' || d.outcome === 'COUNTER_OFFER') json.offer = { amount_rub: +d.amount, term_months: +d.term, rate_percent: +d.rate };
    if (d.outcome === 'NEEDS_INFO') json.info_items = [{ code: 'OTHER', message: d.info || d.comment }];
    try { setA(await api(`/operator/applications/${id}/decision`, { method: 'POST', json })); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  if (!a) return err ? <ErrorPlate text={err} /> : <Loading />;
  const sc = a.scoring; const sd = a.suggested_decision; const canDecide = a.status === 'MANUAL_REVIEW'; const needsOffer = d.outcome === 'OFFER' || d.outcome === 'COUNTER_OFFER';
  const set = (k: keyof typeof d) => (_: unknown, { value }: { value: string }) => setD({ ...d, [k]: value });
  return <><Link to="/operator" className="muted">← Очередь</Link><Gap size={16} />
    <div className="card"><div className="row"><H1>{a.company?.name}</H1><StatusBadge s={a.status} /></div>
      <Typography.Text view="primary-medium" tag="p">ИНН {a.company?.inn} · {a.product_code}: {money(a.amount_rub)} на {a.term_months} мес.</Typography.Text>
      <Hint>Выручка {money(a.revenue_12m_rub ?? 0)} · прибыль {money(a.net_profit_12m_rub ?? 0)} · платежи {money(a.existing_monthly_payments_rub ?? 0)}/мес</Hint>
      {canDecide && !a.assigned_operator_id && <><Gap size={16} /><Button view="accent" size={40} onClick={take}>Взять в работу</Button></>}</div>
    {sc && <div className="card scroll"><div className="row"><H2>Скоринг: {sc.score} баллов</H2><Status view="contrast" color={GRADE_COLOR[sc.grade] ?? 'grey'} size={24}>Группа {sc.grade}</Status></div>
      {sc.knockouts?.length > 0 && <><Plate view="negative" rounded title={`Стоп-факторы: ${sc.knockouts.join(', ')}`} /><Gap size={12} /></>}
      <Table wrapper={false}><Table.THead><Table.THeadCell>Фактор</Table.THeadCell><Table.THeadCell>Значение</Table.THeadCell><Table.THeadCell>Баллы</Table.THeadCell><Table.THeadCell>Комментарий</Table.THeadCell></Table.THead>
        <Table.TBody>{sc.factors?.map((f: any) => <Table.TRow key={f.factor}><Table.TCell>{f.factor}</Table.TCell><Table.TCell>{f.value}</Table.TCell><Table.TCell>{f.points}/{f.max_points}</Table.TCell><Table.TCell>{f.comment}</Table.TCell></Table.TRow>)}</Table.TBody></Table></div>}
    <div className="grid"><div className="card"><H2>БКИ</H2><pre>{JSON.stringify(a.enrichment?.bki ?? {}, null, 1)}</pre></div><div className="card"><H2>ЕГРЮЛ</H2><pre>{JSON.stringify(a.enrichment?.egrul ?? {}, null, 1)}</pre></div></div>
    {sd && <><Plate view="common" rounded title="Подсказка системы">{LABEL[sd.outcome] ?? sd.outcome}{sd.offer && <> — {money(sd.offer.amount_rub)}, {sd.offer.term_months} мес., {sd.offer.rate_percent}%</>}</Plate><Gap size={16} /></>}
    {canDecide && <div className="card"><H2>Решение</H2><div className="stack">
      <Select label="Что решаем" block options={OUTCOMES} selected={d.outcome} onChange={({ selected }) => selected && setD({ ...d, outcome: selected.key })} />
      {needsOffer && <div className="grid"><Input label="Сумма, ₽" type="number" block value={d.amount} onChange={set('amount')} /><Input label="Срок, мес." type="number" block value={d.term} onChange={set('term')} /><Input label="Ставка, %" type="number" step="0.1" block value={d.rate} onChange={set('rate')} /></div>}
      {d.outcome === 'NEEDS_INFO' && <Input label="Что запросить у клиента" block value={d.info} onChange={set('info')} />}
      <Textarea label="Комментарий (обязательно)" block autosize minRows={3} value={d.comment} onChange={set('comment')} />
    </div><Gap size={16} />
      <ErrorPlate text={err} /><Button view="accent" loading={busy} disabled={d.comment.trim().length < 3} onClick={decide}>Сохранить решение</Button></div>}
    <div className="card"><H2>История</H2><ol className="tl">{a.history?.map((h: any, i: number) => <li key={i}><StatusBadge s={h.to_status} /> <Typography.Text view="primary-small" color="secondary">{h.actor_type} · {dt(h.created_at)}</Typography.Text>{h.comment && <Hint>{h.comment}</Hint>}</li>)}</ol></div></>;
}
