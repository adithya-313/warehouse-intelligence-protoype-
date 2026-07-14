/** @type {import('next').NextConfig} */
const nextConfig = {
  // NOTE: 'output: standalone' is for production images only.
  // In dev (docker-compose with volume mounts + `npx next dev`), this is ignored.
  output: 'standalone',
  async rewrites() {
    return [
      {
        // Docker DNS resolves the *service name* from docker-compose.yml, NOT container_name.
        // Service name is 'api', container_name is 'sentinel_api' — these are different.
        // Using 'sentinel_api' here caused ECONNREFUSED because it does not resolve on the bridge network.
        source: '/api/:path*',
        destination: 'http://api:8080/api/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
