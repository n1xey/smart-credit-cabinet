import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, Application, Product, money, payment } from '../api/client';
import { Hint } from './shared';
const PURPOSES = [['WORKING_CAPITAL', 'Закупки, зарплаты, текущие расходы'], ['EQUIPMENT', 'Купить оборудование'], ['URGENT_CASH', 'Нужны деньги срочно'], ['OTHER', 'Другое']];
const DOC_NAMES: Record<string, string> = { FINANCIAL_STATEMENT: 'Финансовая отчётность', SUPPLIER_INVOICE: 'Счёт поставщика', OTHER: 'Другое' };
export default function Wizard() {
  const nav = useNavigate(); const [step, setStep] = useState(0);
  const [products, setProducts] = useState<Product[]>([]); const [code, setCode] = useState('');
  const [rec, setRec] = useState<{ product_code: string; explanation: string } | null>(null);
  const [amount, setAmount] = useState(1_000_000); const [term, setTerm] = useState(12);
  const [fin, setFin] = useState({ revenue_12m_rub: '', net_profit_12m_rub: '', existing_monthly_payments_rub: '0', purpose: '' });
  const [app, setApp] = useState<Application | null>(null); const [docs, setDocs] = useState<any[]>([]);
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { api<Product[]>('/products').then(setProducts).catch(e => setErr(e.message)); }, []);
  const p = products.find(x => x.code === code);
  const pick = (c: string) => { const pr = products.find(x => x.code === c)!; setCode(c); setAmount(Math.min(Math.max(amount, pr.min_amount_rub), pr.max_amount_rub)); setTerm(Math.min(Math.max(term, pr.min_term_months), pr.max_term_months)); };
  const recommend = async (purpose: string) => { try { const r = await api<any>('/products/recommend', { method: 'POST', json: { purpose } }); setRec(r); pick(r.product_code); } catch (e: any) { setErr(e.message); } };
  const body = () => ({ product_code: code, amount_rub: amount, term_months: term, purpose: fin.purpose || undefined,
    revenue_12m_rub: fin.revenue_12m_rub ? +fin.revenue_12m_rub : undefined, net_profit_12m_rub: fin.net_profit_12m_rub ? +fin.net_profit_12m_rub : undefined, existing_monthly_payments_rub: +fin.existing_monthly_payments_rub || 0 });
  const save = async () => { // автосохранение черновика при каждом шаге
    const a = app ? await api<Application>(`/applications/${app.id}`, { method: 'PATCH', json: body() }) : await api<Application>('/applications', { method: 'POST', json: body() });
    setApp(a); return a;
  };
  const next = async () => { setErr(''); setBusy(true); try { if (step >= 1) await save(); setStep(step + 1); } catch (e: any) { setErr(e.message); } finally { setBusy(false); } };
  const upload = async (type: string, file: File) => {
    setErr(''); const fd = new FormData(); fd.append('doc_type', type); fd.append('file', file);
    try { const d = await api<any>(`/applications/${app!.id}/documents`, { method: 'POST', body: fd }); setDocs([...docs, d]); } catch (e: any) { setErr(e.message); }
  };
  const submit = async () => {
    setBusy(true); setErr('');
    try { const id = app!.id; const key = crypto.randomUUID(); await api(`/applications/${id}/submit`, { method: 'POST', headers: { 'Idempotency-Key': key } }); nav(`/app/${id}`); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  const missing = (p?.required_documents ?? []).filter(t => !docs.some(d => d.doc_type === t));
  const rate = p?.base_rate_percent ?? 0;
  const titles = ['Продукт', 'Условия', 'Финансы', 'Документы', 'Проверка'];
  return <>
    <h1>Новая заявка</h1><p className="muted">Шаг {step + 1} из 5: {titles[step]}. Черновик сохраняется автоматически.</p>
    {err && <p className="err" role="alert">{err}</p>}
    {step === 0 && <><div className="card"><h2>Для чего нужны деньги?</h2><div className="row">{PURPOSES.map(([k, v]) => <button key={k} className="sec" onClick={() => recommend(k)}>{v}</button>)}</div>
      {rec && <p role="status"><strong>Рекомендуем: {products.find(x => x.code === rec.product_code)?.name}.</strong> {rec.explanation}</p>}</div>
      <div className="grid">{products.map(x => <button key={x.code} className="card" style={{ textAlign: 'left', color: 'inherit', background: x.code === code ? 'var(--line)' : 'var(--card)' }} onClick={() => pick(x.code)} aria-pressed={x.code === code}>
        <h3>{x.name}</h3><p className="muted">{x.description}</p>
        <p>От {money(x.min_amount_rub)} до {money(x.max_amount_rub)}<br />На {x.min_term_months}–{x.max_term_months} мес.<br />Ставка от {x.base_rate_percent}% годовых</p></button>)}</div></>}
    {step === 1 && p && <div className="card"><h2>{p.name}</h2>
      <label htmlFor="a">Сумма: <strong>{money(amount)}</strong></label><input id="a" type="range" min={p.min_amount_rub} max={p.max_amount_rub} step={10000} value={amount} onChange={e => setAmount(+e.target.value)} />
      <label htmlFor="t">Срок: <strong>{term} мес.</strong></label><input id="t" type="range" min={p.min_term_months} max={p.max_term_months} value={term} onChange={e => setTerm(+e.target.value)} />
      <p className="big">≈ {money(payment(amount, term, rate))} в месяц</p>
      <Hint>Это примерный платёж при ставке {rate}% годовых. Точные условия банк назовёт после проверки: ставка зависит от оценки заявки.</Hint></div>}
    {step === 2 && <div className="card"><h2>Финансы за последние 12 месяцев</h2><Hint>Введите примерные суммы в рублях — по ним мы оценим, какой платёж вам по силам.</Hint>
      {([['revenue_12m_rub', 'Выручка'], ['net_profit_12m_rub', 'Чистая прибыль'], ['existing_monthly_payments_rub', 'Платежи по текущим кредитам в месяц']] as const).map(([k, l]) =>
        <div key={k}><label htmlFor={k}>{l}</label><input id={k} type="number" min={0} value={fin[k]} onChange={e => setFin({ ...fin, [k]: e.target.value })} /></div>)}
      <label htmlFor="pu">На что нужны деньги <small>(по желанию)</small></label><textarea id="pu" maxLength={500} value={fin.purpose} onChange={e => setFin({ ...fin, purpose: e.target.value })} /></div>}
    {step === 3 && <div className="card"><h2>Документы</h2>
      {(p?.required_documents.length ?? 0) === 0 ? <p>Для этого продукта документы не нужны.</p> : p!.required_documents.map(t => <div key={t}><label htmlFor={t}>{DOC_NAMES[t] ?? t}</label>
        <input id={t} type="file" onChange={e => e.target.files?.[0] && upload(t, e.target.files[0])} />{docs.some(d => d.doc_type === t) && <small>✓ Загружено</small>}</div>)}</div>}
    {step === 4 && p && <div className="card"><h2>Проверьте заявку</h2>
      <p>{p.name}: <strong>{money(amount)}</strong> на {term} мес.</p><p>Выручка: {fin.revenue_12m_rub ? money(+fin.revenue_12m_rub) : '—'}; прибыль: {fin.net_profit_12m_rub ? money(+fin.net_profit_12m_rub) : '—'}</p>
      {missing.length > 0 && <p className="err">Не хватает документов: {missing.map(t => DOC_NAMES[t] ?? t).join(', ')}. Можно отправить и так — банк запросит их у вас.</p>}
      <p>После отправки вы увидите, как продвигается проверка.</p><button disabled={busy} onClick={submit}>Отправить на рассмотрение</button></div>}
    <div className="row">{step > 0 && <button className="sec" onClick={() => setStep(step - 1)}>Назад</button>}
      {step < 4 && <button disabled={busy || (step === 0 && !code)} onClick={next}>Далее</button>}</div>
  </>;
}
