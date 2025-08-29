-- PostgreSQL setup script for adverse news screening application
-- This script creates the database and table structure for storing tagging results

-- Create database (run this as a PostgreSQL superuser)
-- CREATE DATABASE adverse_news_screening;

-- Connect to the database and create the table structure
-- \c adverse_news_screening;

-- Create schema if it doesn't exist (optional - defaults to 'public')
-- You can customize the schema name using POSTGRES_SCHEMA environment variable
DO $$
BEGIN
    -- Create schema if POSTGRES_SCHEMA is set and not 'public'
    -- This block will be executed by the application, not the init script
    -- The init script uses 'public' schema by default
END $$;

-- Create the fc_tags table with proper schema in the public schema
-- The application will handle schema creation and table placement based on POSTGRES_SCHEMA
CREATE TABLE IF NOT EXISTS fc_tags (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    lang VARCHAR(10) NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    method VARCHAR(50) NOT NULL,
    llm_name VARCHAR(100) NOT NULL,
    crime_type VARCHAR(255),
    probability VARCHAR(50),
    modified_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id, company_name, lang, url, method, llm_name)
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS fc_tags_customer_company_lang_idx ON fc_tags (customer_id, company_name, lang);
CREATE INDEX IF NOT EXISTS fc_tags_url_idx ON fc_tags (url);
CREATE INDEX IF NOT EXISTS fc_tags_method_llm_idx ON fc_tags (method, llm_name);
CREATE INDEX IF NOT EXISTS fc_tags_modified_date_idx ON fc_tags (modified_date);

-- Create a user for the application (optional)
-- CREATE USER news_app WITH PASSWORD 'your_secure_password';
-- GRANT CONNECT ON DATABASE adverse_news_screening TO news_app;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE fc_tags TO news_app;
-- GRANT USAGE, SELECT ON SEQUENCE fc_tags_id_seq TO news_app;

-- Sample query to verify the setup
-- SELECT COUNT(*) FROM fc_tags;

-- Comments on table and columns
COMMENT ON TABLE fc_tags IS 'Stores financial crime tagging results for news articles';
COMMENT ON COLUMN fc_tags.customer_id IS 'Customer identifier for multi-tenant support';
COMMENT ON COLUMN fc_tags.company_name IS 'Name of the company being analyzed';
COMMENT ON COLUMN fc_tags.lang IS 'Language code (e.g., en-US, zh-CN)';
COMMENT ON COLUMN fc_tags.url IS 'URL of the news article';
COMMENT ON COLUMN fc_tags.title IS 'Title of the news article';
COMMENT ON COLUMN fc_tags.method IS 'Tagging method used (e.g., rag, all)';
COMMENT ON COLUMN fc_tags.llm_name IS 'Name of the LLM model used for tagging';
COMMENT ON COLUMN fc_tags.crime_type IS 'Type of crime detected or none';
COMMENT ON COLUMN fc_tags.probability IS 'Probability level (e.g., high, medium, low)';
COMMENT ON COLUMN fc_tags.modified_date IS 'Last modification timestamp';
COMMENT ON COLUMN fc_tags.created_date IS 'Record creation timestamp';
