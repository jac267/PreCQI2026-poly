FROM node:22-slim AS build
WORKDIR /bot
COPY package.json ./
RUN npm install
COPY tsconfig.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-slim
WORKDIR /bot
COPY --from=build /bot/node_modules ./node_modules
COPY --from=build /bot/dist ./dist
COPY package.json ./
CMD ["node", "dist/main.js"]
