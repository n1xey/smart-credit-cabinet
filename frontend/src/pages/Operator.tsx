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
import { api, errorText, isVersionConflict, Application, money, dt } from '../api/client';
import { useAuth } from '../auth';
import { ErrorPlate, H1, H2, Hint, LABEL, Loading, ShowMore, StatusBadge, usePaged } from './shared';
const STATUSES = ['', 'MANUAL_REVIEW', 'NEEDS_INFO', 'SCORING', 'OFFER', 'COUNTER_OFFER', 'REJECTED'];
const OUTCOMES = [{ key: 'OFFER', content: 'Одобрить' }, { key: 'COUNTER_OFFER', content: 'Одобрить на других условиях' }, { key: 'NEEDS_INFO', content: 'Запросить данные' }, { key: 'REJECTED', content: 'Отказать' }];
// Коды причин отказа и тексты для клиента — дословно из docs/SCORING.md
export const REJECT_REASONS: Record<string, string> = {
  LOW_SCORE: 'Совокупная оценка заявки ниже требуемой', INSUFFICIENT_CAPACITY: 'Платёжеспособность не позволяет одобрить минимальную сумму продукта',
  BKI_OVERDUE_90: 'Есть длительная просрочка по действующим обязательствам', REGISTRY_NOT_ACTIVE: 'По данным реестра, компания не ведёт деятельность',
  NEGATIVE_REVENUE: 'Недостаточные показатели деятельности', AGE_TOO_LOW: 'Компания работает слишком недолго для этого продукта',
  PRODUCT_NOT_AVAILABLE: 'Этот продукт пока недоступен для вашей компании, попробуйте другой',
};
const REASON_OPTIONS = Object.entries(REJECT_REASONS).map(([key, text]) => ({ key, content: `${key} — ${text}` }));
const GRADE_COLOR: Record<string, 'green' | 'teal' | 'orange' | 'red'> = { A: 'green', B: 'teal', C: 'orange', D: 'orange', E: 'red' };
export interface DecisionForm { outcome: string; comment: string; amount: string; term: string; rate: string; info: string; reasons: string[] }
// Проверка формы до отправки — те же правила, что у OperatorDecisionRequest (422 на сервере)
export function validateDecision(d: DecisionForm): string | null {
  if (d.comment.trim().length < 3) return 'Добавьте комментарий: не короче 3 символов';
  if (d.outcome === 'OFFER' || d.outcome === 'COUNTER_OFFER') {
    if (!/^\d+$/.test(d.amount) || +d.amount <= 0) return 'Сумма — целое число рублей больше нуля';
    if (!/^\d+$/.test(d.term) || +d.term <= 0) return 'Срок — целое число месяцев больше нуля';
    if (!(+d.rate > 0)) return 'Укажите ставку больше нуля';
  }
  if (d.outcome === 'NEEDS_INFO' && !(d.info || d.comment).trim()) return 'Напишите, что запросить у клиента';
  if (d.outcome === 'REJECTED' && d.reasons.length === 0) return 'Выберите хотя бы одну причину отказа — клиент увидит её текст';
  return null;
}
export function decisionBody(d: DecisionForm) {
  const json: Record<string, unknown> = { outcome: d.outcome, comment: d.comment.trim() };
  if (d.outcome === 'OFFER' || d.outcome === 'COUNTER_OFFER') json.offer = { amount_rub: parseInt(d.amount, 10), term_months: parseInt(d.term, 10), rate_percent: Math.round(+d.rate * 100) / 100 };
  if (d.outcome === 'NEEDS_INFO') json.info_items = [{ code: 'OTHER', message: (d.info || d.comment).trim() }];
  if (d.outcome === 'REJECTED') json.reason_codes = d.reasons;
  return json;
}
export default function Operator() {
  const nav = useNavigate();
  const [st, setSt] = useState('MANUAL_REVIEW'); const [mine, setMine] = useState(false);
  const q = new URLSearchParams(); if (st) q.set('status', st); if (mine) q.set('assigned_to_me', 'true');
  const { items: rows, total, err, busy, more } = usePaged<Application>(`/operator/queue?${q}`);
  return <><H1>Очередь заявок</H1>
    <div className="row">{STATUSES.map(s => <Tag key={s} size={32} checked={st === s} onClick={() => setSt(s)}>{s ? LABEL[s] : 'Все'}</Tag>)}
      <span style={{ flex: 1 }} /><Tag size={32} view="filled" checked={mine} onClick={() => setMine(!mine)}>Только мои</Tag></div>
    <Gap size={16} /><ErrorPlate text={err} />
    <div className="scroll">{!rows ? (err ? null : <Loading />) : rows.length === 0 ? <div className="card"><Hint>В очереди пусто</Hint></div> : <Table>
      <Table.THead><Table.THeadCell>Компания</Table.THeadCell><Table.THeadCell>Сумма</Table.THeadCell><Table.THeadCell>Статус</Table.THeadCell><Table.THeadCell>Обновлена</Table.THeadCell></Table.THead>
      <Table.TBody>{rows.map(r => <Table.TRow key={r.id} onClick={() => nav(`/operator/${r.id}`)}>
        <Table.TCell><Link to={`/operator/${r.id}`}>{r.company_name ?? r.id.slice(0, 8)}</Link></Table.TCell><Table.TCell>{money(r.amount_rub)} / {r.term_months} мес.</Table.TCell>
        <Table.TCell><StatusBadge s={r.status} /></Table.TCell><Table.TCell>{dt(r.updated_at)}</Table.TCell></Table.TRow>)}</Table.TBody></Table>}</div>
    {rows && rows.length > 0 && <><Gap size={16} /><ShowMore shown={rows.length} total={total} busy={busy} onClick={more} /></>}</>;
}
export function OperatorCard() {
  const { id } = useParams(); const { user } = useAuth(); const [a, setA] = useState<any>(null); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const [d, setD] = useState<DecisionForm>({ outcome: 'OFFER', comment: '', amount: '', term: '', rate: '', info: '', reasons: [] });
  const load = () => api<any>(`/operator/applications/${id}`).then(setA).catch(e => setErr(errorText(e))); useEffect(() => { load(); }, [id]);
  const take = async () => { setErr(''); try { setA(await api(`/operator/applications/${id}/take`, { method: 'POST' })); } catch (e) { setErr(errorText(e)); load(); } };
  const decide = async () => {
    const problem = validateDecision(d); if (problem) { setErr(problem); return; }
    setErr(''); setBusy(true);
    try { setA(await api(`/operator/applications/${id}/decision`, { method: 'POST', json: decisionBody(d), ifMatch: a.version })); }
    catch (e) { setErr(errorText(e)); if (isVersionConflict(e)) load(); } finally { setBusy(false); }
  };
  if (!a) return err ? <ErrorPlate text={err} /> : <Loading />;
  const sc = a.scoring; const sd = a.suggested_decision; const needsOffer = d.outcome === 'OFFER' || d.outcome === 'COUNTER_OFFER';
  // Решение принимает только оператор, взявший заявку (иначе 409 CONFLICT)
  const review = a.status === 'MANUAL_REVIEW'; const mineNow = review && a.assigned_operator_id === user?.id; const takenByOther = review && a.assigned_operator_id && !mineNow;
  const set = (k: keyof DecisionForm) => (_: unknown, { value }: { value: string }) => setD({ ...d, [k]: value });
  return <><Link to="/operator" className="muted">← Очередь</Link><Gap size={16} />
    <div className="card"><div className="row"><H1>{a.company?.name}</H1><StatusBadge s={a.status} /></div>
      <Typography.Text view="primary-medium" tag="p">ИНН {a.company?.inn} · {a.product_code}: {money(a.amount_rub)} на {a.term_months} мес.</Typography.Text>
      <Hint>Выручка {money(a.revenue_12m_rub ?? 0)} · прибыль {money(a.net_profit_12m_rub ?? 0)} · платежи {money(a.existing_monthly_payments_rub ?? 0)}/мес</Hint>
      {review && !a.assigned_operator_id && <><Gap size={16} /><Button view="accent" size={40} onClick={take}>Взять в работу</Button></>}
      {takenByOther && <><Gap size={16} /><Plate view="attention" rounded title="Заявку уже рассматривает другой оператор" /></>}</div>
    {sc && <div className="card scroll"><div className="row"><H2>Скоринг: {sc.score} баллов</H2><Status view="contrast" color={GRADE_COLOR[sc.grade] ?? 'grey'} size={24}>Группа {sc.grade}</Status></div>
      {sc.knockouts?.length > 0 && <><Plate view="negative" rounded title={`Стоп-факторы: ${sc.knockouts.join(', ')}`} /><Gap size={12} /></>}
      <Table wrapper={false}><Table.THead><Table.THeadCell>Фактор</Table.THeadCell><Table.THeadCell>Значение</Table.THeadCell><Table.THeadCell>Баллы</Table.THeadCell><Table.THeadCell>Комментарий</Table.THeadCell></Table.THead>
        <Table.TBody>{sc.factors?.map((f: any) => <Table.TRow key={f.factor}><Table.TCell>{f.factor}</Table.TCell><Table.TCell>{f.value}</Table.TCell><Table.TCell>{f.points}/{f.max_points}</Table.TCell><Table.TCell>{f.comment}</Table.TCell></Table.TRow>)}</Table.TBody></Table></div>}
    <div className="grid"><div className="card"><H2>БКИ</H2><pre>{JSON.stringify(a.enrichment?.bki ?? {}, null, 1)}</pre></div><div className="card"><H2>ЕГРЮЛ</H2><pre>{JSON.stringify(a.enrichment?.egrul ?? {}, null, 1)}</pre></div></div>
    {sd && <><Plate view="common" rounded title="Подсказка системы">{LABEL[sd.outcome] ?? sd.outcome}{sd.offer && <> — {money(sd.offer.amount_rub)}, {sd.offer.term_months} мес., {sd.offer.rate_percent}%</>}</Plate><Gap size={16} /></>}
    {mineNow && <div className="card"><H2>Решение</H2><div className="stack">
      <Select label="Что решаем" block options={OUTCOMES} selected={d.outcome} onChange={({ selected }) => selected && setD({ ...d, outcome: selected.key })} />
      {needsOffer && <div className="grid"><Input label="Сумма, ₽" type="number" inputMode="numeric" min={1} step={1} block value={d.amount} onChange={set('amount')} /><Input label="Срок, мес." type="number" inputMode="numeric" min={1} step={1} block value={d.term} onChange={set('term')} /><Input label="Ставка, %" type="number" step="0.1" block value={d.rate} onChange={set('rate')} /></div>}
      {d.outcome === 'NEEDS_INFO' && <Input label="Что запросить у клиента" block value={d.info} onChange={set('info')} />}
      {d.outcome === 'REJECTED' && <Select label="Причины отказа (обязательно)" hint="Клиент увидит текст причины, внутренний скоринг ему не показывается" block multiple allowUnselect options={REASON_OPTIONS} selected={d.reasons}
        onChange={({ selectedMultiple }) => setD({ ...d, reasons: selectedMultiple.map(o => o.key) })} />}
      <Textarea label="Комментарий (обязательно)" aria-label="Комментарий (обязательно)" block autosize minRows={3} value={d.comment} onChange={set('comment')} />
    </div><Gap size={16} />
      <ErrorPlate text={err} /><Button view="accent" loading={busy} onClick={decide}>Сохранить решение</Button></div>}
    {!mineNow && <ErrorPlate text={err} />}
    <div className="card"><H2>История</H2><ol className="tl">{a.history?.map((h: any, i: number) => <li key={i}><StatusBadge s={h.to_status} /> <Typography.Text view="primary-small" color="secondary">{h.actor_type} · {dt(h.created_at)}</Typography.Text>{h.comment && <Hint>{h.comment}</Hint>}</li>)}</ol></div></>;
}
