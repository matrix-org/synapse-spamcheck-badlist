-- Insert an evil prefix into the table of links.
INSERT INTO image_filter.iwf_links (url) VALUES('evil.example.com') ON CONFLICT DO NOTHING;

-- Insert an evil md5 into the table of files.
-- This matches to `evil_file.bin` in this directory.
INSERT INTO image_filter.iwf_md5 (md5) VALUES('61b7964268dc353337a978f87bca72a6') ON CONFLICT DO NOTHING;
