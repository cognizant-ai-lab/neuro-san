
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
class StringFilter:
    """
    Interface whose filter() method takes one string and returns another
    string which is a filtered version of the input.

    Implementations encapsulate one string-shaping policy, for example making
    a name acceptable to an external system that only allows certain
    characters. Keeping such a policy behind this interface lets callers be
    handed any implementation, and lets several policies be composed by an
    implementation that applies others in sequence.

    This interface used to live in leaf-common and is reinstated here so it
    can be pushed back down once more than one project needs it again.
    """

    def filter(self, in_string: str) -> str:
        """
        Filters the given string according to the implementation's policy.

        :param in_string: An input string to filter
        :return: A filtered version of in_string, according to implementation policy
        :raises NotImplementedError: Always; implementations must override this method
        """
        raise NotImplementedError
