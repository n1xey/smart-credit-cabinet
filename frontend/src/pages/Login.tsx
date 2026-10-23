import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@alfalab/core-components-button';
import { Input } from '@alfalab/core-components-input';
import { Gap } from '@alfalab/core-components-gap';
import { useAuth } from '../auth';
import { errorText } from '../api/client';
import { ErrorPlate, H1, Hint } from './shared';
// Регистрации нет: кабинет для действующих клиентов банка, учётные записи заведены заранее (MVP.md, «Авторизация»)
export default function Login() {
  const { login } = useAuth(); const nav = useNavigate();
  const [f, setF] = useState({ email: '', password: '' });
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setBusy(true);
    try { const u = await login(f.email, f.password); nav(u.role === 'CLIENT' ? '/' : '/operator'); }
    catch (x) { setErr(errorText(x)); } finally { setBusy(false); }
  };
  const set = (k: string) => (_: unknown, { value }: { value: string }) => setF({ ...f, [k]: value });
  return <form className="card center" onSubmit={submit}>
    <H1>Вход в кабинет</H1>
    <Hint>Для клиентов банка: подайте заявку на кредит для бизнеса онлайн и следите за решением в одном месте. Войдите под учётной записью, которую вам выдал банк.</Hint>
    <Gap size={24} />
    <div className="stack">
      <Input label="Электронная почта" type="email" block required autoComplete="email" value={f.email} onChange={set('email')} />
      <Input label="Пароль" type="password" block required autoComplete="current-password" value={f.password} onChange={set('password')} />
    </div>
    <Gap size={16} />
    <ErrorPlate text={err} />
    <Button view="accent" type="submit" block loading={busy}>Войти</Button>
    {import.meta.env.VITE_DEMO_MODE === 'true' && <><Gap size={12} /><Hint>Демо: client1@demo.local … client7@demo.local или operator@demo.local, пароль Demo12345! Все данные вымышленные.</Hint></>}
  </form>;
}
