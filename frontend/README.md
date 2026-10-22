# frontend (Участник 3)
React 18 + Vite + TypeScript. Без внешних CDN и шрифтов.
- `npm install` (создаст package-lock.json — закоммитить), `npm run dev` (порт 5173, /api проксируется на :8000)
- **Посмотреть интерфейс без бэкенда:** `npm run demo` → http://localhost:5173. Встроенный мок (`src/api/mock.ts`, включается `VITE_API_URL=mock` из `.env.demo`) с синтетическими компаниями из `docs/SCORING.md`. Войти — кнопками в демо-панели внизу или `client1@demo.local` … `client7@demo.local`, `operator@demo.local` / `Demo12345!`. Заявки двигаются по статусам сами, можно пройти весь путь до «Средства выданы». Данные живут в памяти вкладки, перезагрузка страницы их сбрасывает. Исходы в моке упрощены и к скорингу продукта отношения не имеют.
- Mock по контракту: `npm run mock` (Prism на :4010), затем `VITE_API_URL=http://localhost:4010 npm run dev` — ответы-заглушки (`"string"`, нули), годится для проверки формата, не для показа.
- Демо-панель с реальным бэкендом работает, только когда загружен seed с демо-учётками; без него панель покажет подсказку.
- Типы из контракта: `npm run gen:api` (после contract-PR Кирилла)
- Docker: `docker build -t alfa-frontend .` — nginx раздаёт статику и проксирует /api на сервис `backend:8000`
- Переменные: см. `.env.example` (VITE_API_URL, VITE_DEMO_MODE). **Перед релизом** выключить демо-панель: `VITE_DEMO_MODE=false` (в `Dockerfile` она включена для показа жюри и знает демо-пароль).
- Тесты: `npm test` (Vitest + Testing Library): платёж, клиент API (If-Match, details из 422, пагинация), SSE, решение оператора, мастер, страница заявки по каждому `next_action`, демо-мок.

## Как фронт следует контракту v0.2
- Статус в реальном времени: `GET /applications/{id}/events` читается через `fetch` со стримом и заголовком `Authorization` (`src/api/events.ts`); токен в адрес не попадает. Пока поток жив, опрос с `ETag` идёт раз в 15 с, если поток недоступен — каждые 3 с.
- Списки (`/applications`, `/operator/queue`) постраничные: `limit`/`offset`, общее число из `X-Total-Count`, кнопка «Показать ещё».
- `If-Match` с версией заявки уходит в PATCH черновика, accept/decline и решении оператора; на `VERSION_CONFLICT` страница перечитывает заявку.
- Ошибки 422 показываются вместе со списком полей из `details`.
- Отказ оператора требует хотя бы один код причины из `docs/SCORING.md`; сумма и срок оффера — целые числа.

## Дизайн-система
UI собран на [core-components](https://core-ds.github.io/core-components/master/) Альфа-Банка (`@alfalab/core-components-*`, MIT).
- Берём отдельные пакеты (button, input, select, slider-input, steps, table, plate, status, tag и т. д.), а не общий `@alfalab/core-components`: так меньше зависимостей.
- Цвета, тени и радиусы — CSS-переменные из `@alfalab/core-components-vars` (подключены в `src/main.tsx`). В `src/styles.css` только раскладка; свои цвета не заводим.
- Фирменный шрифт Styrene UI в пакетах не поставляется, компоненты сами откатываются на системный шрифт. Внешних CDN нет, всё работает офлайн.
- Тёмной темы нет: компоненты в светлой теме.
- Версии зафиксированы точно (`--save-exact`). Новый пакет ставить так: `npm i --save-exact @alfalab/core-components-<имя>@<версия>`, версия старше двух недель.

Зависимости для THIRD_PARTY_NOTICES: react, react-dom, react-router-dom (MIT), vite, @vitejs/plugin-react, typescript, openapi-typescript, @stoplight/prism-cli, образы node:20.17.0-alpine3.20, nginx:1.27.2-alpine.
Дизайн-система (MIT, © Alfa-Bank, https://github.com/core-ds/core-components): @alfalab/core-components-amount, -amount-input, -attach, -button, -divider, -gap, -input, -link, -plate, -radio-group, -select, -skeleton, -slider-input, -space, -spinner, -status, -steps, -table, -tag, -textarea, -typography, -vars и их транзитивные @alfalab/* пакеты.
Тесты (только dev): vitest (MIT), jsdom (MIT), @testing-library/react, /dom, /jest-dom (MIT).
