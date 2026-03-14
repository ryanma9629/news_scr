// MongoDB initialization script
// This script creates the required database and collections

// Switch to the adverse_news_screening database
db = db.getSiblingDB('adverse_news_screening');

// Create the web_contents collection with indexes
// Note: URL is NOT globally unique - same URL can exist for different companies/languages
db.createCollection('web_contents');
db.web_contents.createIndex(
    { "company_name_lower": 1, "lang": 1, "url_lower": 1 },
    { unique: true, name: "unique_company_lang_url_idx" }
);
db.web_contents.createIndex({ "company_name": 1, "lang": 1 });
db.web_contents.createIndex({ "created_at": 1 });
db.web_contents.createIndex({ "session_id": 1 });

// Create the fc_tags collection with indexes
// Note: URL is NOT globally unique - same URL can exist for different companies/languages
db.createCollection('fc_tags');
db.fc_tags.createIndex(
    { "company_name_lower": 1, "lang": 1, "url_lower": 1 },
    { unique: true, name: "unique_company_lang_url_idx" }
);
db.fc_tags.createIndex({ "company_name": 1, "lang": 1 });
db.fc_tags.createIndex({ "created_at": 1 });
db.fc_tags.createIndex({ "session_id": 1 });

print('Database and collections initialized successfully');
