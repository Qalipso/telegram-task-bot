# Docker Deployment Guide for AIWIP

This guide covers building, testing, and deploying the containerized AIWIP application.

## Quick Start (Local Development)

```bash
# Clone repo and install dependencies
git clone <repo>
cd aiwip
cp .env.example .env

# Start all services with hot-reload
docker compose -f docker-compose.dev.yml up -d

# View logs
docker compose -f docker-compose.dev.yml logs -f api

# Stop all services
docker compose -f docker-compose.dev.yml down
```

### Development Commands

```bash
# Run tests
docker compose -f docker-compose.dev.yml exec api pytest

# Run migrations
docker compose -f docker-compose.dev.yml exec api alembic upgrade head

# Access shell
docker compose -f docker-compose.dev.yml exec api python

# View database
docker compose -f docker-compose.dev.yml exec postgres psql -U aiwip -d aiwip
```

## Production Deployment

### 1. Build Images

```bash
# Build production images
docker compose build

# Or build specific image
docker build -t aiwip-api:1.0.0 -f api/Dockerfile .
```

### 2. Push to Registry

```bash
# Using Docker Hub
docker tag aiwip-api:latest myusername/aiwip-api:1.0.0
docker push myusername/aiwip-api:1.0.0

# Or use the script
./push.sh myregistry.azurecr.io 1.0.0
```

### 3. Deploy with Docker Compose

```bash
# Set production environment
export COMPOSE_PROJECT_NAME=aiwip-prod
export POSTGRES_PASSWORD=$(openssl rand -base64 32)
export SECRET_KEY=$(openssl rand -base64 32)

# Create .env.prod
cat > .env.prod << EOF
APP_ENV=production
LOG_LEVEL=WARNING
POSTGRES_USER=aiwip
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=aiwip
SECRET_KEY=$SECRET_KEY
TELEGRAM_API_ID=YOUR_API_ID
TELEGRAM_API_HASH=YOUR_API_HASH
TELEGRAM_PHONE=YOUR_PHONE
OPENAI_API_KEY=YOUR_KEY
EOF

# Start services
docker compose --file docker-compose.yml --env-file .env.prod up -d

# Verify
docker compose ps
docker compose logs -f api
```

### 4. Deploy to Kubernetes

Create `k8s-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aiwip-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: aiwip-api
  template:
    metadata:
      labels:
        app: aiwip-api
    spec:
      containers:
      - name: api
        image: myregistry/aiwip-api:1.0.0
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: aiwip-secrets
              key: database-url
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: aiwip-api
spec:
  selector:
    app: aiwip-api
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

Deploy:
```bash
kubectl create secret generic aiwip-secrets --from-env-file=.env.prod
kubectl apply -f k8s-deployment.yaml
```

## Scaling

### Horizontal Scaling (Multiple Workers)

```bash
# Scale worker service to 3 replicas
docker compose up -d --scale worker=3
```

### Vertical Scaling (More Resources)

Update `docker-compose.yml`:
```yaml
api:
  deploy:
    resources:
      limits:
        cpus: "2"
        memory: 1024M
```

## Monitoring & Logs

```bash
# View resource usage
docker stats

# View service logs with follow
docker compose logs -f api worker web

# Export logs
docker compose logs > logs.txt

# Check service health
docker compose ps

# Inspect service
docker inspect aiwip-api-1
```

## Troubleshooting

### Service won't start
```bash
docker compose logs api
docker compose ps
```

### Out of memory
```bash
docker stats
docker compose down
# Increase memory limits in docker-compose.yml
```

### Database connection issues
```bash
docker compose exec postgres psql -U aiwip -d aiwip -c "\dt"
```

### Port conflicts
```bash
# Find what's using port 8000
lsof -i :8000
# Change ports in docker-compose.yml
```

## Backup & Recovery

### Backup database
```bash
docker compose exec postgres pg_dump -U aiwip aiwip > backup.sql
```

### Restore database
```bash
docker compose exec -T postgres psql -U aiwip aiwip < backup.sql
```

### Backup volumes
```bash
docker run --rm -v aiwip_pgdata:/volume -v $(pwd):/backup \
  ubuntu tar czf /backup/pgdata.tar.gz -C /volume .
```

## Security Best Practices

- [ ] Use strong passwords for PostgreSQL (stored in secrets, not in .env)
- [ ] Set `LOG_LEVEL=WARNING` in production
- [ ] Use a secrets manager (Vault, AWS Secrets Manager, etc.)
- [ ] Run containers with read-only root filesystem where possible
- [ ] Use network policies to restrict inter-service communication
- [ ] Enable Docker content trust for image signing
- [ ] Scan images for vulnerabilities: `docker scan aiwip-api`
- [ ] Run security scans in CI/CD pipeline

## CI/CD Integration

The GitHub Actions workflow (`.github/workflows/ci-cd.yml`) automatically:
1. Builds images on push to main/develop
2. Runs tests against PostgreSQL & Redis
3. Pushes images to container registry on merge

Secrets to configure in GitHub:
- `DOCKER_USERNAME` and `DOCKER_PASSWORD` (or use GITHUB_TOKEN)
- `REGISTRY_URL`, `REGISTRY_USERNAME`, `REGISTRY_PASSWORD`

## Performance Tuning

### Database Connection Pooling
```yaml
api:
  environment:
    DATABASE_POOL_SIZE: "20"
    DATABASE_MAX_OVERFLOW: "10"
```

### Redis Caching
```yaml
redis:
  command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
```

### Nginx Reverse Proxy (Production)
```yaml
nginx:
  image: nginx:alpine
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
  depends_on:
    - api
    - web
```

## Support

For issues:
1. Check logs: `docker compose logs SERVICE_NAME`
2. Review `MONITORING.md` for observability
3. Check GitHub Actions workflow for CI/CD errors
4. Enable debug logging: `LOG_LEVEL=DEBUG`
