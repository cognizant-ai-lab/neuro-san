
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
from typing import Any
from typing import Dict
from typing import List

import argparse

from neuro_san import REGISTRIES_DIR
from neuro_san.client.simple_one_shot import SimpleOneShot
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.test.assessor.assessor_assert_forwarder import AssessorAssertForwarder
from neuro_san.test.driver.data_driven_agent_test_driver import DataDrivenAgentTestDriver


class Assessor:
    """
    Command line tool for assessing an agent network's response
    to an input test case.
    """

    def __init__(self):
        """
        Constructor
        """
        self.args = None

    def main(self):
        """
        Main entry point for command line user interaction.
        """
        # Parse command line arguments
        self.parse_args()

        # Run the tests per the test case, collecting failure information in the AssertForwarder
        asserts = AssessorAssertForwarder()
        driver = DataDrivenAgentTestDriver(asserts)

        print(f"Testing {self.args.test_hocon}:")
        driver.one_test(self.args.test_hocon)

        # Get raw failure information from AssertForwarder
        num_total: int = asserts.get_num_total()
        fail: List[Dict[str, Any]] = asserts.get_fail_dicts()
        num_pass: int = num_total - len(fail)

        # Initial output
        print(f"{num_pass}/{num_total} attempts passed.")
        if num_total == 1:
            print("There was only one test attempt done. Consider setting 'success_ratio' on your test case hocon.")
        if num_pass == num_total:
            return

        # Assess the failures by agent and output the results.
        assessment: Dict[str, List[Dict[str, Any]]] = self.assess_failures(fail)
        self.output_failures(assessment, num_total)

    def parse_args(self):
        """
        Parse command line arguments into member variables
        """
        arg_parser = argparse.ArgumentParser()
        self.add_args(arg_parser)
        self.args = arg_parser.parse_args()
        if self.args.assessor_agent is None:
            self.args.assessor_agent = REGISTRIES_DIR.get_file_in_basis("assess_failure.hocon")

    def add_args(self, arg_parser: argparse.ArgumentParser):
        """
        Adds arguments.  Allows subclasses a chance to add their own.
        :param arg_parser: The argparse.ArgumentParser to add.
        """
        arg_parser.add_argument("--test_hocon", type=str,
                                help="The test case .hocon file to use as a basis for assessment")
        arg_parser.add_argument("--assessor_agent", type=str, default=None,
                                help="""
The assessor agent to use. A default of None implies use of neuro-san stock assess_failure.hocon
""")
        arg_parser.add_argument("--connection", default="direct", type=str,
                                choices=["grpc", "direct", "http", "https"],
                                help="""
The type of connection to initiate. Choices are to connect to:
    "grpc"      - an agent service via gRPC. Needs host and port.
    "http"      - an agent service via HTTP. Needs host and port.
    "https"     - an agent service via secure HTTP. Needs host and port.
    "direct"    - a session via library.
""")
        arg_parser.add_argument("--host", type=str, default=None,
                                help="hostname setting if not running locally")
        arg_parser.add_argument("--port", type=int, default=AgentSession.DEFAULT_PORT,
                                help="TCP/IP port to run the Agent gRPC service on")

    def categorize_one_failure(self, fail: Dict[str, Any], failure_modes: List[str]) -> str:
        """
        Categorize a single failure instance
        :param fail: A failure dictionary from asserts.get_fail_dicts()
        :param failure_modes: A List of strings describing known failure modes
        :return: A string describing an existing mode of failure or
                a description of a new mode of failure
        """

        text: str = f"""
The acceptance_criteria is:
"{fail.get('acceptance_criteria')}".

The text_sample is:
"{fail.get('text_sample')}".

The known failure_modes are:
{failure_modes}
"""

        # Use the "gist" agent to do the evalution
        one_shot = SimpleOneShot(self.args.assessor_agent, self.args.connection,
                                 host=self.args.host, port=self.args.port)
        raw_answer: str = one_shot.get_answer_for(text)
        return raw_answer

    def assess_failures(self, fail: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Assess the failures in a failure list

        :param fail: A list of failure dictionaries from asserts.get_fail_dicts()
        :return: A dictionary whose keys describe specific modes of failure,
                and whose values are a list of failure dictionaries.
        """
        # Loop through each failure dictionary and categorize each one.
        assessment: Dict[str, Dict[str, Any]] = {}
        for one_failure in fail:

            # Always use our latest-greatest list of known failure modes.
            failure_modes: List[str] = assessment.keys()
            failure_mode: str = self.categorize_one_failure(one_failure, failure_modes)

            # If we have seen this failure before, add to the existing list.
            if failure_mode in failure_modes:
                assessment[failure_mode].append(one_failure)
            else:
                # ... otherwise make a new list for more potential matches later.
                assessment[failure_mode] = [one_failure]

        return assessment

    def output_failures(self, assessment: Dict[str, Dict[str, Any]], num_total: int):
        """
        Output the results of the failure assessment
        :param assessment: A dictionary whose keys describe specific modes of failure,
                and whose values are a list of failure dictionaries.
        :param num_total: The total number of attempts, including passing attempts.
        """
        # Get a total failure count
        num_fail: int = 0
        for failure_list in assessment.values():
            num_fail += len(failure_list)
        print(f"{num_fail}/{num_total} attempts failed.")

        # Sort the modes of failure by how often they occurred,
        # with the most common appearing at the beginning of the list.
        # The item[1] in the lambda is a list of failure dictionaries corresponding to the failure mode.
        # What is returned from sorted() is a list of key/value tuples which are reassembled
        # back into a sorted dictionary where earlier entries reflects higher occurrence.
        sorted_assessment: Dict[str, List[Dict[str, Any]]] = \
            dict(sorted(assessment.items(), key=lambda item: len(item[1]), reverse=True))

        # Output specific modes of failure with example agent return values.
        print("Modes of failure:")
        for failure_mode, failure_list in sorted_assessment.items():
            mode_count: int = len(failure_list)
            percent: float = 100.0 * mode_count / num_fail
            print("")
            print(f"{mode_count}/{num_fail} failures ({percent:.2f}%):")
            print("Failure Mode:")
            print(f"{failure_mode}")
            for index, fail_dict in enumerate(failure_list):
                print("")
                print(f"    Example {index+1}:")
                text_sample: str = fail_dict.get("text_sample")
                text_sample = text_sample.strip()
                print(f"    {text_sample}")

            acceptance_criteria: str = failure_list[0].get("acceptance_criteria")
            acceptance_criteria = acceptance_criteria.strip()
            print("")
            print("    Acceptance Criteria:")
            print(f"    {acceptance_criteria}")


if __name__ == '__main__':
    Assessor().main()
