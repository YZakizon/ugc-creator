FROM node:20-bookworm-slim

WORKDIR /app

RUN npm install --global pnpm@9.15.0

COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile --ignore-scripts --reporter=append-only

COPY . .

EXPOSE 3010
