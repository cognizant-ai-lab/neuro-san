#!/bin/bash

# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

# Entry point script which manages the transition from
# Docker bash to Python

cat /etc/os-release

PYTHON=python3
echo "Using python ${PYTHON}"

PIP=pip3
echo "Using pip ${PIP}"

echo "Preparing app..."
if [ -z "${PYTHONPATH}" ]
then
    PYTHONPATH=$(pwd)
fi
export PYTHONPATH

echo "Configuration information:"
grep MemTotal < /proc/meminfo
if [ -f /sys/fs/cgroup/memory/memory.limit_in_bytes ]
then
    cat /sys/fs/cgroup/memory/memory.limit_in_bytes
fi
if [ -f /sys/fs/cgroup/memory.max ]
then
    cat /sys/fs/cgroup/memory.max
fi
echo

lscpu | grep "^CPU(s):"
if [ -f /sys/fs/cgroup/cpu/cpu.cfs_quota_us ]
then
    cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us
fi
if [ -f /sys/fs/cgroup/cpu.max ]
then
    cat /sys/fs/cgroup/cpu.max
fi
echo

ulimit -a

echo "Toolchain:"
${PYTHON} --version
${PIP} --version
${PIP} freeze

PACKAGE_INSTALL=${PACKAGE_INSTALL:-.}
echo "PACKAGE_INSTALL is ${PACKAGE_INSTALL}"

echo "AGENT_SESSION_REQUIRE_HTTPS = ${AGENT_SESSION_REQUIRE_HTTPS}"

echo "Starting service with args '$1'..."
${PYTHON} "${PACKAGE_INSTALL}"/neuro_san/service/main_loop/server_main_loop.py "$@"

echo "Done."
