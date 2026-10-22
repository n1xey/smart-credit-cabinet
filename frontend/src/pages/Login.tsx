import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@alfalab/core-components-button';
import { Input } from '@alfalab/core-components-input';
import { Gap } from '@alfalab/core-components-gap';
import { useAuth } from '../auth';
import { api, setToken } from '../api/client';
import { ErrorPlate, H1, Hint } from './shared';
export default function Login() {
  const { login } = useAuth(); const nav = useNavigate();
  const [mode, setMode] = useState<'in' | 'up'>('in'); const [f, setF] = useState({ email: '', password: '', full_name: '' });
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setBusy(true);
    try {
      if (mode === 'up') await api('/auth/register', { method: 'POST', json: f }).then((r: any) => setToken(r.access_token));
      const u = await login(f.email, f.password); nav(u.role === 'CLIENT' ? '/' : '/operator');
    } catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  };
  const set = (k: string) => (_: unknown, { value }: { value: string }) => setF({ ...f, [k]: value });
  return <form className="card center" onSubmit={submit}>
    <H1>{mode === 'in' ? 'Вход' : 'Регистрация'}</H1>
    <Hint>Подайте заявку на кредит для бизнеса онлайн и следите за решением в одном месте.</Hint>
    <Gap size={24} />
    <div className="stack">
      {mode === 'up' && <Input label="Ваше имя" block required value={f.full_name} onChange={set('full_name')} />}
      <Input label="Электронная почта" type="email" block required autoComplete="email" value={f.email} onChange={set('email')} />
      <Input label="Пароль" type="password" block required minLength={8} autoComplete={mode === 'in' ? 'current-password' : 'new-password'} hint={mode === 'up' ? 'Не короче 8 символов' : undefined} value={f.password} onChange={set('password')} />
    </div>
    <Gap size={16} />
    <ErrorPlate text={err} />
    <div className="stack">
      <Button view="accent" type="submit" block loading={busy}>{mode === 'in' ? 'Войти' : 'Создать аккаунт'}</Button>
      <Button view="transparent" block onClick={() => setMode(mode === 'in' ? 'up' : 'in')}>{mode === 'in' ? 'Зарегистрироваться' : 'У меня уже есть аккаунт'}</Button>
    </div>
    {import.meta.env.VITE_DEMO_MODE === 'true' && <><Gap size={12} /><Hint>Демо: client1@demo.local / Demo12345! — все данные вымышленные.</Hint></>}
  </form>;
}
