# Adverse News Screening

An intelligent news screening system powered by Large Language Models (LLMs) for KYC/CDD processes.

## Project Structure

```
news_scr/
├── README.md                     # This file
├── requirements.txt              # Python dependencies
├── .env                         # Environment variables (create from .env.example)
├── .env.example                 # Environment template
├── .gitignore                   # Git ignore rules
│
├── app/                         # Main application code
│   ├── __init__.py
│   ├── main.py                  # FastAPI server (main entry point)
│   ├── crawler.py               # Web crawling functionality
│   ├── docstore.py              # MongoDB document storage
│   ├── postgres_store.py        # PostgreSQL tagging storage
│   ├── query.py                 # Q&A with context
│   ├── summarization.py         # Document summarization
│   ├── tagging.py               # FC tagging for crime classification
│   └── websearch.py             # Web search engines integration
│
├── static/                      # Static web assets
│   ├── index.html               # Main web interface
│   ├── css/
│   │   └── news_scr.css        # Stylesheet
│   └── js/
│       └── news_scr.js         # JavaScript functionality
│
├── config/                      # Configuration files
│   ├── mongodb/
│   │   └── init-db.js          # MongoDB initialization script
│   ├── postgresql/
│   │   ├── init-db.sql         # PostgreSQL table setup
│   │   └── README.md           # PostgreSQL setup guide
│   └── ssl/
│       ├── cert.pem            # SSL certificate
│       ├── key.pem             # SSL private key
│       └── generate_ssl.py     # SSL certificate generator
│
├── docker/                      # Docker configuration
│   ├── Dockerfile              # Docker image definition
│   ├── docker-compose.yml      # Development compose file
│   ├── docker-compose.prod.yml # Production compose file
│   └── docker-compose.published.yml # Published image compose file
│
├── scripts/                     # Build and deployment scripts
│   ├── build.sh                # Build Docker image
│   ├── build-and-push.sh       # Build and push to registry
│   └── docker.sh               # Docker management script
│
└── docs/                        # Documentation
    ├── README.docker.md         # Docker-specific documentation
    └── DOCKER.md                # Docker setup guide
```

## Quick Start

### 1. Environment Setup

Copy the environment template and configure your API keys:

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 2. Using Docker (Recommended)

Build and start the application:

```bash
# Using the build script
./scripts/build.sh

# Start the application
docker-compose -f docker/docker-compose.yml up -d

# View logs
docker-compose -f docker/docker-compose.yml logs -f

# Stop the application
docker-compose -f docker/docker-compose.yml down
```

Or use the management script:

```bash
# Build, start, and manage the application
./scripts/docker.sh build
./scripts/docker.sh start
./scripts/docker.sh logs
./scripts/docker.sh status
./scripts/docker.sh stop
```

### 3. Manual Setup

If you prefer to run without Docker:

```bash
# Install dependencies
pip install -r requirements.txt

# Start the application
python -m app.main
```

### 4. Access the Application

- **Web Interface**: http://localhost:8280
- **API Documentation**: http://localhost:8280/docs
- **Health Check**: http://localhost:8280/api/health

## Features

- **Web Search**: Search for news articles using Google or Bing
- **Content Crawling**: Extract content from news URLs
- **FC Tagging**: Classify content for crime types using LLMs
- **Summarization**: Generate summaries of news articles
- **Q&A**: Ask questions about the content using RAG
- **Multi-LLM Support**: Azure OpenAI, DeepSeek, Qwen/Tongyi
- **Dual Storage**: MongoDB for content and metadata, PostgreSQL for tagging results
- **Session Management**: Browser-based sessions for data persistence

## Configuration

### Environment Variables

Key environment variables (see `.env.example` for complete list):

```bash
# Azure OpenAI
AZURE_OPENAI_API_KEY=your_azure_openai_key
AZURE_OPENAI_ENDPOINT=your_azure_endpoint

# DeepSeek
DEEPSEEK_API_KEY=your_deepseek_key

# Qwen/Tongyi
DASHSCOPE_API_KEY=your_dashscope_key

# Search APIs (optional)
BING_SUBSCRIPTION_KEY=your_bing_key
GOOGLE_SERPER_API_KEY=your_serper_key

# MongoDB
MONGO_URI=mongodb://localhost:27017

# PostgreSQL (for tagging results)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=adverse_news_screening
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password

# Server
HOST=0.0.0.0
PORT=8280
```

### PostgreSQL Setup

The application automatically saves all tagging results to PostgreSQL for persistence and analysis. PostgreSQL configuration is optional for MongoDB-only deployments.

#### Quick Setup:

1. **Install PostgreSQL:**
   ```bash
   # Ubuntu/Debian
   sudo apt install postgresql postgresql-contrib
   
   # Docker
   docker run --name postgres-adverse-news -e POSTGRES_PASSWORD=password -p 5432:5432 -d postgres:15
   ```

2. **Create database and user:**
   ```bash
   sudo -u postgres psql
   CREATE DATABASE adverse_news_screening;
   CREATE USER news_app WITH PASSWORD 'your_secure_password';
   GRANT ALL PRIVILEGES ON DATABASE adverse_news_screening TO news_app;
   \q
   ```

3. **Initialize tables:**
   ```bash
   psql -U news_app -d adverse_news_screening -f config/postgresql/init-db.sql
   ```

For detailed setup instructions, see [config/postgresql/README.md](config/postgresql/README.md).

### SSL Configuration

To enable HTTPS, place your SSL certificates in `config/ssl/`:
- `cert.pem` - SSL certificate
- `key.pem` - Private key

Or generate self-signed certificates:

```bash
python config/ssl/generate_ssl.py
```

## Development

### Project Structure Rationale

- **`app/`**: Contains all Python application code with relative imports
- **`static/`**: Web assets served by FastAPI
- **`config/`**: Configuration files separated by type
- **`docker/`**: All Docker-related files in one place
- **`scripts/`**: Build and deployment automation
- **`docs/`**: Documentation and guides

### Adding New Features

1. Place Python modules in `app/`
2. Use relative imports (e.g., `from .module import Class`)
3. Update `requirements.txt` for new dependencies
4. Update Docker configuration if needed

### Running Tests

```bash
# TODO: Add test framework and instructions
```

## Deployment

### Production Deployment

Use the production compose file:

```bash
docker-compose -f docker/docker-compose.prod.yml up -d
```

### Container Registry

Build and push to a container registry:

```bash
./scripts/build-and-push.sh --registry your-registry.com --push
```

## API Endpoints

- `POST /api/search` - Search for news articles
- `POST /api/crawler` - Crawl content from URLs
- `POST /api/tagging` - Perform FC tagging
- `POST /api/summary` - Summarize content
- `POST /api/qa` - Ask questions about content
- `GET /api/health` - Health check

## Troubleshooting

### Common Issues

1. **Port already in use**: Change `PORT` in `.env` or stop conflicting services
2. **MongoDB connection**: Ensure MongoDB is running and accessible
3. **API keys**: Verify all required API keys are set in `.env`
4. **SSL issues**: Check certificate paths and permissions

### Logs

View application logs:

```bash
# Docker
docker-compose -f docker/docker-compose.yml logs -f

# Or using the management script
./scripts/docker.sh logs
```

## Contributing

1. Follow the established project structure
2. Use relative imports in Python modules
3. Update documentation for new features
4. Test with Docker before submitting changes

## License

[Add your license information here]
