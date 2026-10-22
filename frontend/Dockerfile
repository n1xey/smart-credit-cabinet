FROM node:20.17.0-alpine3.20 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=/api/v1
# Демо-панель включена для показа жюри. TODO перед релизом: VITE_DEMO_MODE=false (панель знает демо-пароль)
ARG VITE_DEMO_MODE=true
ENV VITE_API_URL=$VITE_API_URL VITE_DEMO_MODE=$VITE_DEMO_MODE
RUN npm run build
FROM nginx:1.27.2-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
