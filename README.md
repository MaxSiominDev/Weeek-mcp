# weeek-mcp

Paste a [Weeek](https://weeek.net) task link into your AI assistant to read the
whole task: its title, description, comments, and any attached screenshots.

Built for one workflow: getting screenshots from Weeek into a chat without
downloading and uploading them by hand.

## What it does and does not do

| | |
|---|---|
| Reads a task from any Weeek link shape | yes |
| Description | yes |
| Comments, in order, rendered as Markdown | yes |
| Screenshots and file attachments | downloaded to disk, paths returned |
| Images posted inside comments | yes |
| Anything else in Weeek (search, projects, boards, CRM) | **no, by design** |
| Writing anything back to Weeek | **no, this server is read-only** |

Comments are **required**, not optional. If the session cannot read them, the whole
call fails. If fewer comments are returned than Weeek reports, the output tells
you how many are missing.

## Install

Needs Python 3.14. The simplest way is [uv](https://docs.astral.sh/uv/getting-started/installation/),
which fetches Python itself:

```bash
uv tool install 'weeek-mcp[browser] @ git+https://github.com/MaxSiominDev/weeek-mcp'
```

pipx and plain pip install the same spec:

```bash
pipx install 'weeek-mcp[browser] @ git+https://github.com/MaxSiominDev/weeek-mcp'
pip install 'weeek-mcp[browser] @ git+https://github.com/MaxSiominDev/weeek-mcp'
```

The `[browser]` extra lets the server re-read the session from your browser on its
own when it lapses. Drop it only if you sign in with an email + password.

Then point your client at the server:

```jsonc
// claude_desktop_config.json / .mcp.json
{
  "mcpServers": {
    "weeek": {
      "command": "weeek-mcp"
    }
  }
}
```

Then sign in once using the command that matches how you log in to Weeek.

```bash
weeek-mcp login --from-browser   # recommended
weeek-mcp login                  # email + password
weeek-mcp login --cookie         # paste a cookie by hand
weeek-mcp doctor                 # check it worked
```

`--from-browser` reads the session from a browser where you're already logged in.
It uses Chrome by default; pass a browser name to use another, such as
`--from-browser arc`. This is the easiest option and works for Google/SSO accounts
that don't have a password. The first read triggers a one-time OS keychain
permission prompt. Approve it to continue.

## Why signing in is required

Everything this server reads comes from Weeek's internal API, the same one its web
app uses. That API authenticates requests with a browser session cookie. API tokens
aren't an alternative. Weeek restricted them to project owners, and even before
that, the internal API returned a 401 for every bearer-token scheme, so reading
comments has always required a session.

**Weeek sessions expire after about two hours** (`Set-Cookie: ... Max-Age=7200`).
Your setup needs a way to renew the session. There are three options.

### Read it from the browser: `weeek-mcp login --from-browser` (recommended)

Reads `weeek_session` directly from your browser's cookie store. The cookie is
`HttpOnly`, so page scripts can't access it, but it is stored in the browser's
database. No password or DevTools needed. While you remain logged in, the browser
keeps a live cookie, which the server can read again if its saved session expires.

Chromium browsers encrypt cookies with a key stored in the OS keychain. The first
read triggers a one-time permission prompt asking you to allow access.
If the browser has locked its cookie database, reading may fail. Close the browser
and try again.

Needs the `[browser]` extra from the install command above.

### Password accounts: `weeek-mcp login`

Signs in through Weeek's login endpoint and signs in again automatically when the
session expires. Your password is stored in the **OS keychain** (macOS Keychain,
GNOME Keyring, or Windows Credential Locker), never in a file.

Weeek limits sign-in to 5 attempts per window.

### SSO accounts: `weeek-mcp login --cookie`

If you log in with Google, your account has no password to use here. Instead, copy
the session cookie from a browser where you're already logged in.

1. Open `app.weeek.net` and log in.
2. Open DevTools → **Network**, then click something in the app to generate requests.
3. Select any request to `api.weeek.net` → **Request Headers** → copy the whole `Cookie:` line.

Use the Network tab, not the console. `weeek_session` is `HttpOnly`, so
`document.cookie` cannot read it.

**Copy the entire line.** It also contains `remember_app_*`, Laravel's remember-me
cookie, which lets Weeek sign you back in and issue a new session silently.
The server checks every response for a new session cookie and saves it. With
`remember_app_*` present, you only need to copy the cookies once. Without it, the
session expires after two hours. `weeek-mcp doctor` tells you which case applies.

That cookie gives access to your account. Treat it like a password. If it leaks,
log out of all Weeek sessions to invalidate it.

Cookies are stored in `~/.config/weeek-mcp/session` with mode `0600`.
`weeek-mcp logout` removes the session and any stored password.

## Attachments

Files are saved to `/tmp/weeek-mcp/{task_id}/` and returned as absolute paths,
never embedded in the response. Inline base64 counts against the host's tool-output
limit, and a single screenshot can exceed it. Returning a file also lets the client
resize the image for the model instead of leaving that decision to the server.

SVG and other formats that vision models cannot read are skipped.

## Stability

This server uses an **undocumented internal API**. It can break without notice
when Weeek changes its web app.

## License

MIT. See [NOTICE](NOTICE) for third-party attribution.