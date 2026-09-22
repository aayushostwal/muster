# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# Serve stage: nginx serves the static build on port 3000.
# VITE_API_URL is re-injected at container start (see docker-entrypoint.sh)
# since docker-compose passes it as a runtime env var, not a build arg, and
# Vite normally only inlines import.meta.env.* at build time.
FROM nginx:1.27-alpine AS serve
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/50-muster-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/50-muster-runtime-config.sh

EXPOSE 3000
