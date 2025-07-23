# News Scraper Docker Setup

This directory contains Docker configuration files for running the News Scraper application.

## Quick Start

1. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env file with your actual API keys and configuration
   ```

2. **Build and run with Docker Compose**:
   ```bash
   docker-compose up -d
   ```

3. **Access the application**:
   - Open your browser and go to `http://localhost:8280`
   - The MongoDB database will be available on `localhost:27017`

## Configuration

### Required Environment Variables

The following environment variables are **required** and must be set in your `.env` file:

- `AZURE_OPENAI_API_KEY`: Your Azure OpenAI API key
- `AZURE_OPENAI_ENDPOINT`: Your Azure OpenAI endpoint URL
- `AZURE_OPENAI_API_VERSION`: Azure OpenAI API version (default: 2024-02-01)

### Optional Environment Variables

- `BING_SUBSCRIPTION_KEY`: Bing Search API key for web search functionality
- `SERPER_API_KEY`: Serper API key (alternative search provider)
- `APIFY_API_TOKEN`: Apify API token for web crawling functionality
- `SSL_CERTFILE` and `SSL_KEYFILE`: SSL certificate files for HTTPS

## Services

### news-scraper
- **Port**: 8280
- **Description**: Main FastAPI application serving the news scraper interface
- **Health Check**: HTTP GET request to `/health` endpoint

### mongodb
- **Port**: 27017
- **Description**: MongoDB database for storing scraped content and tags
- **Database**: `adverse_news_screening`
- **Collections**: `web_contents`, `fc_tags`

## Docker Commands

### Build and start all services:
```bash
docker-compose up -d
```

### View logs:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f news-scraper
docker-compose logs -f mongodb
```

### Stop all services:
```bash
docker-compose down
```

### Stop and remove volumes (WARNING: This will delete all data):
```bash
docker-compose down -v
```

### Rebuild the application image:
```bash
docker-compose build news-scraper
```

## Data Persistence

- MongoDB data is persisted in a Docker volume named `mongodb_data`
- SSL certificates should be placed in the project root directory as `cert.pem` and `key.pem`

## Troubleshooting

### Check service health:
```bash
docker-compose ps
```

### Access MongoDB shell:
```bash
docker-compose exec mongodb mongosh
```

### Access application container:
```bash
docker-compose exec news-scraper bash
```

### Check application logs for errors:
```bash
docker-compose logs news-scraper
```

## Development

For development, you can override the command to enable auto-reload:

```bash
docker-compose run --rm -p 8280:8280 news-scraper python serv_fastapi.py
```

Or set `RELOAD=true` in your `.env` file.

## Security Notes

- The application runs as a non-root user inside the container
- SSL certificates are mounted as read-only volumes
- Environment variables should be kept secure and not committed to version control
- Consider using Docker secrets in production environments
