# Configuration

The add-on supports `amd64` and `aarch64`, publishes the web/API service on TCP 8790 and leaves the optional legacy receiver on TCP 9998 unpublished by default. The web UI is exposed with `http://[HOST]:[PORT:8790]`. Ingress is disabled because the hub's session cookies and configured public URL need a stable root URL.

Options are `admin_username`, `initial_password`, `timezone`, `public_url`, `allowed_hosts`, `wearer_name`, `enable_briefing`, `llm_base_url`, `llm_model` and `llm_api_key`. The first start requires an explicit password of 12–1024 characters. Add your HA hostname or LAN IPv4 address to `allowed_hosts`; configured `public_url` hostnames are added automatically. Host entries contain no scheme or port. The timezone must be an installed IANA timezone. Briefing is disabled unless explicitly enabled and configured; Home Assistant is expected to use the HACS pull integration and account-bound API tokens.

The image downloads the health-hub source from the immutable GitHub archive ref pinned in `Dockerfile` (`GRAVELEX_REF`). The add-on does not clone a floating branch. The source ref is a packaging input and should be updated deliberately alongside a release.

# Migration and restore

For an existing host, create a cold backup with the health-hub backup helper. Preserve the registry and every member database so server IDs and account ownership remain intact. Stop the old service, extract the database archive into the add-on data volume with ownership suitable for the container, start the add-on, and verify login, account history and API access. Keep the original volume and backup until verification is complete.

Do not claim Supervisor-level backup or migration success from source inspection alone; validate those operations on the target Home Assistant host.
