FROM docker.m.daocloud.io/library/node:24.11.1-alpine AS build
ARG VITE_SERVICE_URL=http://localhost:8089
ARG VITE_ADMIN_URL=http://localhost:8088
ENV VITE_SERVICE_URL=${VITE_SERVICE_URL}
ENV VITE_ADMIN_URL=${VITE_ADMIN_URL}
WORKDIR /build/admin
COPY apps/admin-web/package*.json ./
RUN npm ci
COPY apps/admin-web/ ./
RUN npm run build
WORKDIR /build/service
COPY apps/service-web/package*.json ./
RUN npm ci
COPY apps/service-web/ ./
RUN npm run build
FROM docker.m.daocloud.io/library/nginx:1.28.0-alpine
COPY --from=build /build/admin/dist /usr/share/nginx/admin
COPY --from=build /build/service/dist /usr/share/nginx/service
COPY deploy/nginx-container.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 81

