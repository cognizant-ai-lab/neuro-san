#!/bin/bash

# Script that runs the docker file locally with proper mounts
# Usage: run.sh <CONTAINER_VERSION>
#
# This needs to be run from the top-level directory

export SERVICE_NAME="NeuroSan"
export SERVICE_DIR=neuro-san
export SERVICE_TAG=neuro-san
export SERVICE_VERSION=0.0.1

function check_run_directory() {

    # Everything here needs to be done from the top-level directory for the repo
    working_dir=$(pwd)
    exec_dir=$(basename "${working_dir}")
    if [ "$exec_dir" != "neuro-san" ]
    then
        echo "This script must be run from the top-level directory for the repo"
        exit 1
    fi
}


function run() {

    CONTAINER_VERSION=$1
    if [ "${CONTAINER_VERSION}" == "" ]
    then
        CONTAINER_VERSION="${SERVICE_VERSION}"
    fi
    echo "Using CONTAINER_VERSION ${CONTAINER_VERSION}"

    # Using a default network of 'host' is actually easiest thing when
    # locally testing against a vault server container set up with https,
    # but allow this to be changeable by env var.
    network=${NETWORK:="host"}
    echo "Network is ${network}"

    # Run the docker container in interactive mode
    #   Mount the current user's aws credentials in the container
    #   Mount the 1st command line arg as the place where input files come from
    #   Mount the directory where the vault certs live. In production this would be
    #       set up to what kubernetes does natively.
    #   Slurp in the rest as environment variables, all of which are optional.
    docker run --rm -it -d \
        --name="${SERVICE_NAME}" \
        --network="${network}" \
        -v "${HOME}"/.aws:/usr/local/leaf/.aws \
        -v "${VAULT_CERT_DIR:=/home/${USER}/certs/vault/localhost}":/usr/local/leaf/vault \
        -e AWS_ACCESS_KEY_ID \
        -e AWS_SECRET_ACCESS_KEY \
        -e AWS_DEFAULT_REGION \
        -e VAULT_ADDR \
        -e VAULT_GITHUB_AUTH_TOKEN \
        -e VAULT_CACERT="/usr/local/leaf/vault/ca_bundle.pem" \
        -e OSO_URL \
        -e OSO_API_KEY \
        -e AUTHORIZATION_TYPE \
        -e UNILEAF_USER="${USER}" \
	    localhost/leaf/"${SERVICE_TAG}":"${CONTAINER_VERSION}"
}

function main() {
    check_run_directory
    run "$@"
}

# Pass all command line args to function
main "$@"
