import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@alfalab/core-components-button';
import { Steps } from '@alfalab/core-components-steps';
import { Tag } from '@alfalab/core-components-tag';
import { SliderInput } from '@alfalab/core-components-slider-input';
import { AmountInput } from '@alfalab/core-components-amount-input';
import { Textarea } from '@alfalab/core-components-textarea';
import { Attach } from '@alfalab/core-components-attach';
import { Plate } from '@alfalab/core-components-plate';
import { Typography } from '@alfalab/core-components-typography';
import { Gap } from '@alfalab/core-components-gap';
import { api, Application, Product, money, payment } from '../api/client';
import { ErrorPlate, H1, H2, Hint } from './shared';
const PURPOSES = [['WORKING_CAPITAL', 'Закупки, зарплаты, текущие расходы'], ['EQUIPMENT', 'Купить оборудование'], ['URGENT_CASH', 'Нужны деньги срочно'], ['OTHER', 'Другое']];
const DOC_NAMES: Record<string, string> = { FINANCIAL_STATEMENT: 'Финансовая отчётность', SUPPLIER_INVOICE: 'Счёт поставщика', OTHER: 'Другое' };
const FIN = [['revenue_12m_rub', 'Выручка'], ['net_profit_12m_rub', 'Чистая прибыль'], ['existing_monthly_payments_rub', 'Платежи по текущим кредитам в месяц']] as const;
const Big = ({ children }: { children: React.ReactNode }) => <Typography.Text view="primary-large" weight="bold" tag="div">{children}</Typography.Text>;
export default function Wizard() {
  const nav = useNavigate(); const [step, setStep] = useState(0);
  const [products, setProducts] = useState<Product[]>([]); const [code, setCode] = useState('');
  const [purpose, setPurpose] = useState('');
  const [rec, setRec] = useState<{ product_code: string; explanation: string } | null>(null);
  const [amount, setAmount] = useState(1_000_000); const [term, setTerm] = useState(12);
  const [fin, setFin] = useState({ revenue_12m_rub: '', net_profit_12m_rub: '', existing_monthly_payments_rub: '0', purpose: '' });
  const [app, setApp] = useState<Application | null>(null); const [docs, setDocs] = useState<any[]>([]);
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { api<Product[]>('/products').then(setProducts).catch(e => setErr(e.message)); }, []);
  const p = products.find(x => x.code === code);
  const pick = (c: string) => { const pr = products.find(x => x.code === c)!; setCode(c); setAmount(Math.min(Math.max(amount, pr.min_amount_rub), pr.max_amount_rub)); setTerm(Math.min(Math.max(term, pr.min_term_months), pr.max_term_months)); };
  const recommend = async (k: string) => { setPurpose(k); try { const r = await api<any>('/products/recommend', { method: 'POST', json: { purpose: k } }); setRec(r); pick(r.product_code); } catch (e: any) { setErr(e.message); } };
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
    <H1>Новая заявка</H1>
    <div className="card scroll"><Steps activeStep={step + 1} isMarkCompletedSteps>{titles.map(t => <span key={t}>{t}</span>)}</Steps></div>
    <Hint>Черновик сохраняется автоматически — можно вернуться к нему позже.</Hint><Gap size={16} />
    <ErrorPlate text={err} />
    {step === 0 && <><div className="card"><H2>Для чего нужны деньги?</H2>
      <div className="row">{PURPOSES.map(([k, v]) => <Tag key={k} size={40} checked={purpose === k} onClick={() => recommend(k)}>{v}</Tag>)}</div>
      {rec && <><Gap size={16} /><div role="status"><Plate view="positive" rounded title={`Рекомендуем: ${products.find(x => x.code === rec.product_code)?.name ?? rec.product_code}`}>{rec.explanation}</Plate></div></>}</div>
      <H2>Или выберите сами</H2>
      <div className="grid">{products.map(x => <div key={x.code} role="button" tabIndex={0} aria-pressed={x.code === code} className={'card click' + (x.code === code ? ' picked' : '')} onClick={() => pick(x.code)} onKeyDown={e => e.key === 'Enter' && pick(x.code)}>
        <Typography.Title tag="h3" view="xsmall" font="system" weight="bold">{x.name}</Typography.Title><Hint>{x.description}</Hint><Gap size={12} />
        <Typography.Text view="primary-medium" tag="div">От {money(x.min_amount_rub)} до {money(x.max_amount_rub)}<br />На {x.min_term_months}–{x.max_term_months} мес.<br />Ставка от {x.base_rate_percent}% годовых</Typography.Text></div>)}</div></>}
    {step === 1 && p && <div className="card"><H2>{p.name}</H2>
      <div className="stack">
        <SliderInput block label="Сумма, ₽" min={p.min_amount_rub} max={p.max_amount_rub} step={10000} value={amount}
          onChange={(_, { value }) => setAmount(Math.min(Math.max(Number(value) || p.min_amount_rub, p.min_amount_rub), p.max_amount_rub))}
          steps={[money(p.min_amount_rub), money(p.max_amount_rub)]} />
        <SliderInput block label="Срок, мес." min={p.min_term_months} max={p.max_term_months} step={1} value={term}
          onChange={(_, { value }) => setTerm(Math.min(Math.max(Number(value) || p.min_term_months, p.min_term_months), p.max_term_months))}
          steps={[`${p.min_term_months} мес.`, `${p.max_term_months} мес.`]} />
      </div><Gap size={24} />
      <Hint>Примерный платёж в месяц</Hint><Typography.TitleResponsive tag="div" view="medium" font="system" weight="bold">≈ {money(payment(amount, term, rate))}</Typography.TitleResponsive>
      <Hint>При ставке {rate}% годовых. Точные условия банк назовёт после проверки: ставка зависит от оценки заявки.</Hint></div>}
    {step === 2 && <div className="card"><H2>Финансы за последние 12 месяцев</H2><Hint>Введите примерные суммы — по ним мы оценим, какой платёж вам по силам.</Hint><Gap size={16} />
      <div className="stack">
        {FIN.map(([k, l]) => <AmountInput key={k} label={l} block currency="RUR" minority={1} integersOnly positiveOnly={k === 'existing_monthly_payments_rub'}
          value={fin[k] === '' ? null : +fin[k]} onChange={(_, { value }) => setFin({ ...fin, [k]: value === null ? '' : String(value) })} />)}
        <Textarea label="На что нужны деньги (по желанию)" block autosize minRows={2} maxLength={500} showCounter value={fin.purpose} onChange={(_, { value }) => setFin({ ...fin, purpose: value })} />
      </div></div>}
    {step === 3 && <div className="card"><H2>Документы</H2>
      {(p?.required_documents.length ?? 0) === 0 ? <Hint>Для этого продукта документы не нужны.</Hint> : <div className="stack">{p!.required_documents.map(t => <div key={t}>
        <Typography.Text view="primary-medium" weight="medium" tag="div">{DOC_NAMES[t] ?? t}{docs.some(d => d.doc_type === t) && <span className="muted"> — загружено ✓</span>}</Typography.Text><Gap size={8} />
        <Attach buttonContent="Выбрать файл" noFileText="Файл не выбран" onChange={(_, { files }) => files[0] && upload(t, files[0])} /></div>)}</div>}</div>}
    {step === 4 && p && <div className="card"><H2>Проверьте заявку</H2>
      <div className="grid kv">
        <div><small>Продукт</small><Big>{p.name}</Big></div>
        <div><small>Сумма и срок</small><Big>{money(amount)} на {term} мес.</Big></div>
        <div><small>Выручка за 12 мес.</small><Big>{fin.revenue_12m_rub ? money(+fin.revenue_12m_rub) : '—'}</Big></div>
        <div><small>Чистая прибыль</small><Big>{fin.net_profit_12m_rub ? money(+fin.net_profit_12m_rub) : '—'}</Big></div>
      </div><Gap size={16} />
      {missing.length > 0 && <><Plate view="attention" rounded title={`Не хватает документов: ${missing.map(t => DOC_NAMES[t] ?? t).join(', ')}`}>Можно отправить и так — банк запросит их у вас.</Plate><Gap size={16} /></>}
      <Hint>После отправки вы увидите, как продвигается проверка.</Hint><Gap size={16} />
      <Button view="accent" loading={busy} onClick={submit}>Отправить на рассмотрение</Button></div>}
    <div className="row">{step > 0 && <Button view="secondary" onClick={() => setStep(step - 1)}>Назад</Button>}
      {step < 4 && <Button view="accent" loading={busy} disabled={step === 0 && !code} onClick={next}>Далее</Button>}</div>
  </>;
}
