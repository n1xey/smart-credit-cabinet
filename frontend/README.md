# frontend (Участник 3)
React 18 + Vite + TypeScript. Без внешних CDN и шрифтов.
- `npm install` (создаст package-lock.json — закоммитить), `npm run dev` (порт 5173, /api проксируется на :8000)
- Mock без бэкенда: `npm run mock` (Prism на :4010), затем `VITE_API_URL=http://localhost:4010 npm run dev`
- Типы из контракта: `npm run gen:api` (после contract-PR Кирилла)
- Docker: `docker build -t alfa-frontend .` — nginx раздаёт статику и проксирует /api на сервис `backend:8000`
- Переменные: см. `.env.example` (VITE_API_URL, VITE_DEMO_MODE)
Зависимости для THIRD_PARTY_NOTICES: react, react-dom, react-router-dom (MIT), vite, @vitejs/plugin-react, typescript, openapi-typescript, @stoplight/prism-cli, образы node:20.17.0-alpine3.20, nginx:1.27.2-alpine.
