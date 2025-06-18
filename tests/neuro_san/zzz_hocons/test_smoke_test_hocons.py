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

from unittest import TestCase

import pytest

from parameterized import parameterized

from neuro_san.test.unittest.dynamic_hocon_unit_tests import DynamicHoconUnitTests


class TestSmokeTestHocons(TestCase):
    """
    Data-driven dynamic test cases where each test case is specified by a single hocon file.
    """

    # A single instance of the DynamicHoconUnitTests helper class.
    # We pass it our source file location and a relative path to the common
    # root of the test hocon files listed in the @parameterized.expand()
    # annotation below so the instance can find the hocon test cases listed.
    DYNAMIC = DynamicHoconUnitTests(__file__, path_to_basis="../../fixtures")

    @parameterized.expand(DynamicHoconUnitTests.from_hocon_list([
        # These can be in any order.
        # Ideally more basic functionality will come first.
        # Barring that, try to stick to alphabetical order.
        "music_nerd_pro/combination_responses_with_history_direct.hocon",

        # List more hocon files as they become available here.
    ]))
    @pytest.mark.timeout(30)  # 30 seconds for this test
    @pytest.mark.smoke
    def test_hocon(self, test_name: str, test_hocon: str):
        """
        Test method for a single parameterized test case specified by a hocon file.
        Arguments to this method are given by the iteration that happens as a result
        of the magic of the @parameterized.expand annotation above.

        :param test_name: The name of a single test.
        :param test_hocon: The hocon file of a single data-driven test case.
        """
        # Call the guts of the dynamic test driver.
        # This will expand the test_hocon file name from the expanded list to
        # include the file basis implied by the __file__ and path_to_basis above.
        self.DYNAMIC.one_test_hocon(self, test_name, test_hocon)

    @parameterized.expand(DynamicHoconUnitTests.from_hocon_list([
        # These can be in any order.
        # Ideally more basic functionality will come first.
        # Barring that, try to stick to alphabetical order.
        "music_nerd_pro/combination_responses_with_history_grpc.hocon",

        # List more hocon files as they become available here.
    ]))
    @pytest.mark.timeout(30)  # 30 seconds for this test
    @pytest.mark.smoke
    @pytest.mark.needs_server
    def test_hocon_with_server(self, test_name: str, test_hocon: str):
        """
        Test method for a single parameterized test case specified by a hocon file.
        Arguments to this method are given by the iteration that happens as a result
        of the magic of the @parameterized.expand annotation above.

        :param test_name: The name of a single test.
        :param test_hocon: The hocon file of a single data-driven test case.
        """
        # Call the guts of the dynamic test driver.
        # This will expand the test_hocon file name from the expanded list to
        # include the file basis implied by the __file__ and path_to_basis above.
        self.DYNAMIC.one_test_hocon(self, test_name, test_hocon)

    @parameterized.expand(DynamicHoconUnitTests.from_hocon_list([
        # These can be in any order.
        # Ideally more basic functionality will come first.
        # Barring that, try to stick to alphabetical order.
        "music_nerd_pro_llm_anthropic/combination_responses_with_history_direct.hocon",

        # List more hocon files as they become available here.
    ]))
    @pytest.mark.timeout(30)  # 30 seconds for this test
    @pytest.mark.smoke
    @pytest.mark.non_default_llm_provider
    @pytest.mark.anthropic
    def test_hocon_with_anthropic(self, test_name: str, test_hocon: str):
        """
        Test method for a single parameterized test case specified by a hocon file.
        Arguments to this method are given by the iteration that happens as a result
        of the magic of the @parameterized.expand annotation above.

        :param test_name: The name of a single test.
        :param test_hocon: The hocon file of a single data-driven test case.
        """
        # Call the guts of the dynamic test driver.
        # This will expand the test_hocon file name from the expanded list to
        # include the file basis implied by the __file__ and path_to_basis above.
        self.DYNAMIC.one_test_hocon(self, test_name, test_hocon)
