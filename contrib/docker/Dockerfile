# Dockerfile for Review Board.
#
# Copyright (C) 2020 Beanbag, Inc.
#
# Documentation on this Docker image is available at
# https://www.reviewboard.org/docs/manual/latest/admin/installation/docker/
#
# This can be built through Docker, as normal. The ./build.py script can help
# automate the multi-platform builds for the official Review Board Docker
# images.
#
# If building for multi-platform (amd64 and arm64), you will need at least
# one machine capable of arm64 builds (or supporting cross-compilation or
# emulation). A macOS machine is capable of both amd64 and arm64 builds.
#
# To build using a single machine capable of multiple architectures, first run:
#
#     $ docker buildx create --name rb-build --use
#
# That will create a single build environment (see `docker buildx ls`) with
# support for both.
#
# To build across multiple machines, run:
#
#     $ docker buildx create --name rb-build --platform linux/arm64
#     $ docker buildx create --name rb-build --platform linux/amd64 \
#              --append ssh://<user>@<host>
#
# (Change architectures as needed)
#
# Then, before building this image, run:
#
#     $ docker buildx use rb-build


##############################################################################
# Stage 1 of the build.
#
# We'll set up development support and compile any modules we need in a
# virtualenv. That will be copied in stage 2 to the destination image, without
# carrying all the development bloat.
#
# We're using Ubuntu (LTS release) rather than Alpine, due to better
# compatibility with compiled Python modules and a long support life.
#
# Alpine doesn't use glibc, and cannot benefit from pre-compiled wheels.
# See https://pythonspeed.com/articles/alpine-docker-python/
##############################################################################
FROM ubuntu:22.04 AS builder
MAINTAINER Beanbag, Inc. <support@beanbaginc.com>

# The version of Review Board this will install.
ARG REVIEWBOARD_VERSION

# Power Pack version to install.
#
# This can be in X.Y or X.Y.Z form.
ARG POWERPACK_VERSION=5.3

# Review Bot extension version to install.
#
# This can be in X.Y or X.Y.Z form.
ARG REVIEWBOT_VERSION=4.0

# Extra extension packages needed by the server.
#
# This is used only when building from *this* Dockerfile. Consumers should
# create a new Dockerfile that inherits from this one and installs packages
# themselves.
ARG EXTRA_PACKAGES=

# Build-specific environment variables.
ARG TARGETARCH

# Install all the base system-level packages needed by Review Board.
#
# We will be installing some packages (including most Python packages) via
# pip instead of apt-get.
RUN    set -ex \
    && export TERM=dumb \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get update -y \
    && apt-get install -y --no-install-recommends \
           build-essential \
           ca-certificates \
           libldap-common \
           curl \
           gnupg \
           libapr1-dev \
           libaprutil1-dev \
           libffi-dev \
           libssl-dev \
           libjpeg-dev \
           libmysqlclient-dev \
           libsasl2-dev \
           libsvn1 \
           libsvn-dev \
           libxml2-dev \
           libxmlsec1-dev \
           mysql-client \
           openssl \
           pkg-config \
           postgresql-client \
           python3.11-dev \
           sendmail \
           subversion \
           tzdata \
           virtualenv \
    && rm -rf /var/lib/apt/lists/*

# Add the Perforce apt repository.
#
# NOTE: Update the "deb" line when modifying the base Ubuntu version!
RUN    { curl https://package.perforce.com/perforce.pubkey | apt-key add -; } \
    && echo "deb http://package.perforce.com/apt/ubuntu bionic release" \
       > /etc/apt/sources.list.d/perforce.list

# Set up the environment for Python and scripts.
ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Set up a virtualenv for Review Board.
ENV VIRTUAL_ENV=/venv
RUN virtualenv -p python3.11 $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install Review Board and its Python dependencies.
#
# If any packages are provided in ./packages/ when building this, we'll
# prioritize those.
COPY ./packages /tmp/packages
RUN    set -ex \
    && pip3 install -U pip \
    && pip3 install \
           --no-cache-dir \
           gunicorn \
           gunicorn[gevent] \
           gunicorn[gthread] \
    && pip3 install \
           --no-cache-dir \
           --pre \
           --find-links /tmp/packages \
           ReviewBoard~=${REVIEWBOARD_VERSION} \
           ReviewBoardPowerPack~=${POWERPACK_VERSION} \
           reviewbot_extension~=${REVIEWBOT_VERSION} \
           ${EXTRA_PACKAGES} \
    && pip3 install \
           --no-cache-dir \
           'ReviewBoard[ldap]' \
           'ReviewBoard[mercurial]' \
           'ReviewBoard[mysql]' \
           'ReviewBoard[postgres]' \
           'ReviewBoard[s3]' \
           'ReviewBoard[saml]' \
           'ReviewBoard[swift]' \
    && if test "$TARGETARCH" = "amd64"; then \
           pip3 install --no-cache-dir 'ReviewBoard[p4]'; \
       fi \
    && { curl https://pysvn.reviewboard.org | python3.11 -; } \
    && rm -rf /tmp/packages


##############################################################################
# Stage 2 of the build.
#
# We'll create a new, final image that contains the virtualenv and only the
# runtime dependencies necessary to run Review Board.
##############################################################################
FROM ubuntu:22.04

# Review Board user ID
#
# The web server will run as this user, and writable directories (such as
# htdocs/media/uploaded/ and data/) will be owned by this user.
ARG REVIEWBOARD_USER_ID=1001

# Review Board group ID
#
# Writable directories (such as htdocs/media/uploaded/ and data/) will be owned
# by this group.
ARG REVIEWBOARD_GROUP_ID=1001

# Whether to install Power Pack by default.
#
# Set to "no" to disable.
ENV ENABLE_POWERPACK=yes

# Public-facing domain name for the server.
ENV DOMAIN=

# Name of your company, for support purposes.
ENV COMPANY=

# Memcached hostname:port.
ENV MEMCACHED_SERVER=memcached:11211

# Database type.
#
# One of "mysql" or "postgresql"
ENV DATABASE_TYPE=postgresql

# Existing name of the database on the server.
ENV DATABASE_NAME=reviewboard

# Database server.
ENV DATABASE_SERVER=db

# Username for accessing the database.
#
# This should be a user specific to Review Board, and not an administrator.
ENV DATABASE_USERNAME=reviewboard

# Password for accessing the database.
ENV DATABASE_PASSWORD=

# Whether to wait for the database to be up before starting services.
ENV WAIT_FOR_DB=yes

# The number of Gunicorn workers.
#
# This, along with NUM_THREADS, should be tuned for the server it's run on.
# It should be at least 2.
ENV NUM_WORKERS=4

# The number of Gunicorn threads.
#
# This, along with NUM_THREADS, should be tuned for the server it's run on.
ENV NUM_THREADS=20

# The number of seconds before a connection is dropped due to inactivity.
#
# This can be set higher if communication with internal servers or
# repositories regularly takes longer than 2 minutes.
ENV REQUEST_TIMEOUT=120

ENV GUNICORN_FLAGS=

# Build-specific environment variables.
ARG TARGETARCH

# Public port that gunicorn will listen to.
EXPOSE 8080

# Location of the site directory.
#
# Mount this somewhere to persist the site directory across containers.
VOLUME /site

# Set up the environment for Python and scripts.
#
# These are used by the processes being run, and are not intended to be
# customized.
ENV LANG=C.UTF-8
ENV VIRTUAL_ENV=/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV REVIEWBOARD_SITEDIR /site
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create a user for the web server.
RUN    groupadd -r reviewboard -g $REVIEWBOARD_GROUP_ID \
    && adduser --system --uid $REVIEWBOARD_USER_ID \
               --disabled-password --disabled-login \
               --ingroup reviewboard reviewboard

COPY --from=builder /etc/apt /etc/apt

RUN    set -ex \
    && export TERM=dumb \
    && export DEBIAN_FRONTEND=noninteractive \
    && if test "$TARGETARCH" = "amd64"; then \
           export P4_PACKAGES="helix-cli"; \
       else \
           export P4_PACKAGES=""; \
       fi \
    && apt-get update -y \
    && apt-get install -y --no-install-recommends \
           ca-certificates \
           cron \
           curl \
           cvs \
           git \
           gosu \
           libldap-2.4 \
           libldap-common \
           libmysqlclient21 \
           libxmlsec1-openssl \
           patch \
           mysql-client \
           postgresql-client \
           python3.11 \
           python3.11-distutils \
           stunnel \
           subversion \
           $P4_PACKAGES \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3

COPY scripts/* /
COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV

# Periodically check that we can hit our health check endpoint, to ensure
# Review Board is running.
HEALTHCHECK CMD curl -f http://127.0.0.1:8080/health/ || exit 1

# Run the site install/upgrade operation and the web server.
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["/serve.sh"]
