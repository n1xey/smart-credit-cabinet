import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate, Link, NavLink, Outlet } from 'react-router-dom';
import '@alfalab/core-components-vars/colors-bluetint.css';
import '@alfalab/core-components-vars/shadows-bluetint.css';
import '@alfalab/core-components-vars/border-radius.css';
import '@alfalab/core-components-vars/gaps.css';
import '@alfalab/core-components-vars/common.css';
import './styles.css';
import { Button } from '@alfalab/core-components-button';
import { Typography } from '@alfalab/core-components-typography';
import { AuthProvider, useAuth } from './auth';
import { Role, api } from './api/client';
import { Loading } from './pages/shared';
import Login from './pages/Login';
import Company from './pages/Company';
import Wizard from './pages/Wizard';
import ApplicationPage from './pages/ApplicationPage';
import Operator, { OperatorCard } from './pages/Operator';
import Home from './pages/Home';

function Guard({ roles }: { roles: Role[] }) {
  const { user, ready } = useAuth();
  if (!ready) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to="/" replace />;
  return <Outlet />;
}
const nav = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : '');
function Layout() {
  const { user, logout } = useAuth();
  return <>
    <header><div className="bar">
      <Link className="logo" to="/"><i aria-hidden>А</i>Кредитный кабинет</Link>
      <nav>
        {user?.role === 'CLIENT' && <><NavLink className={nav} to="/" end>Мои заявки</NavLink><NavLink className={nav} to="/company">Компания</NavLink><NavLink className={nav} to="/apply">Новая заявка</NavLink></>}
        {user && user.role !== 'CLIENT' && <NavLink className={nav} to="/operator">Очередь заявок</NavLink>}
      </nav>
      <span className="sp" />
      {user && <><Typography.Text view="primary-small" color="secondary">{user.email}</Typography.Text><Button view="secondary" size={32} onClick={logout}>Выйти</Button></>}
    </div></header>
    <main><Outlet /></main>
    {import.meta.env.VITE_DEMO_MODE === 'true' && <DemoPanel />}
  </>;
}
function DemoPanel() {
  const { login } = useAuth();
  const go = (e: string) => login(e, 'Demo12345!').then(() => (location.href = '/'));
  return <footer className="demo"><details className="card"><summary>Демо-панель</summary>
    <div className="row" style={{ marginTop: 12 }}>
      {[1, 2, 3, 4, 5, 6, 7].map(n => <Button key={n} view="secondary" size={32} onClick={() => go(`client${n}@demo.local`)}>Клиент {n}</Button>)}
      <Button view="secondary" size={32} onClick={() => go('operator@demo.local')}>Оператор</Button>
      <Button view="secondary" size={32} onClick={() => go('admin@demo.local')}>Админ</Button>
      <Button view="outlined" size={32} onClick={() => go('admin@demo.local').then(() => api('/dev/reset-demo', { method: 'POST' }))}>Сбросить демо-данные</Button>
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
