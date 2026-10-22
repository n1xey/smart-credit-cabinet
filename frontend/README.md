# frontend (Участник 3)
React 18 + Vite + TypeScript. Без внешних CDN и шрифтов.
- `npm install` (создаст package-lock.json — закоммитить), `npm run dev` (порт 5173, /api проксируется на :8000)
- Mock без бэкенда: `npm run mock` (Prism на :4010), затем `VITE_API_URL=http://localhost:4010 npm run dev`
- Типы из контракта: `npm run gen:api` (после contract-PR Кирилла)
- Docker: `docker build -t alfa-frontend .` — nginx раздаёт статику и проксирует /api на сервис `backend:8000`
- Переменные: см. `.env.example` (VITE_API_URL, VITE_DEMO_MODE)

## Дизайн-система
UI собран на [core-components](https://core-ds.github.io/core-components/master/) Альфа-Банка (`@alfalab/core-components-*`, MIT).
- Берём отдельные пакеты (button, input, select, slider-input, steps, table, plate, status, tag и т. д.), а не общий `@alfalab/core-components`: так меньше зависимостей.
- Цвета, тени и радиусы — CSS-переменные из `@alfalab/core-components-vars` (подключены в `src/main.tsx`). В `src/styles.css` только раскладка; свои цвета не заводим.
- Фирменный шрифт Styrene UI в пакетах не поставляется, компоненты сами откатываются на системный шрифт. Внешних CDN нет, всё работает офлайн.
- Тёмной темы нет: компоненты в светлой теме.
- Версии зафиксированы точно (`--save-exact`). Новый пакет ставить так: `npm i --save-exact @alfalab/core-components-<имя>@<версия>`, версия старше двух недель.

Зависимости для THIRD_PARTY_NOTICES: react, react-dom, react-router-dom (MIT), vite, @vitejs/plugin-react, typescript, openapi-typescript, @stoplight/prism-cli, образы node:20.17.0-alpine3.20, nginx:1.27.2-alpine.
Дизайн-система (MIT, © Alfa-Bank, https://github.com/core-ds/core-components): @alfalab/core-components-amount, -amount-input, -attach, -button, -divider, -gap, -input, -link, -plate, -radio-group, -select, -skeleton, -slider-input, -space, -spinner, -status, -steps, -table, -tag, -textarea, -typography, -vars и их транзитивные @alfalab/* пакеты.
