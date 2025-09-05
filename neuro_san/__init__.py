
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

from leaf_common.config.file_of_class import FileOfClass

# Normally we don't use __init__.py files to define anything,
# but here we define some constants that point to important directories in the distribution.
TOP_LEVEL_DIR = FileOfClass(__file__)
DEPLOY_DIR = FileOfClass(__file__, path_to_basis="./deploy")
REGISTRIES_DIR = FileOfClass(__file__, path_to_basis="./registries")
