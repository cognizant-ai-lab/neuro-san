import pytest

from unittest import TestCase

from neuro_san.coded_tools.music_nerd_pro.accountant import Accountant


class TestAccountant(TestCase):
    """
    Unit tests for Accountant class.
    """

    @pytest.mark.asyncio
    async def test_invoke(self):
        """
        Tests the invoke method of the Accountant CodedTool.
        The Accountant CodedTool should increment the passed running cost by 1.0 each time it is invoked,
        and should return a dictionary with the updated running cost.
        """
        accountant = Accountant()
        # Initial running cost
        a_running_cost = 0.0
        response_1 = await accountant.async_invoke(args={"running_cost": a_running_cost}, sly_data={})
        expected_dict_1 = {"running_cost": 3.0}
        self.assertDictEqual(response_1, expected_dict_1)
        updated_running_cost = response_1["running_cost"]
        response_2 = await accountant.async_invoke(args={"running_cost": updated_running_cost}, sly_data={})
        expected_dict_2 = {"running_cost": 6.0}
        self.assertDictEqual(response_2, expected_dict_2)
