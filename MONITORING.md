# Monitoring & Observability Setup for AIWIP

This document describes the logging and monitoring setup for the containerized application.

## Logging Configuration

All services use the `json-file` logging driver with rotation:
- **Max size**: 10MB per log file
- **Max files**: 3-5 rotated files per service
- Logs are stored in Docker's default location: `/var/lib/docker/containers/`

View logs:
```bash
# View logs for specific service
docker compose logs -f api

# View last 100 lines
docker compose logs --tail=100 api

# View logs with timestamps
docker compose logs -t api
```

## Resource Limits

Each service has CPU and memory limits configured:

| Service | CPU Limit | Memory Limit | CPU Reserved | Memory Reserved |
|---------|-----------|--------------|--------------|-----------------|
| API | 1.0 | 512MB | 0.5 | 256MB |
| Worker | 0.5 | 256MB | 0.25 | 128MB |
| Web | 0.5 | 256MB | 0.25 | 128MB |

View resource usage:
```bash
docker stats
```

## Health Checks

All services have health checks configured:

- **Postgres**: `pg_isready` check, 5s interval
- **Redis**: `redis-cli ping`, 5s interval
- **API**: HTTP GET to `/health`, 15s interval, 30s start period
- **Web**: HTTP GET to `/`, 15s interval, 30s start period

View health status:
```bash
docker compose ps
```

## Metrics & Monitoring (Optional)

To add Prometheus + Grafana monitoring:

1. Add Prometheus service to `docker-compose.yml`:
```yaml
prometheus:
  image: prom/prometheus:latest
  ports:
    - "9090:9090"
  volumes:
    - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
    - prometheus-data:/prometheus
```

2. Add Grafana for visualization:
```yaml
grafana:
  image: grafana/grafana:latest
  ports:
    - "3001:3000"
  volumes:
    - grafana-data:/var/lib/grafana
```

3. Instrument API with Prometheus client:
```bash
pip install prometheus-client
```

## Troubleshooting

### Check service status:
```bash
docker compose ps
```

### View service logs:
```bash
docker compose logs SERVICE_NAME
```

### Check for OOM (Out of Memory):
```bash
docker stats
docker inspect CONTAINER_ID | grep -i memory
```

### Monitor in real-time:
```bash
docker stats --no-stream=false
```

## Log Aggregation (Production)

For production deployments, consider:
- **ELK Stack** (Elasticsearch, Logstash, Kibana)
- **Loki** (Grafana's log aggregation)
- **Datadog** or **New Relic** (commercial SaaS)
- **Splunk**

To integrate Loki:
```yaml
loki:
  image: grafana/loki:latest
  ports:
    - "3100:3100"

# Update service logging drivers to use loki
api:
  logging:
    driver: loki
    options:
      loki-url: http://loki:3100/loki/api/v1/push
```
