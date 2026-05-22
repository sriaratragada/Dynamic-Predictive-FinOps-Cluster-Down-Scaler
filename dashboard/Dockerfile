# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + built frontend
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend-builder /frontend/dist ./frontend/dist

USER 65534
EXPOSE 8090
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8090"]
