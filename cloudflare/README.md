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
- The initial version does not require D1, KV, Durable Objects, GitHub Actions, or Kaggle.

Default model: `@cf/zai-org/glm-4.7-flash`. Change `DEFAULT_MODEL` in `wrangler.jsonc` to another compatible Workers AI chat model.

## Deploy

1. Install Node.js and Wrangler on a computer with access to Cloudflare:
   `npm install -g wrangler`
2. Log in:
   `wrangler login`
3. From this directory, configure an access key before publishing:
   `npx wrangler secret put ACCESS_KEY`
   Choose a long random value. The same value is entered in the site's **הגדרות** dialog. If you intentionally want a public demo, omit this secret, but anyone who can reach the URL may use your Workers AI quota.
4. Deploy:
   `npx wrangler deploy`

The AI binding is declared in `wrangler.jsonc`. On first deployment, Cloudflare may ask you to enable Workers AI or accept its terms in the dashboard.

## Local development

`npx wrangler dev`

For local testing with a real Workers AI binding, use Wrangler's remote development mode if required by your account:
`npx wrangler dev --remote`

## Notes

- The model's own context window, output limit, and Cloudflare account quotas still apply.
- The browser keeps chat history locally; it is not synchronized across devices.
- Stopping the browser request aborts the client connection. It does not guarantee that Cloudflare has cancelled model computation already underway.
- Do not put Cloudflare API tokens or model provider credentials in `public/` or browser JavaScript.
