import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { api, setToken } from '../api/client';
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
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return <form className="card" onSubmit={submit} style={{ maxWidth: 420, margin: '40px auto' }}>
    <h1>{mode === 'in' ? 'Вход' : 'Регистрация'}</h1>
    <p className="muted">Подайте заявку на кредит для бизнеса онлайн и следите за решением в одном месте.</p>
    {mode === 'up' && <><label htmlFor="n">Ваше имя</label><input id="n" required value={f.full_name} onChange={set('full_name')} /></>}
    <label htmlFor="e">Электронная почта</label><input id="e" type="email" required value={f.email} onChange={set('email')} />
    <label htmlFor="p">Пароль {mode === 'up' && <small>(не короче 8 символов)</small>}</label><input id="p" type="password" minLength={8} required value={f.password} onChange={set('password')} />
    {err && <p className="err" role="alert">{err}</p>}
    <p><button disabled={busy}>{mode === 'in' ? 'Войти' : 'Создать аккаунт'}</button>{' '}
      <button type="button" className="sec" onClick={() => setMode(mode === 'in' ? 'up' : 'in')}>{mode === 'in' ? 'Регистрация' : 'У меня уже есть аккаунт'}</button></p>
    {import.meta.env.VITE_DEMO_MODE === 'true' && <small>Демо: client1@demo.local / Demo12345! — всё данные вымышленные.</small>}
  </form>;
}
