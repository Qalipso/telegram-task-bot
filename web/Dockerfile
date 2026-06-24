FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:20-alpine

ENV NODE_ENV=production

RUN addgroup -g 1001 appuser && adduser -D -u 1001 -G appuser appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/package.json /app/package-lock.json* ./
RUN npm ci --omit=dev

COPY --from=builder --chown=appuser:appuser /app/.next ./.next

USER appuser

EXPOSE 3000
CMD ["npm", "start"]
