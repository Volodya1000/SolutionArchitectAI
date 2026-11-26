FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build
WORKDIR /app
RUN npm install --global pnpm@12.21.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm typecheck && pnpm build

FROM nginx:alpine@sha256:7fc0fb4af7bf006aeb31aea88069976060f8f0a0a86b667126742cc17f4e31ae
COPY frontend/nginx.conf /etc/nginx/templates/nginx.conf.template
COPY --chmod=755 frontend/container-defaults.envsh /docker-entrypoint.d/15-app-defaults.envsh
COPY --from=build /app/dist /usr/share/nginx/html
ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp/nginx NGINX_ENVSUBST_FILTER="^(BACKEND_PORT|FRONTEND_PORT)$"
RUN mkdir -p /tmp/nginx && chown 101:101 /tmp/nginx
USER 101
CMD ["nginx", "-c", "/tmp/nginx/nginx.conf", "-g", "daemon off;"]
