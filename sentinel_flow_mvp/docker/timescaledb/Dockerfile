# We start from our existing TimescaleDB image
FROM timescale/timescaledb:latest-pg15

# Switch to root to install system dependencies required for compiling pgvector
USER root

# Install build tools, PostgreSQL development headers, and LLVM19 (matching PG's build)
RUN apk add --no-cache \
    build-base \
    git \
    postgresql15-dev \
    clang19 \
    llvm19

# Clone the pgvector repository and compile it
RUN git clone --branch v0.5.1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make \
    && make install \
    && rm -rf /tmp/pgvector

# Switch back to the default postgres user for security
USER postgres
