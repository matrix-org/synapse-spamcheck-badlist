CREATE SCHEMA IF NOT EXISTS image_filter;

-- A table of lowercased urls.
CREATE TABLE IF NOT EXISTS image_filter.iwf_links(
    -- Normalized URL:
    -- - lowercased
    -- - NO scheme
    -- - NO leading ://
    -- - host
    -- - user, password, port, path, parameters if available
    -- Examples:
    --  "example.com"
    --  "user@example.com:5432/abc/def"
    url TEXT PRIMARY KEY NOT NULL,

    -- The date at which this entry was inserted.
    insertion_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- An index to be able to cleanup old entries if necessary.
CREATE INDEX ON image_filter.iwf_links (insertion_date);

-- A table of hashes of image contents.
CREATE TABLE IF NOT EXISTS image_filter.iwf_md5(
    -- MD5 of images.
    -- - hexdigested
    -- - lowercase
    -- Examples:
    -- "1e0e133830a78c8674aab524e8fd3720"
    -- "6fca125cd4c33a5e1ffcff6e5791ca00"
    md5 TEXT PRIMARY KEY NOT NULL,

    -- The date at which this entry was inserted.
    insertion_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- An index to be able to cleanup old entries if necessary.
CREATE INDEX ON image_filter.iwf_md5 (insertion_date);
