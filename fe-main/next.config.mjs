/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit .next/standalone so the Docker image ships a self-contained server
  // instead of the full node_modules tree.
  output: "standalone",
};

export default nextConfig;
