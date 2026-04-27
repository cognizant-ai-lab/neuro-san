# Creating Clients

## Python Clients

If you are using Python to create your client, then you are in luck!
The command line client at neuro_san/client/agent_cli.py is a decent example
of how to construct a chat client in Python.

A little deeper under the hood, that agent_cli client uses this class under neuro_san/session
to connect to a server:

Synchronous connection:

* HttpServiceAgentSession

It also uses the DirectAgentSession to call the neuro-san infrastructure as a library.
There are async versions of all of the above as well.

## Connection modes

There are two ways to connect to an agent network:

### HTTP / MCP (client-server)

client → Server → use_direct=False (hardcoded) → HTTP → external network

The client sends requests to a running server. The server runs the agent network and resolves
any external networks (tools prefixed with `/`) via HTTP back to itself.

`use_direct` is hardcoded to `False` on the server — the client's setting is ignored.

Requires starting the server first:
    ```python
    python -m neuro_san.service.main_loop.server_main_loop
    ```

### Direct (in-process / library call)

client → in-process → use_direct=False → HTTP → external network (needs server, hangs if none)
client → in-process → use_direct=True  → in-process → external network (no server needed)

The agent network runs in the same Python process as the client. No server is needed
for the top-level network. Direct mode is more flexible — but therefore trickier.

The `use_direct` parameter controls how **external networks** are resolved:
* **`use_direct=True`** (default in CLI) — external networks are loaded from the local manifest
  and run in-process. No server needed.
* **`use_direct=False`** — external networks are resolved via HTTP to a running server.
  If no server is running, **it silently hangs** with no error message.

For a working example of an external network, see
[`math_guy_passthrough`](../registries/math_guy_passthrough.hocon),
which delegates to the `/math_guy` external network.

### Setting `use_direct`

**CLI (`agent_cli`):**

```bash
# use_direct=True (default) — no server needed for external networks
python -m neuro_san.client.agent_cli --agent agent_network_designer

# use_direct=False — requires a running server for external networks
python -m neuro_san.client.agent_cli --agent agent_network_designer --local_externals_service
```

**Library API (`AgentSessionFactory`):**

```python
from neuro_san.client.agent_session_factory import AgentSessionFactory
```

```text
# use_direct=True — external networks resolved in-process
session = AgentSessionFactory().create_session("direct", "agent_network_designer", use_direct=True)
 
# use_direct=False — external networks resolved via HTTP (needs server)
session = AgentSessionFactory().create_session("direct", "agent_network_designer", use_direct=False)

Note: The library API currently defaults use_direct to False. This will be changed to True in a future release to match the CLI default. Until then, always pass use_direct=True explicitly when using direct mode without a server.
```

## Other clients

A neuro-san server uses HTTP under the hood. You can check out the protobufs definition of the
API under neuro_san/api/grpc.  The place to start is agent.proto for the service definitions.
The next most important file there is chat.proto for the chat message definitions.

### Using curl to interact with a neuro-san server

In one window start up a neuro-san server:
    ```python
    python -m neuro_san.service.main_loop.server_main_loop
    ```
In another window, you can interact with this server via curl.

#### Getting an agent's prompt

Specific neuro-san agents are accessed by including the agent name in the route.
To get the hello_world agent's prompt, we do a GET to the function url for the agent:
    ```bash
    curl --request GET --url localhost:8080/api/v1/hello_world/function
    ```
returns:

```json
    {
        "function": {
            "description": "\nI can help you to make a terse announcement.\nTell me what your target audience is, and what
            sentiment you would like to relate.\n"
        }
    }
```

The description field of the function structure is a user-displayable prompt.

#### Communicating with an agent

##### Initial User Request

Using the same principle of specifying the agent name in a route, we can use the hello_world
url to initiate a conversation with an agent with a POST:
    ```bash
    curl --request POST --url localhost:8080/api/v1/hello_world/streaming_chat --data '{
        "user_message": {
            "text": "I approach a new planet and wish to send greetings to the orb."
        }
    }'
    ```

This will result in a stream of a single chat message structure coming back until the processing of the request is finished:

```json
    {
        "response": {
            "type": "AGENT_FRAMEWORK",
            "text": "The announcement \"Hello, world!\" is an apt and concise greeting for the new planet.",
            "chat_context": {
                <blah blah>
            }
        }
    }
```

This response is telling you:

* The message from the hello_world agent network was the typical end "AGENT_FRAMEWORK"-typed message.
  These kinds of messages come from neuro-san itself, not from any particular agent
  within the network.
* The "text" of what came back as the answer - "Hello, world!" with typical extra LLM elaborating text.
* The chat_context that is returned is a structure that helps you continue the conversation.
  For the most part, you can think of this as semi-opaque chat history data.

For a single-shot conversation, this is all you really need to report back to your user.

But if you want to continue the conversation, you will need to pay attention to the chat_context.
What comes back in the chat_context can be fairly large, but for purposes of this conversation,
the details of the content are not as important.

##### Continuing the conversation

In order to continue the conversation, you simply take the value of the last AGENT_FRAMEWORK message's
chat_context and add that to your next streaming_chat request:
    ```bash
    curl --request POST --url localhost:8080/api/v1/hello_world/streaming_chat --data '{
        "user_message": {
            "text": "I approach a new planet and wish to send greetings to the orb."
        },
        "chat_context": {
            <blah blah>
        }
    }'
    ```

... and back comes the next result for your conversation

##### Adding Private Data to the User Request

One strength of the neuro-san infrastructure is that you can add private data to the user request.
This can be used to add context to the conversation that is not visible to the chat stream of any agent.
The field you want to fill is called "sly_data". It is a dictionary of key-value pairs that can
be different for each agent.

As above, you can specify the agent name in the route. We will use a different sample agent
called "math_guy" who is a simple calculator agent that takes operands in the sly_data and
the name of the operator in the regular chat stream. The result also comes back in the sly_data:
    ```bash
    curl --request POST --url localhost:8080/api/v1/math_guy/streaming_chat --data '{
        "user_message": {
            "text": "multiply"
        },
        "sly_data": {
            "x": 7,
            "y": 6
        }
    }'
    ```

The response looks like this:

```json
    {
        "response": {
            "type": "AGENT_FRAMEWORK",
            "text": "\"Check sly_data['equals'] for the result\"",
            "chat_context": {
                <blah blah>
            }
            "sly_data": {
                "equals": 42
            }
        }
    }
```
