# Cloudflare AI Platform

A Cloudflare-only first-stage version of the multi-provider chat platform.

## Provider roadmap

- **Workers AI** — implemented and enabled.
- **Gemini API** — reserved in the UI; not implemented yet.
- **Kaggle Worker** — reserved in the UI; not implemented yet.

The current UI uses plain ES5-style JavaScript and XMLHttpRequest. It does not depend on fetch, modules, optional chaining, or browser-side streaming APIs. Streaming is read from XMLHttpRequest progress events, which is more compatible with older browsers.

## Architecture

- Cloudflare Worker serves the static site from `public/`.
- The Worker calls Workers AI through the `AI` binding.
- The model runs on the server; no provider key is exposed to the browser.
- Chat history is saved in the current browser's localStorage.
- The optional `ACCESS_KEY` secret protects the inference endpoint.
- The initial version does not require D1, KV, Durable Objects, or Kaggle. GitHub Actions can deploy it automatically.

Default model: `@cf/zai-org/glm-4.7-flash`. Change `DEFAULT_MODEL` in `wrangler.jsonc` to another compatible Workers AI chat model.

## Deploy with GitHub Actions (recommended)

The repository workflow `.github/workflows/deploy-cloudflare.yml` deploys this Worker and its static assets whenever changes under `cloudflare/` are pushed to `main`. It can also be started manually from the Actions tab.

Add these two repository secrets under **Settings → Secrets and variables → Actions**:

- `CLOUDFLARE_API_TOKEN` — a Cloudflare API token scoped to this account with the **Edit Cloudflare Workers** permission.
- `CLOUDFLARE_ACCOUNT_ID` — the account ID for the Cloudflare account where the Worker should be deployed.

Never commit the API token to the repository. The account ID is `0a06a40f499b79a49a611c033382ff18` for the account inspected during setup.

After adding the secrets, merge this branch into `main` (or push a later change to `cloudflare/`). The workflow will deploy `unisocsu-ai-platform` and print its `workers.dev` URL in the Actions log. The first deployment may require enabling Workers AI or accepting its terms in the Cloudflare dashboard.

## Manual deploy (alternative)

1. Install Node.js and Wrangler: `npm install -g wrangler`.
2. Log in: `wrangler login`.
3. From the repository root, run: `npx wrangler deploy --config cloudflare/wrangler.jsonc`.
4. To configure an access key before publishing, run: `npx wrangler secret put ACCESS_KEY --config cloudflare/wrangler.jsonc`. Choose a long random value and enter the same value in the site's **הגדרות** dialog. If you omit this secret, anyone who can reach the URL may use your Workers AI quota.

The AI binding is declared in `wrangler.jsonc`.

## Local development

`npx wrangler dev`

For local testing with a real Workers AI binding, use Wrangler's remote development mode if required by your account:
`npx wrangler dev --remote`

## Notes

- The model's own context window, output limit, and Cloudflare account quotas still apply.
- The browser keeps chat history locally; it is not synchronized across devices.
- Stopping the browser request aborts the client connection. It does not guarantee that Cloudflare has cancelled model computation already underway.
- Do not put Cloudflare API tokens or model provider credentials in `public/` or browser JavaScript.
