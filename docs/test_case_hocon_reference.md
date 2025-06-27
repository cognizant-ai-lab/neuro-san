# Data-Driven Test Case HOCON File Reference

This document describes the neuro-san specifications for the test case .hocon files
found within this repo under the [tests/fixtures](../tests/fixtures) section of this repo.

The neuro-san system uses the HOCON (Human-Optimized Config Object Notation) file format
for its data-driven configuration elements.  Very simply put, you can think of
.hocon files as JSON files that allow comments, but there is more to the hocon
format than that which you can explore on your own.

Specifications in this document each have header changes for the depth of scope of the dictionary
header they pertain to.
Some key descriptions refer to values that are dictionaries.
Sub-keys to those dictionaries will be described in the next-level down heading scope from their parent.

<!--TOC-->

- [Data-Driven Test Case HOCON File Reference](#data-driven-test-case-hocon-file-reference)
    - [Data-Driven Test Case Specifications](#data-driven-test-case-specifications)
        - [agent](#agent)
        - [connections](#connections)
        - [success_ratio](#success_ratio)
        - [use_direct](#use_direct)
        - [metadata](#metadata)
        - [timeout_in_seconds](#timeout_in_seconds)
        - [interactions](#interactions)
            - [text](#text)
            - [sly_data](#sly_data)
            - [timeout_in_seconds](#timeout_in_seconds-1)
            - [chat_filter](#chat_filter)
            - [continue_conversation](#continue_conversation)
            - [response](#response)
                - [text (response)](#text-response)
                - [sly_data (response)](#sly_data-response)
                - [Stock Tests](#stock-tests)
                    - [value/not_value](#valuenot_value)
                    - [less/not_less](#lessnot_less)
                    - [greater/not_greater](#greaternot_greater)
                    - [keywords/not_keywords](#keywordsnot_keywords)
                    - [gist/not_gist](#gistnot_gist)
    - [Use with the Assessor](#use-with-the-assessor)

<!--TOC-->

## Data-Driven Test Case Specifications

### agent

The value gives the string name of the agent to be tested.

While all agents are named according to the filename of their agent network hocon file,
this value should only be the stem of that file.

### connections

Single string values can be:

| value | meaning |
|:----------------|:----------|
| direct (default)| Connect directly to the agent via a neuro-san library call - no server required. |
| http  |  Connect to the agent via a server via http |
| grpc  |  Connect to the agent via a server via gRPC |
| https |  Connect to the agent via a server via secure http |

Note that it is possible to specify a list of connection types for the same test case.
If this is the case, the test driver will conduct the same test via each connection type.

Example of a list:

```python
    ...
    "connections": [ "direct", "http", "grpc" ]
    ...
```

Currently, only testing against a locally running server is supported.

### success_ratio

A string value that represents the fraction of test attempts that need to succeed
in order to call the test passing.

The big idea here is that this is an acknowledgement of the realities of working with LLMs:

- agents do not always do what you want them to
- getting agents to give you correct output given existing prompts and a particular input is fundamentally an optimization
exercise against the prompts themselves.

The denominator (bottom) of the fraction is an integer indicating how many test samples (repeat iterations)
should be attempted.

The numerator (top) of the fraction is an integer indicating how many of those test samples
need to execute without failure in order to call the test "passing" within a unit test infrastructure
that needs some kind of boolean assessment.

When using the [Assessor](../neuro_san/test/assessor/assessor.py) tool to categorize modes of failure,
the denominator here is also used as the indication of how many test samples should be taken.

By default this value is "1/1" indicating that the test case will only run once,
and that single test sample *must* pass in order to "pass".  This is in keeping with
standard expectations w/ non-statistically-oriented tests.

Keep in mind that when using the success_ratio to define test success for an agent test,
sometimes the failures can actually be due to the test criteria ([gist/not_gist](#gistnot_gist) prompting) and
not the agent itself.

### use_direct

Boolean value that describes how an external agent is called.
When False (the default), a grpc call is used to contact the server of the external agent,
even if it is on the same server.
When True, no new socket is created and a direct/library connection is used instead.

### metadata

A dictionary of request metadata to send along to a server for each interaction.

What is required of request metadata dictionaries is server specific.
The default server implementation doesn't require anything for request metadata,
however some servers may require this to contain bearer tokens for access,
or extra user-identifying information for logging.

By default the value for this dictionary is None.

### timeout_in_seconds

An optional float that describes how long the test as a whole should take before
the test driver should give up on it.  This includes multiple attempts when a
[success_ratio](#success_ratio) is defined.

### interactions

A list of dictionaries, where each entry is an interaction with the test cases's agent
to futher the progression of the single test case.  Component dictionaries representing
requests and tests on those responses are executed sequentially according to their order
in the interactions list.

In general, most keys of each component dictionary describe what to send in a request to
the test case's agent, however the most important entry for each dictionary is the
value of the [response](#response) key - this is where the tests on what is returned
are defined.

#### text

A single user message string to send to the agent as input.
Default value is None.

#### sly_data

A dictionary of private data key/value pairs to associate with the input.
Keys are always strings and values can be anything JSON-serializable,
as long as the receiving agent will understand it.

What is required here depends on the agent itself, and ideally what is required
is at least documented in the agent's hocon file.

Superfluous information is passed, taking up space, but ignored.

The default value is None.

<!-- markdownlint-disable-next-line MD024 -->
#### timeout_in_seconds

An optional float that describes how long the single interaction should take before giving up.

#### chat_filter

A string value which describes how the server should filter information it sends back
to the client.

The default value is "MINIMAL", indicating that all that is required to send back to
the client is a single message containing "the answer" (however that is defined by the agent),
and enough information for the test driver to continue the conversation with context
on to the next interaction dictionary.

The only other honored value is "MAXIMAL", indicating full debug information should
come back to the client.  This ends up being a lot more messages.

*Future* iterations of the test infrastructure may elect to test at the level of
this fine-grained MAXIMAL debug information.

#### continue_conversation

A boolean value indicating that the context of the conversation with the test case's agent
should be continued on to the next interaction dictionary.

By default, this value is true, indicating that subsequent interaction requests will take
into account the previous requests and responses.

When this value is false, it is as if at this point in the list of interactions
you are starting a whole new clean-slate conversation.

#### response

A dictionary describing how to test various aspects of the response from the agent.

By default this is an empty dictionary, indicating no tests should be done on this
iteration of the conversation with the agent.  An empty response is valuable for at
least advancing the conversation forward to a point of interest that you'd like to test.

This is kind of abstract, so please try to follow:

Keys in this response dictionary describe specific parts of the response that are to
be tested.  The values for each key are themselves dictionaries that describe potentially
multiple tests to be done on the area of focus on the response described by the key.

First we will describe the keys whose values can be tested, like [text](#text-response)
and [sly_data](#sly_data-response) each in its own subheading.
Then we will describe the [Stock Tests](#stock-tests) able to be performed on each
response datum.

##### text (response)

The text field of the response is a dictionary describing which tests to perform
on the text part of the response from the agent's "answer".

Each key corresponds to a specific test/assert in the [Stock Tests](#stock-tests),
and its value can either be a single test value as verification criteria for the test
to pass or a list of these values - all of which must pass the test.  (That is, list
inclusion is an AND operation.)

For instance, part of the [music_nerd test case](../tests/fixtures/music_nerd/beatles_with_history.hocon)
contains this interaction definition:

```python
    "interactions": [
        {
            # This is what we send as input to streaming_chat()
            "text": "Who did Yellow Submarine?",

            # The response block treats how we are going to test what comes back
            "response": {

                # Text block says how we are going to examine the text of the response.
                "text": {

                    # Keywords says we are going to look for exact matches for each
                    # element in a list of strings.  All elements need to show up
                    # in order to pass.
                    "keywords": ["Beatles"]
                }
            }
        },
        ...
```

The first "text" asks the agent the question "Who did Yellow Submarine?" in its request.
In the "response" block, it is the "text" of the corresponding response that is to be tested.
We could set up multiple tests here, but for this simple example we are electing to test
the agent's "answer" against containing the [keyword](#keywordsnot_keywords) "Beatles".
The test doesn't care about exact verbiage of the "answer" from the agent, all that matters
is that somewhere in the text, the keyword "Beatles" is in there.

##### sly_data (response)

The sly_data field of the response is a dictionary describing which tests to perform
on the sly_data dictionary optionally returned as part of the response from the agent's "answer".

Since the sly data is inherently a dictionary, we don't really want to test entire dictionary
contents. Instead, what we want to test are specific values for particular keys inside the
sly_data dictionary that was returned.  As such, each key in the test case's dictionary here
corresponds to a specific key inside the returned sly_data that is to be tested.  The value
is yet another dictionary that describes what to test, just like in [text](#text-response) above.

Each key corresponds to a specific test/assert in the [Stock Tests](#stock-tests),
and its value can either be a single test value as verification criteria for the test
to pass or a list of these values - all of which must pass the test.  (That is, list
inclusion is an AND operation.)

For instance, part of the [math_guy test case](../tests/fixtures/math_guy/basic_sly_data.hocon)
contains this interaction definition:

```python
    "interactions": [
        {
            # This is what we send as input to streaming_chat()
            "text": "times",

            "sly_data": {
                "x": 847,
                "y": 23
            },

            # The response block treats how we are going to test what comes back
            "response": {

                # Text block says how we are going to examine the text of the response.
                "sly_data": {

                    # Each key here corresponds to a key in the sly_data itself
                    # that is returned.
                    "equals": {
                        # Value says we are going to look for exact values for each
                        # element in a list of strings.  All elements need to show up
                        # in order to pass.
                        "value": [19481.0]
                    }
                }
            }
        }
    ]
```

In this response part, what is being tested is the sly_data dictionary returned with "the answer".
That dictionary is expected to have a single key called "equals".  The value for that "equals"
key is tested against all of the tests listed in the corresponding dictionary. In this case,
there is a single [value](#valuenot_value) check against the number 19481.0.

Note that for sly_data, it's possible to return nested dictionaries.
To test the key/value pairs inside nested dictionaries, simply nest your test dictionaries.

##### Stock Tests

The following are lists of the stock test keywords and their negations that come with the
test infrastructure.

For any of these tests, the name of the test itself is specified as a key in a dictionary.
The value part describes what the response should be tested against.
These values can either be single scalar values (string, int, etc) or a list of values.
When specifying a list of values for a test, each value listed must pass.

###### value/not_value

The "value" test looks for a specific value.  If what is in the response is the exact value
mentioned in the test case, the test will pass.  This is just like
[TestCase.assertEqual](https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertEqual)

Similary, the "not_value" tests looks for values that are not what is listed in the test.
If what is in the response is not the exact value mentioned in the test case, the test will pass.
This is just like
[TestCase.assertNotEqual](https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertNotEqual)

###### less/not_less

The "less" test looks for a value that is considered less than what is given.
For numbers, this is the expected inequality. For strings, this is a lexicographical comparison.
If what is tested is less than the value mentioned, the test will pass. This is just like
[TestCase.assertLess](https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertLess)

Similarly the "not_less" test looks for a value that is considered greater than or equal to what is given.
If what is tested is >= than the value mentioned, the test will pass. This is just like
[TestCase.assertGreaterEqual](https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertGreaterEqual)

###### greater/not_greater

The "greater" test looks for a value that is considered greater than what is given.
For numbers, this is the expected inequality. For strings, this is a lexicographical comparison.
If what is tested is greater than the value mentioned, the test will pass. This is just like
[TestCase.assertGreater](https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertGreater)

Similarly the "not_greater" test looks for a value that is considered less than or equal to what is given.
If what is tested is <= than the value mentioned, the test will pass. This is just like
[TestCase.assertLessEqual](https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertLessEqual)

###### keywords/not_keywords

The "keywords" test looks for the value mentioned to be "in" what is referred to in the response.
For strings, this means the given keyword must be somewhere in the larger string that is being tested.
This is just like
[TestCase.assertIn](https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertIn)

Similary the not_keywords test looks for the mentioned value to be not "in" what is referred to in the response.
This is just like
[TestCase.assertNotIn](https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertNotIn)

###### gist/not_gist

This one is special agent magic.

The idea here is that an agent returns some string response in its multitude of ways, but you want to
test that the string returned satisfies a certain verbally specified criteria to match all cases.
This is *not* a strict keyword search and requires a language task to assess the validity.
To do this we use a separate agent to test the value against the criteria to make sure the
response matches the "gist" of the criteria.

If the response from the agent we are testing matches the "gist" of the given criteria, the test passes.

Similarly the "not_gist" test passes when the response does not match the "gist" of the given criteria.

## Use with the Assessor

The [Assessor](../neuro_san/test/assesor/assessor.py) is a tool which uses these data-driven test cases
as a basis for gathering repeated test samples so as to assess how often the test case will pass.
You give the assessor a test case hocon file, it looks at the [success_ratio](#success_ratio) denominator
to see how many test samples it should run.  As it gathers its output for each test sample, it
records *how* the failures occurred and attempts to classify them according to common modes of failure.
This allows you to get statistical picture of what you need to improve with respect to prompt or
test case optimization.
