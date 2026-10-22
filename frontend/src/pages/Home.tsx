import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@alfalab/core-components-button';
import { Typography } from '@alfalab/core-components-typography';
import { api, Application, money } from '../api/client';
import { ErrorPlate, H1, H2, Hint, Loading, ShowMore, StatusBadge, usePaged } from './shared';
const PRODUCT: Record<string, string> = { WORKING_CAPITAL: 'Оборотный кредит', EQUIPMENT: 'Кредит на оборудование', EXPRESS: 'Экспресс-кредит' };
export default function Home() {
  const nav = useNavigate();
  const { items: apps, total, err, busy, more } = usePaged<Application>('/applications'); const [feed, setFeed] = useState<any[]>([]);
  useEffect(() => { api<any[]>('/feed').then(setFeed).catch(() => {}); }, []);
  return <>
    <div className="row"><H1>Мои заявки</H1><span style={{ flex: 1 }} />{apps && apps.length > 0 && <Button view="accent" size={40} onClick={() => nav('/apply')}>Новая заявка</Button>}</div>
    <ErrorPlate text={err} />
    {!apps ? (err ? null : <Loading />) : apps.length === 0 ? <div className="card"><H2>Заявок пока нет</H2><Hint>Начните с подбора продукта — это займёт пару минут.</Hint><p><Button view="accent" onClick={() => nav('/apply')}>Подать заявку</Button></p></div> :
      <>{apps.map(a => <div key={a.id} className="card click row" role="link" tabIndex={0} onClick={() => nav(`/app/${a.id}`)} onKeyDown={e => e.key === 'Enter' && nav(`/app/${a.id}`)}>
        <div><Typography.Text view="primary-large" weight="bold" tag="div">{money(a.amount_rub)} на {a.term_months} мес.</Typography.Text>
          <Hint>{PRODUCT[a.product_code] ?? a.product_code}{a.company_name && <> · {a.company_name}</>}</Hint></div>
        <span style={{ flex: 1 }} /><StatusBadge s={a.status} /></div>)}
        {total > apps.length && <ShowMore shown={apps.length} total={total} busy={busy} onClick={more} />}</>}
    {feed.length > 0 && <><H2>Полезное для вас</H2><div className="grid">{feed.map(f => <div className="card" key={f.id}><Typography.Text view="primary-medium" weight="bold" tag="div">{f.title}</Typography.Text><Hint>{f.summary}</Hint></div>)}</div></>}
  </>;
}
