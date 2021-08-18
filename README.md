# Synapse badlist filter

A simple spam checker module for Synapse, designed to block upload of identified child sexual abuse
imagery and links to identified child sexual abuse websites.

This filter requires:
- a database of links of identified child sexual abuse websites (as published by e.g. the IWF);
- a database of MD5s of identified child sexual abuse imagery (as published by e.g. the IWF).

The filter:
- rejects any message containing a link that matches the database;
- rejects any upload containing a file that matches the database.


## Requirements

You need Synapse >= 1.29.0.

## Installation

In your Synapse python environment:
```bash
pip install git+https://github.com/matrix-org/synapse-spamcheck-badlist#egg=synapse-spamcheck-badlist
```

Then add to your `homeserver.yaml`:
```yaml
modules:
  - module: "synapse_spamcheck_badlist.BadListFilter"
    config:
      # The URL of the server using this filter.
      base_url: "https://example.matrix.org"
      # The name of the table containing links.
      # It MUST contain at least one value `url TEXT PRIMARY KEY NOT NULL`.
      links_table: "image_filter.iwf_links"
      # The name of the table containing MD5s
      # It MUST contain at least one value `md5 TEXT PRIMARY KEY NOT NULL`.
      md5_table: "image_filter.iwf_md5"
      # How often we should check for changes in the database, in seconds.
      pull_from_db_every_sec: 600
```

Synapse will need to be restarted to apply the changes. Links added to the database will be used within `pull_from_db_every_sec` second, while MD5s added to the database will be used immediately.
