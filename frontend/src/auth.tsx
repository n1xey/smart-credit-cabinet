import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { api, setToken, getToken, setUnauthorizedHandler, User } from './api/client';
interface Ctx { user: User | null; ready: boolean; login(e: string, p: string): Promise<User>; logout(): void }
const C = createContext<Ctx>(null!);
export const useAuth = () => useContext(C);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null); const [ready, setReady] = useState(false);
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    if (getToken()) api<User>('/auth/me').then(setUser).catch(() => setToken(null)).finally(() => setReady(true)); else setReady(true);
  }, []);
  const login = async (email: string, password: string) => {
    const r = await api<{ access_token: string; user: User }>('/auth/login', { method: 'POST', json: { email, password } });
    setToken(r.access_token); setUser(r.user); return r.user;
  };
  return <C.Provider value={{ user, ready, login, logout: () => { setToken(null); setUser(null); } }}>{children}</C.Provider>;
}
