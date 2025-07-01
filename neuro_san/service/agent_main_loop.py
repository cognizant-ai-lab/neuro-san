
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
from neuro_san.service.main_loop.server_main_loop import ServerMainLoop


# Backwards compatibility entry point
if __name__ == '__main__':
    ServerMainLoop().main_loop()
