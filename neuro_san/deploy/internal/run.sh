#!/bin/bash

# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

# Script that runs the docker file locally with proper mounts
# Usage: run.sh <CONTAINER_VERSION>
#
# This needs to be run from the top-level directory

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

    # RUN_JSON_INPUT_DIR will go away when an actual GRPC service exists
    # for receiving the input. For now it's a mounted directory.
    CONTAINER_VERSION="0.0.1"
    echo "Using CONTAINER_VERSION ${CONTAINER_VERSION}"
    echo "Using args '$*'"

    #
    # Host networking only works on Linux. Get the OS we are running on
    #
    OS=$(uname)
    echo "OS: ${OS}"

    # Using a default network of 'host' is actually easiest thing when
    # locally testing against a vault server container set up with https,
    # but allow this to be changeable by env var.
    network=${NETWORK:="host"}
    echo "Network is ${network}"

    SERVICE_NAME="NeuroSanAgents"
    # Assume the first port EXPOSEd in the Dockerfile is the input port
    SERVICE_PORT=$(grep EXPOSE < neuro_san/deploy/internal/Dockerfile | head -1 | awk '{ print $2 }')
    echo "SERVICE_PORT: ${SERVICE_PORT}"

    # Run the docker container in interactive mode
    #   Mount the 1st command line arg as the place where input files come from
    #   Slurp in the rest as environment variables, all of which are optional.

    docker_cmd="docker run --rm -it \
        --name=$SERVICE_NAME \
        --network=$network \
        -e OPENAI_API_KEY \
        -e ANTHROPIC_API_KEY \
        -e TOOL_REGISTRY_FILE=$1 \
        -p $SERVICE_PORT:$SERVICE_PORT \
            leaf/neuro-san:$CONTAINER_VERSION"

    if [ "${OS}" == "Darwin" ];then
        # Host networking does not work for non-Linux operating systems
        # Remove it from the docker command
        docker_cmd=${docker_cmd/--network=$network/}
    fi

    echo "${docker_cmd}"
    $docker_cmd
}

function main() {
    check_run_directory
    run "$@"
}

# Pass all command line args to function
main "$@"
