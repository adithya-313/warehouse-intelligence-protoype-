/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://sentinel_api:8080/api/:path*', 
      },
    ]
  },
};

module.exports = nextConfig;
