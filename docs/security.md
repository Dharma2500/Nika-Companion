# Security and privacy baseline

## Never commit

- API keys, access tokens, passwords or private certificates
- .env files or local provider configuration
- SQLite databases, WAL/SHM files, backups or chat histories
- World snapshots, coordinates, inventories or private server data
- Local logs and crash dumps that may contain personal information

The repository ignore rules cover common cases, but .gitignore is not a security boundary. Review staged files before every commit.

## Local data

The default data directory is ~/NIKA_DATA. Set NIKA_DATA to a dedicated path on the machine that runs the agent. Backups must remain local or in a storage location explicitly chosen by Vitaly.

## API credentials

Runtime API credentials will be loaded from a local secret store or environment variables in a later implementation. They must never be placed in the Fabric JAR, source files, dashboard frontend, Git history, logs or model prompts.

## Minecraft permissions

The mod must not bypass anti-cheat, access hidden server data, impersonate other players or execute actions outside the permissions available to the user. Capability checks are session-specific and fail closed.

## Local bridge

Before enabling actions, the bridge must bind to loopback only, authenticate its client, validate message schemas and size limits, reject replayed requests, and provide an emergency stop. No public network listener is required for the initial design.
