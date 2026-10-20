import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate, Link, Outlet } from 'react-router-dom';
import './styles.css';
import { AuthProvider, useAuth } from './auth';
import { Role, api } from './api/client';
import Login from './pages/Login';
import Company from './pages/Company';
import Wizard from './pages/Wizard';
import ApplicationPage from './pages/ApplicationPage';
import Operator, { OperatorCard } from './pages/Operator';
import Home from './pages/Home';

function Guard({ roles }: { roles: Role[] }) {
  const { user, ready } = useAuth();
  if (!ready) return <main>Загрузка…</main>;
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to="/" replace />;
  return <Outlet />;
}
function Layout() {
  const { user, logout } = useAuth();
  return <>
    <header><div>
      <strong>Кредитный кабинет</strong>
      {user?.role === 'CLIENT' && <><Link to="/">Мои заявки</Link><Link to="/company">Компания</Link><Link to="/apply">Новая заявка</Link></>}
      {user && user.role !== 'CLIENT' && <Link to="/operator">Очередь заявок</Link>}
      <span className="sp" />
      {user && <><small>{user.email}</small><button className="sec" onClick={logout}>Выйти</button></>}
    </div></header>
    <main><Outlet /></main>
    {import.meta.env.VITE_DEMO_MODE === 'true' && <DemoPanel />}
  </>;
}
function DemoPanel() {
  const { login } = useAuth();
  const go = (e: string) => login(e, 'Demo12345!').then(() => (location.href = '/'));
  return <footer style={{ maxWidth: 960, margin: '0 auto', padding: 16 }}><details className="card"><summary>Демо-панель</summary>
    <div className="row" style={{ marginTop: 8 }}>
      {[1, 2, 3, 4, 5, 6, 7].map(n => <button key={n} className="sec" onClick={() => go(`client${n}@demo.local`)}>Клиент {n}</button>)}
      <button className="sec" onClick={() => go('operator@demo.local')}>Оператор</button>
      <button className="sec" onClick={() => go('admin@demo.local')}>Админ</button>
      <button className="sec" onClick={() => go('admin@demo.local').then(() => api('/dev/reset-demo', { method: 'POST' }))}>Сбросить демо-данные</button>
    </div></details></footer>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><BrowserRouter><AuthProvider><Routes>
  <Route element={<Layout />}>
    <Route path="/login" element={<Login />} />
    <Route element={<Guard roles={['CLIENT']} />}>
      <Route path="/" element={<Home />} /><Route path="/company" element={<Company />} />
      <Route path="/apply" element={<Wizard />} /><Route path="/app/:id" element={<ApplicationPage />} />
    </Route>
    <Route element={<Guard roles={['OPERATOR', 'ADMIN']} />}>
      <Route path="/operator" element={<Operator />} /><Route path="/operator/:id" element={<OperatorCard />} />
    </Route>
  </Route>
</Routes></AuthProvider></BrowserRouter></StrictMode>);
