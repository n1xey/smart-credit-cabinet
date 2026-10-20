import { FormEvent, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, Company as C } from '../api/client';
import { Hint } from './shared';
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
  const set = (k: keyof C) => (e: any) => setC({ ...c, [k]: e.target.value });
  return <form className="card" onSubmit={save}>
    <h1>Ваша компания</h1><p className="muted">Введите ИНН — остальное мы подставим сами.</p>
    <label htmlFor="inn">ИНН <Hint>10 цифр для организации, 12 для ИП</Hint></label>
    <div className="row"><input id="inn" inputMode="numeric" value={c.inn} onChange={set('inn')} style={{ maxWidth: 240 }} aria-invalid={c.inn !== '' && !innOk} />
      <button type="button" disabled={!innOk || busy} onClick={lookup}>Найти по ИНН</button></div>
    {c.inn !== '' && !innOk && <p className="err">ИНН — это 10 или 12 цифр</p>}
    {msg && <p role="status">{msg}</p>}
    <label htmlFor="nm">Название</label><input id="nm" required value={c.name} onChange={set('name')} />
    <label htmlFor="lf">Форма</label><select id="lf" value={c.legal_form} onChange={set('legal_form')}><option value="OOO">ООО</option><option value="IP">ИП</option></select>
    <label htmlFor="ok">Вид деятельности (ОКВЭД)</label><input id="ok" value={c.okved ?? ''} onChange={set('okved')} />
    <label htmlFor="ad">Адрес</label><input id="ad" value={c.address ?? ''} onChange={set('address')} />
    {err && <p className="err" role="alert">{err}</p>}
    <p><button disabled={!innOk || busy}>Сохранить и продолжить</button></p>
  </form>;
}
