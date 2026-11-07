# The real app's web UI as a production build (#263): `make up` in the main checkout starts it
# (127.0.0.1:5173), `make deploy` rebuilds it with the API, so the UI is always the deployed commit.
# Worktrees and the test instance keep the Vite dev server (`make web-up`).
#   build   - npm ci from the lock, then tsc + vite build into /web/dist
#   runtime - nginx (unprivileged, port 8080) serving dist/ and proxying /api/* to the api service
FROM node:22.23.3-alpine3.24@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build

WORKDIR /web
# .npmrc: legacy-peer-deps (D-15), so the install matches the lock.
COPY package.json package-lock.json .npmrc ./
# --ignore-scripts: no install hooks from the dependency tree run at build time.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
# Same-origin API through nginx's /api proxy, as the dev server does with web/.env.local.
# .env* files are kept out of the build context (.dockerignore), so nothing local leaks in.
ENV VITE_API_BASE=/api
RUN npm run build


FROM nginxinc/nginx-unprivileged:1.30.6-alpine3.24@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03 AS runtime

# OS security fixes released since the base was built (the same idea as the API's --pull), and no
# curl: nginx doesn't use it (the healthcheck uses busybox wget). Back to the image's nginx user.
USER root
RUN apk upgrade --no-cache && apk del --no-cache curl
USER 101

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
# Straight to nginx: the image's entrypoint scripts rewrite conf.d, which is read-only here.
ENTRYPOINT ["nginx", "-g", "daemon off;"]
