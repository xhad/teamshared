# Marketplace install & publish

How teammates install **teamshared** from this repo, and how to submit to the
[Cursor Marketplace](https://cursor.com/marketplace).

## Install (team / git marketplace)

Once this repo is public (or teammates have access):

1. In Cursor: **Settings → Plugins → Add marketplace**
2. Paste the repository URL:

   ```
   https://github.com/xhad/actx
   ```

3. Install the plugin:

   ```
   /add-plugin teamshared
   ```

   Or use **Settings → Plugins** and enable **teamshared**.

4. Set environment variables **before launching Cursor** (shell profile or `.env`):

   ```bash
   export TEAMSHARED_URL=https://actx.teamshared.com/mcp   # or your host
   export TEAMSHARED_TOKEN=teamshared_...                    # from /get-token
   ```

5. Install [Bun](https://bun.sh) for continual-learning hooks.

6. **Developer: Reload Window** — confirm **Settings → MCP** shows `teamshared`.

### Local dev (symlink)

```bash
ln -sf "$(pwd)/plugins/teamshared" ~/.cursor/plugins/local/teamshared
```

## Prerequisites for users

| Requirement | Why |
|---|---|
| teamshared server + token | MCP tools and `/state` API for continual-learning |
| `TEAMSHARED_URL` / `TEAMSHARED_TOKEN` | Plugin `mcp.json` reads these at Cursor launch |
| Bun | `stop` hook runs TypeScript via `bun run` |
| Open repo with `AGENTS.md` | Continual learning writes learned bullets there |

Get a token: open your server's `/get-token` page or ask an admin for an invite link.

## Publish to Cursor Marketplace (official listing)

Cursor reviews all marketplace plugins manually. Checklist before submitting at
[cursor.com/marketplace/publish](https://cursor.com/marketplace/publish):

- [ ] Repository is **public** and open source (MIT)
- [ ] `.cursor-plugin/marketplace.json` at repo root lists `plugins/teamshared`
- [ ] `plugins/teamshared/.cursor-plugin/plugin.json` is valid JSON with `name`, `version`, `description`, `author`, `license`, `logo`
- [ ] All component paths exist: `rules/`, `skills/*/SKILL.md`, `agents/*.md`, `hooks/hooks.json`, `mcp.json`
- [ ] Every skill/agent has YAML frontmatter (`name`, `description`)
- [ ] `README.md` covers install, env vars, and what the plugin does
- [ ] `LICENSE` and `CHANGELOG.md` present
- [ ] Logo committed at `assets/logo.svg`
- [ ] Test locally: symlink to `~/.cursor/plugins/local/teamshared`, reload, verify MCP + hooks

### Validate locally

```bash
./scripts/validate-teamshared-plugin.sh
```

### Submission notes

- Put **Sapien** in the manifest `author.name` field (company name).
- In the submission description, mention: requires external teamshared server + bearer token; includes forked continual-learning hook (MIT, attributed in LICENSE).
- Alternative first step: list on [cursor.directory](https://cursor.directory) while waiting for official marketplace review.

## Repo layout (marketplace)

```
actx/
├── .cursor-plugin/
│   └── marketplace.json       # indexes plugins/teamshared
└── plugins/
    └── teamshared/
        ├── .cursor-plugin/plugin.json
        ├── mcp.json
        ├── rules/teamshared.mdc
        ├── skills/
        ├── agents/
        ├── hooks/
        ├── assets/logo.svg
        ├── README.md
        ├── CHANGELOG.md
        └── LICENSE
```
