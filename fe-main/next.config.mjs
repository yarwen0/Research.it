// NEXT_PUBLIC_* values are inlined at build time, and lib/api.ts falls back to
// a backend on 127.0.0.1. On Vercel that would ship a site whose every visitor
// calls their own machine, so a hosted build without the API URL stops here.
if (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error(
    "NEXT_PUBLIC_API_URL is not set. Add it to the Vercel project's environment variables " +
      "as the backend's public URL, then redeploy. See DEPLOYMENT.md.",
  );
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit .next/standalone so the Docker image ships a self-contained server
  // instead of the full node_modules tree.
  output: "standalone",
};

export default nextConfig;
