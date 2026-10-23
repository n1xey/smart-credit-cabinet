import { FormEvent, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@alfalab/core-components-button';
import { Input } from '@alfalab/core-components-input';
import { Select } from '@alfalab/core-components-select';
import { Plate } from '@alfalab/core-components-plate';
import { Gap } from '@alfalab/core-components-gap';
import { api, errorText, ApiError, Company as C } from '../api/client';
import { ErrorPlate, H1, Hint, Loading } from './shared';
const FORMS = [{ key: 'OOO', content: 'ООО' }, { key: 'IP', content: 'ИП' }];
const FIELDS: [keyof C, string][] = [['name', 'Название'], ['legal_form', 'Форма'], ['okved', 'ОКВЭД'], ['address', 'Адрес']];
const shown = (k: keyof C, v?: string) => k === 'legal_form' ? FORMS.find(f => f.key === v)?.content ?? v : v;
// Расхождения профиля с реестром (мок ЕГРЮЛ): по ним банк запросит уточнение (REGISTRY_MISMATCH)
export function registryDiff(profile: C, registry: C): { field: keyof C; label: string; ours?: string; registry?: string }[] {
  const norm = (v?: string) => (v ?? '').trim().toLowerCase();
  return FIELDS.filter(([k]) => registry[k] !== undefined && norm(profile[k]) !== norm(registry[k]))
    .map(([k, label]) => ({ field: k, label, ours: shown(k, profile[k]), registry: shown(k, registry[k]) }));
}
// Клиенты — действующие клиенты банка (ORGANIZER_QA.md): профиль приходит «из банка», здесь его сверяют с реестром по ИНН
export default function Company() {
  const nav = useNavigate(); const [c, setC] = useState<C | null>(null); const [fromBank, setFromBank] = useState(false);
  const [reg, setReg] = useState<C | null>(null); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { api<C>('/company').then(p => { setC(p); setFromBank(true); })
    .catch(e => { setC({ inn: '', name: '', legal_form: 'OOO' }); if (!(e instanceof ApiError && e.status === 404)) setErr(errorText(e)); }); }, []);
  if (!c) return err ? <ErrorPlate text={err} /> : <Loading />;
  const innOk = /^\d{10}(\d{2})?$/.test(c.inn);
  const check = async () => {
    setErr(''); setReg(null); setBusy(true);
    try { const r = await api<C>(`/company/lookup?inn=${c.inn}`); if (fromBank) setReg(r); else setC({ ...c, ...r }); }
    catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  };
  const diff = reg ? registryDiff(c, reg) : [];
  const save = async (e: FormEvent) => { e.preventDefault(); setErr(''); setBusy(true); try { await api('/company', { method: 'PUT', json: c }); nav('/apply'); } catch (x) { setErr(errorText(x)); setBusy(false); } };
  const set = (k: keyof C) => (_: unknown, { value }: { value: string }) => setC({ ...c, [k]: value });
  return <form className="card" onSubmit={save} style={{ maxWidth: 640 }}>
    <H1>Ваша компания</H1>
    <Hint>{fromBank ? 'Данные из банка: вы уже наш клиент. Сверьте их с реестром — если сведения разойдутся, банк попросит уточнить их при проверке заявки.' : 'Введите ИНН — остальное мы подставим из реестра.'}</Hint>
    <Gap size={24} />
    <div className="row" style={{ alignItems: 'flex-start' }}>
      <div style={{ flex: '1 1 240px' }}><Input label="ИНН" inputMode="numeric" block value={c.inn} onChange={set('inn')} disabled={fromBank}
        error={c.inn !== '' && !innOk ? 'ИНН — это 10 или 12 цифр' : undefined} hint={fromBank ? 'ИНН компании, закреплённой за вашей учётной записью' : '10 цифр для организации, 12 для ИП'} /></div>
      <Button view="secondary" size={56} disabled={!innOk} loading={busy} onClick={check}>{fromBank ? 'Сверить с реестром' : 'Найти по ИНН'}</Button>
    </div>
    {reg && <><Gap size={16} /><div role="status">{diff.length === 0
      ? <Plate view="positive" rounded title="Сведения совпадают с реестром" />
      : <Plate view="attention" rounded title="Сведения отличаются от реестра" buttons={<Button view="secondary" size={32} onClick={() => { setC({ ...c, ...reg }); setReg(null); }}>Взять данные из реестра</Button>}>
        <ul>{diff.map(d => <li key={d.field}>{d.label}: у нас «{d.ours || '—'}», в реестре «{d.registry}»</li>)}</ul></Plate>}</div></>}
    <Gap size={16} />
    <div className="stack">
      <Input label="Название" block required value={c.name} onChange={set('name')} />
      <Select label="Форма" block options={FORMS} selected={c.legal_form} onChange={({ selected }) => selected && setC({ ...c, legal_form: selected.key as C['legal_form'] })} />
      <Input label="Вид деятельности (ОКВЭД)" block value={c.okved ?? ''} onChange={set('okved')} hint="Например, 62.01 — разработка ПО" />
      <Input label="Адрес" block value={c.address ?? ''} onChange={set('address')} />
    </div>
    <Gap size={24} />
    <ErrorPlate text={err} />
    <Button view="accent" type="submit" disabled={!innOk} loading={busy}>Сохранить и перейти к заявке</Button>
  </form>;
}
