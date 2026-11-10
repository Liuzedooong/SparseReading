# SparseRead project website

Production website: https://sparseread.pages.dev/

The Astro + React site is deployed to Cloudflare Pages, independently of GitHub Pages.
Build inputs (benchmarks and claims) come from launch/claims.yaml, launch/cases/flagship.yaml
and the recorded demo sources. Their values are unchanged during this migration.

## Build

From the repository root:

~~~bash
cd website
npm ci
npm run build
~~~

Upload the contents of website/dist to the existing Cloudflare Pages project
named sparseread using Direct Upload, or deploy from that directory with:

~~~bash
npx wrangler pages deploy dist --project-name sparseread
~~~

Use your own Cloudflare login. The default site hostname is
https://sparseread.pages.dev/ and the base path is /, not /SparseReading/.

For a local review site with the draft-only review route:
SPARSEREAD_BASE=/ npm run review

Changing the hostname requires an Astro build with the new SPARSEREAD_SITE setting
and updated public/robots.txt, public/sitemap.xml and public/llms.txt.

The unobtrusive footer eye uses the third-party hits.sh service with a stable
key across deployments. It counts requests, not unique visitors; long-term
availability and data retention are dependent on that service.

The old GitHub Pages publishing workflow is now a build-only validation workflow.
