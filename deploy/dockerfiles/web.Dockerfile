# Stage 1: Build
FROM node:20.11-alpine3.19 AS builder
WORKDIR /app

# 安装 pnpm
RUN corepack enable && corepack prepare pnpm@9 --activate

# 依赖层（利用缓存）
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/ packages/
RUN pnpm fetch

# 源码层
COPY apps/web/ apps/web/
RUN pnpm install --offline --frozen-lockfile
RUN pnpm --filter web build

# Stage 2: Serve
FROM nginx:1.25.4-alpine
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html
COPY deploy/dockerfiles/web-entrypoint.sh /web-entrypoint.sh
RUN chmod +x /web-entrypoint.sh
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
