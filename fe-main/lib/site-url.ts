/**
 * The site's public origin, which Open Graph and Twitter image URLs are
 * resolved against. Link previews need them absolute.
 *
 * NEXT_PUBLIC_SITE_URL wins when set. Otherwise, on Vercel, the production
 * domain it exposes as VERCEL_PROJECT_PRODUCTION_URL (a bare host), so a link
 * to the deployed site previews correctly without configuring anything.
 */
export function siteUrl(env: Record<string, string | undefined> = process.env): string {
  if (env.NEXT_PUBLIC_SITE_URL) return env.NEXT_PUBLIC_SITE_URL;
  if (env.VERCEL_PROJECT_PRODUCTION_URL) return `https://${env.VERCEL_PROJECT_PRODUCTION_URL}`;
  return "http://localhost:3000";
}
