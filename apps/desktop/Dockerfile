# Stage 1: Build static Next.js assets
FROM node:20-alpine AS builder

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml* ./
COPY apps/desktop/package.json ./apps/desktop/

RUN pnpm install --frozen-lockfile=false

COPY apps/desktop ./apps/desktop

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_LOCAL_AUTH_TOKEN
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_LOCAL_AUTH_TOKEN=${NEXT_PUBLIC_LOCAL_AUTH_TOKEN}

RUN pnpm --filter desktop build

# Stage 2: Serve static files with ultra-lightweight Nginx
FROM nginx:alpine AS runner

COPY --from=builder /app/apps/desktop/out /usr/share/nginx/html
COPY apps/desktop/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:3000 || exit 1

CMD ["nginx", "-g", "daemon off;"]
