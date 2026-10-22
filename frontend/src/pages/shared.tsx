import { ReactNode, useCallback, useEffect, useState } from 'react';
import { Button } from '@alfalab/core-components-button';
import { apiPage, errorText } from '../api/client';
import { Status } from '@alfalab/core-components-status';
import { Typography } from '@alfalab/core-components-typography';
import { Plate } from '@alfalab/core-components-plate';
import { Spinner } from '@alfalab/core-components-spinner';
export const FINAL_OK = ['OFFER', 'COUNTER_OFFER', 'ACCEPTED', 'DISBURSED'];
export const FINAL_BAD = ['REJECTED', 'CANCELLED', 'EXPIRED'];
export const WAIT = ['SUBMITTED', 'DATA_CHECK', 'ENRICHMENT', 'SCORING', 'MANUAL_REVIEW', 'SIGNING', 'NEEDS_INFO', 'DRAFT'];
// Подписи берутся из контракта (STATE_MACHINE.md); на странице заявки основной текст всегда из API (status_title)
export const LABEL: Record<string, string> = { DRAFT: 'Черновик', SUBMITTED: 'Принята', DATA_CHECK: 'Проверка данных', NEEDS_INFO: 'Нужны уточнения', ENRICHMENT: 'Сверка сведений', SCORING: 'Оценка', MANUAL_REVIEW: 'Разбор специалистом', OFFER: 'Есть предложение', COUNTER_OFFER: 'Другие условия', ACCEPTED: 'Условия приняты', SIGNING: 'Подписание', DISBURSED: 'Выдача (демо)', REJECTED: 'Отказ', CANCELLED: 'Отменена', EXPIRED: 'Срок истёк' };
const color = (s: string) => FINAL_BAD.includes(s) ? 'red' : FINAL_OK.includes(s) ? 'green' : s === 'NEEDS_INFO' || s === 'SIGNING' ? 'orange' : s === 'DRAFT' ? 'grey' : 'blue';
export const StatusBadge = ({ s, title }: { s: string; title?: string }) =>
  <Status view="soft" color={color(s)} size={24}>{title ?? LABEL[s] ?? s}</Status>;
export const Hint = ({ children }: { children: ReactNode }) => <Typography.Text tag="div" view="primary-small" color="secondary">{children}</Typography.Text>;
export const H1 = ({ children }: { children: ReactNode }) => <Typography.TitleResponsive tag="h1" view="medium" font="system" weight="bold" style={{ margin: '0 0 16px' }}>{children}</Typography.TitleResponsive>;
export const H2 = ({ children }: { children: ReactNode }) => <Typography.Title tag="h2" view="small" font="system" weight="bold" style={{ margin: '0 0 12px' }}>{children}</Typography.Title>;
export const ErrorPlate = ({ text }: { text: string }) => text ? <div role="alert" style={{ marginBottom: 16 }}><Plate view="negative" rounded title={text} /></div> : null;
// Постраничный список: первая страница при смене path, «Показать ещё» догружает следующую
export function usePaged<T>(path: string) {
  const [items, setItems] = useState<T[] | null>(null); const [total, setTotal] = useState(0); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const load = useCallback(async (offset: number) => {
    setErr(''); setBusy(true);
    try { const p = await apiPage<T>(path, offset); setItems(prev => offset === 0 || !prev ? p.items : [...prev, ...p.items]); setTotal(p.total); }
    catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  }, [path]);
  useEffect(() => { setItems(null); load(0); }, [load]);
  return { items, total, err, busy, more: () => load(items?.length ?? 0), hasMore: (items?.length ?? 0) < total };
}
export const ShowMore = ({ shown, total, busy, onClick }: { shown: number; total: number; busy: boolean; onClick(): void }) =>
  <div className="row" style={{ marginBottom: 16 }}><Hint>Показано {shown} из {total}</Hint>{shown < total && <Button view="secondary" size={40} loading={busy} onClick={onClick}>Показать ещё</Button>}</div>;
export const Loading = () => <div className="row" role="status"><Spinner visible preset={24} /> <span className="muted">Загрузка…</span></div>;
