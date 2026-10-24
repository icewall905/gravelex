# GravelEx Health Hub Home Assistant add-on

This add-on packages the self-hosted GravelEx Health Hub for Home Assistant. It stores the registry, original owner history and per-member databases in the add-on's persistent `/data` volume. A fresh add-on has empty history; an existing hub can be migrated with a cold backup containing all SQLite databases.

Install it from Home Assistant **Settings → Add-ons → Add-on Store → ⋮ → Repositories** using `https://github.com/icewall905/gravelex`. This is a Supervisor add-on repository; the separate HACS integration is installed through HACS and is documented independently.

On first start, `admin_username` and `initial_password` create the bootstrap administrator. Set `initial_password` to a password of at least 12 characters before the first start; an empty password fails closed. The add-on never prints passwords, API tokens or session secrets. Changing options later does not overwrite an existing registry account or persistent secrets. Use the dashboard's household account controls or the in-container password reset procedure for existing accounts.

Open the web UI at the configured port 8790. Add the Home Assistant hostname or LAN IPv4 address you use to `allowed_hosts`; the hostname in `public_url` is also allowed automatically. The add-on does not use Supervisor authentication or ingress, so configure `public_url` and HTTPS before exposing it beyond a trusted host. Home Assistant access should use the account's scoped API token; legacy forwarding remains separately configured and is not enabled by add-on defaults.

Cold backups include the registry, original database, all `people/*.sqlite3` databases, deployment options and persistent secrets. Retain a backup before migration or restore, stop the add-on before replacing its data, and verify the restored history before deleting the original volume.
