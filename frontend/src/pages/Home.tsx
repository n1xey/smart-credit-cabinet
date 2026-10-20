import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Application, money } from '../api/client';
import { StatusBadge } from './shared';
export default function Home() {
  const [apps, setApps] = useState<Application[] | null>(null); const [feed, setFeed] = useState<any[]>([]); const [err, setErr] = useState('');
  useEffect(() => { api<Application[]>('/applications').then(setApps).catch(e => setErr(e.message)); api<any[]>('/feed').then(setFeed).catch(() => {}); }, []);
  return <>
    <h1>Мои заявки</h1>
    {err && <p className="err" role="alert">{err}</p>}
    {!apps ? <p>Загрузка…</p> : apps.length === 0 ? <div className="card"><p>Заявок пока нет. Начните с подбора продукта — это займёт пару минут.</p><Link className="btn" to="/apply">Подать заявку</Link></div> :
      apps.map(a => <Link key={a.id} to={`/app/${a.id}`} style={{ textDecoration: 'none', color: 'inherit' }}><div className="card row"><div><strong>{money(a.amount_rub)}</strong> на {a.term_months} мес.<br /><small>{a.company_name}</small></div><span className="sp" style={{ flex: 1 }} /><StatusBadge s={a.status} /></div></Link>)}
    {feed.length > 0 && <><h2>Полезное для вас</h2><div className="grid">{feed.map(f => <div className="card" key={f.id}><strong>{f.title}</strong><p className="muted">{f.summary}</p></div>)}</div></>}
  </>;
}
