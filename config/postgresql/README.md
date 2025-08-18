# PostgreSQL Setup for Adverse News Screening

This directory contains PostgreSQL configuration and setup files for the adverse news screening application.

## Quick Setup

### 1. Install PostgreSQL

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

**CentOS/RHEL:**
```bash
sudo yum install postgresql postgresql-server postgresql-contrib
sudo postgresql-setup initdb
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**macOS:**
```bash
brew install postgresql
brew services start postgresql
```

**Docker:**
```bash
docker run --name postgres-adverse-news -e POSTGRES_PASSWORD=password -p 5432:5432 -d postgres:15
```

### 2. Create Database and User

Connect to PostgreSQL as superuser:
```bash
sudo -u postgres psql
```

Create database and user:
```sql
CREATE DATABASE adverse_news_screening;
CREATE USER news_app WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE adverse_news_screening TO news_app;
\q
```

### 3. Initialize Tables

Run the initialization script:
```bash
psql -U news_app -d adverse_news_screening -f config/postgresql/init-db.sql
```

Or connect and run manually:
```bash
psql -U news_app -d adverse_news_screening
\i config/postgresql/init-db.sql
\q
```

### 4. Configure Environment Variables

Update your `.env` file with PostgreSQL connection details:

```env
# PostgreSQL Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=adverse_news_screening
POSTGRES_USER=news_app
POSTGRES_PASSWORD=your_secure_password
POSTGRES_TAGS_TABLE=fc_tags
```

## Database Schema

The application uses the following table structure for storing tagging results:

```sql
CREATE TABLE fc_tags (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    lang VARCHAR(10) NOT NULL,
    url TEXT NOT NULL,
    method VARCHAR(50) NOT NULL,
    llm_name VARCHAR(100) NOT NULL,
    crime_type VARCHAR(255),
    probability VARCHAR(50),
    modified_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_name, lang, url, method, llm_name)
);
```

## Key Features

- **Automatic Table Creation**: The application automatically creates tables and indexes if they don't exist
- **Upsert Operations**: Duplicate records are automatically updated instead of creating conflicts
- **Performance Optimized**: Includes indexes on commonly queried columns
- **Thread Safe**: Uses connection-per-request pattern for thread safety
- **Error Handling**: Graceful fallback if PostgreSQL is unavailable

## Monitoring

You can monitor the tagging results with these queries:

### Recent tagging activity:
```sql
SELECT company_name, lang, method, llm_name, COUNT(*) as tag_count, 
       MAX(modified_date) as last_update
FROM fc_tags 
WHERE modified_date >= NOW() - INTERVAL '24 hours'
GROUP BY company_name, lang, method, llm_name
ORDER BY last_update DESC;
```

### Crime type distribution:
```sql
SELECT crime_type, probability, COUNT(*) as count
FROM fc_tags 
GROUP BY crime_type, probability
ORDER BY count DESC;
```

### Company-specific analysis:
```sql
SELECT company_name, lang, crime_type, COUNT(*) as articles
FROM fc_tags 
WHERE company_name ILIKE '%company_name%'
GROUP BY company_name, lang, crime_type
ORDER BY articles DESC;
```

## Backup and Maintenance

### Backup database:
```bash
pg_dump -U news_app adverse_news_screening > backup_$(date +%Y%m%d_%H%M%S).sql
```

### Restore database:
```bash
psql -U news_app -d adverse_news_screening < backup_20250818_120000.sql
```

### Clean old records (older than 90 days):
```sql
DELETE FROM fc_tags WHERE modified_date < NOW() - INTERVAL '90 days';
```

## Troubleshooting

### Connection Issues

1. **Check PostgreSQL is running:**
   ```bash
   sudo systemctl status postgresql
   ```

2. **Verify connection settings:**
   ```bash
   psql -U news_app -d adverse_news_screening -h localhost -p 5432
   ```

3. **Check pg_hba.conf for authentication method:**
   ```bash
   sudo nano /etc/postgresql/*/main/pg_hba.conf
   ```

### Permission Issues

1. **Grant necessary permissions:**
   ```sql
   GRANT CONNECT ON DATABASE adverse_news_screening TO news_app;
   GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE fc_tags TO news_app;
   GRANT USAGE, SELECT ON SEQUENCE fc_tags_id_seq TO news_app;
   ```

### Performance Issues

1. **Analyze table statistics:**
   ```sql
   ANALYZE fc_tags;
   ```

2. **Check index usage:**
   ```sql
   SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch 
   FROM pg_stat_user_indexes 
   WHERE tablename = 'fc_tags';
   ```

## Security Considerations

1. **Use strong passwords** for database users
2. **Limit network access** in pg_hba.conf
3. **Enable SSL/TLS** for production deployments
4. **Regular security updates** for PostgreSQL
5. **Monitor access logs** for suspicious activity

For more information, see the PostgreSQL documentation: https://www.postgresql.org/docs/
