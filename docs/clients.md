# Creating Clients

## Python Clients

If you are using Python to create your client, then you are in luck!
The command line client at neuro_san/client/agent_cli.py is a decent example
of how to construct a chat client in Python.

A little deeper under the hood, that agent_cli client uses these classes under neuro_san/session
to connect to a server:

Synchronous connection:

* GrpcServiceAgentSession
* HttpServiceAgentSession

It also uses the DirectAgentSession to call the neuro-san infrastructure as a library.
There are async version of all of the above as well.

## Other clients

A neuro-san server uses HTTP and/or gRPC under the hood. You can check out the protobufs definition of the
API under neuro_san/api/grpc.  The place to start is agent.proto for the service definitions.
The next most important file there is chat.proto for the chat message definitions.

While gRPC data transimission is more compact, most clients will likely want to use the HTTP
interface for ease of use in terms of web-apps and dev-ops administration.

### Using curl to interact with a neuro-san server

In one window start up a neuro-san server:

    python -m neuro_san.service.main_loop.server_main_loop

In another window, you can interact with this server via curl.

#### Getting an agent's prompt

Specific neuro-san agents are accessed by including the agent name in the route.
To get the hello_world agent's prompt, we do a GET to the function url for the agent:

    curl --request GET --url localhost:8080/api/v1/hello_world/function

returns:

    ```json
    {
        "function": {
            "description": "\nI can help you to make a terse anouncement.\nTell me what your target audience is, and what
            sentiment you would like to relate.\n"
        }
    }
    ```

The description field of the function structure is a user-displayable prompt.

#### Communicating with an agent

##### Initial User Request

Using the same principle of specifying the agent name in a route, we can use the hello_world
url to initiate a conversation with an agent with a POST:

    curl --request POST --url localhost:8080/api/v1/hello_world/streaming_chat --data '{
        "user_message": {
            "text": "I approach a new planet and wish to send greetings to the orb."
        }
    }'

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

    curl --request POST --url localhost:8080/api/v1/hello_world/streaming_chat --data '{
        "user_message": {
            "text": "I approach a new planet and wish to send greetings to the orb."
        },
        "chat_context": {
            <blah blah>
        }
    }'

... and back comes the next result for your conversation
