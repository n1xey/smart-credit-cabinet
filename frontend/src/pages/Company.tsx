import { FormEvent, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@alfalab/core-components-button';
import { Input } from '@alfalab/core-components-input';
import { Select } from '@alfalab/core-components-select';
import { Plate } from '@alfalab/core-components-plate';
import { Gap } from '@alfalab/core-components-gap';
import { api, Company as C } from '../api/client';
import { ErrorPlate, H1, Hint } from './shared';
const FORMS = [{ key: 'OOO', content: 'ООО' }, { key: 'IP', content: 'ИП' }];
export default function Company() {
  const nav = useNavigate(); const [c, setC] = useState<C>({ inn: '', name: '', legal_form: 'OOO' });
  const [msg, setMsg] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { api<C>('/company').then(setC).catch(() => {}); }, []);
  const innOk = /^\d{10}(\d{2})?$/.test(c.inn);
  const lookup = async () => {
    setErr(''); setMsg(''); setBusy(true);
    try { setC(await api<C>(`/company/lookup?inn=${c.inn}`)); setMsg('Нашли компанию и заполнили данные. Проверьте их.'); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const save = async (e: FormEvent) => { e.preventDefault(); setErr(''); setBusy(true); try { await api('/company', { method: 'PUT', json: c }); nav('/apply'); } catch (x: any) { setErr(x.message); setBusy(false); } };
  const set = (k: keyof C) => (_: unknown, { value }: { value: string }) => setC({ ...c, [k]: value });
  return <form className="card" onSubmit={save} style={{ maxWidth: 640 }}>
    <H1>Ваша компания</H1><Hint>Введите ИНН — остальное мы подставим сами.</Hint>
    <Gap size={24} />
    <div className="row" style={{ alignItems: 'flex-start' }}>
      <div style={{ flex: '1 1 240px' }}><Input label="ИНН" inputMode="numeric" block value={c.inn} onChange={set('inn')}
        error={c.inn !== '' && !innOk ? 'ИНН — это 10 или 12 цифр' : undefined} hint="10 цифр для организации, 12 для ИП" /></div>
      <Button view="secondary" size={56} disabled={!innOk} loading={busy} onClick={lookup}>Найти по ИНН</Button>
    </div>
    {msg && <><Gap size={16} /><div role="status"><Plate view="positive" rounded title={msg} /></div></>}
    <Gap size={16} />
    <div className="stack">
      <Input label="Название" block required value={c.name} onChange={set('name')} />
      <Select label="Форма" block options={FORMS} selected={c.legal_form} onChange={({ selected }) => selected && setC({ ...c, legal_form: selected.key as C['legal_form'] })} />
      <Input label="Вид деятельности (ОКВЭД)" block value={c.okved ?? ''} onChange={set('okved')} hint="Например, 62.01 — разработка ПО" />
      <Input label="Адрес" block value={c.address ?? ''} onChange={set('address')} />
    </div>
    <Gap size={24} />
    <ErrorPlate text={err} />
    <Button view="accent" type="submit" disabled={!innOk} loading={busy}>Сохранить и продолжить</Button>
  </form>;
}
