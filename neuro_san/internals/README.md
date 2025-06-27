# Streaming Chat Details

Here is how streaming_chat() works for the langchain implementation in perhaps too much detail:

* A request bearing user-input comes into an AgentSession (either by method or web service call).
* An instance of a DataDrivenChat object is initialized with (among other things):
    * A single AgentToolRegistry for the entirety of the agent network
    * A single FrontMan node instantiation.  This instance is initialized with the following:
        * An AgentToolFactory instance - this is used when tool calls are successful
                to "make real" a node in the agent graph from the AgentToolRegistry specs
        * An instance of a Journal, which has access to a queue that feeds messages back
                to the caller (see below)
        * An instance of the front-man's agent spec dictionary
        * Any sly_data (private data) that was passed in as part of the request.
* An asynchronous invocation of DataDrivenChat.streaming_chat() is set up to happen in a separate thread
    while the AgentSession itself, prepares to receive a stream of messages from a queue.
    streaming_chat() is passed the user input, the sly_data dictionary (both passed as part of the request)
    and an InvocationContext object which will be passed around to the system below. This InvocationContext
    contains policy objects for the lower-level calls to reference when there are different behavioral
    decisions to be made.

    In general:
    As the messages come over the queue, they are streamed back to the caller from AgentSession.streaming_chat().
    The messages themselves get thrown on the queue at various points within the asynchronous
    call to DataDrivenChat.streaming_chat() from a separate thread.

* Meanwhile back inside the asynchronous DataDrivenChat.streaming_chat() call,
    * A RunContext is created for the front man per the agent spec (langchain vs openai)
        with some information as to the name of the front man agent.  This is stored
        as part of the origin to be used for sending messages back indicating where in
        the agent hierarchy any given message is coming from.
    * The AgentToolRegistry is consulted to find and create an instance of the FrontMan.
    * The RunContext's create_resources() is invoked which does the following:
        * Consults the agent spec for which LLM Config to use
        * Asks the LLMFactory to create an instance/connection to the LLM in question.
        * Creates Tool instances for any tool listed in the spec to be available for
            optional later use (depending on what the LLM/Agent decides to use within its
            own reasoning).
            * The AgentToolRegistry is consulted as to each agent's function spec
                in constructing each Tool instance.
            * At this stage each Tool instance is a LangChainOpenAIFunctionTool -
                our special bridging code that allows us to route a langchain agent Tool
                call to whatever we want later.  This acts as a placeholder so the Agent
                making the decision knows what it *can* call. That is, it answers the
                question for the agent: "What could I call?".
                It's not until later when the decision to call a tool is made by an LLM,
                that the real instatiation of a node in our own graph is made. That is:
                "What am I going to do?"
        * A langchain ChatPpromptTemplate of a few messages is created per langchain recommendations.
            These include:
            * A system message which holds the instructions
            * A placeholder message which holds the (impending) chat history
            * A "human" message which holds the input to the calle (user or agent generated)
            * A placeholder message for the "agent scratchpad" to allow a place for agent
                decisions to be kept.
        * Finally, a langchain Agent instance itself is created passing it the LLM instance,
            the tools list and the prompt template.
        * All of the above are kept as state in the RunContext instance
    * A timestamp is taken as to when the user-input came in.
    * Any last-response information is cleared for the polling chat() case.
    * the sly_data (private data) dictionary is prepared for dissemination to other agents
    * The first message is sent to the message queue saying that the chat agents are starting up.
    * The front man's special "submit_message() call is made with the user input as an argument.
        This method will return the front man's chat history so the caller can do what it pleases with it.

* Inside FrontMan.submit_message()
    * Its RunContext.submit_message() is called with the user input which returns a framework-agnostic Run handle.
    * A loop is entered waiting for a certain termination criteria to happen
        * The RunContext.wait_on_run() waits for results from the RunContext's LLM
        * If the results from the Run.requires_action() indicates there is more to do,
            (however that is defined by langchain, or OpenAI or whatever framework is being used),
            the FrontMan(/BranchTool)'s make_tool_function_calls() is invoked
            and the termination criteria for the loop is not met, so we keep looping
            until there is nothing more to do. More on that below
        * If the results indicate there is nothing more to do, we get the response
          and return that as the result of submit_message(). This ends up being
          the final response from the front-man agent which is returned to the user.

* When FrontMan/BranchTool/CallingTool.make_tool_function_calls() is invoked:
    * the method is passed a Run result which holds a list of tool names that
        the agent logic wishes to invoke and with what parameters.
        (These are all determined by lower-level langchain Agent logic in conjuction
         with the LLM selected. That is - the LLM itself decides what tools to call.)
    * For each tool that the agent wants to be called:
        * We get the name of the tool to be called  
        * We get the arguments to be passed to the tool
        * We instantiate a new node in our graph via the AgentToolFactory that corresponds
            to the agent_spec of the tool to be called.  The Factory will create one of the
            following nodes based on the spec:  
                (Note: Here "tool" and "node" are interchangeable terms.
                        Maybe I should rename these all to "node" for clarity in the future.)
            * An ExternalTool - Used to invoke an agent network on another server.
                When this guy is made, an effort to redact the sly_data
                is made before passing it on to its constructor
            * A ClassTool - an internal representation which knows how to invoke the
                user's CodedTool implementation
            * A BranchTool - an internal representation that allows invocation of another
                LLM-based agent.

            * Each tool above is instantiated with access to the following:
                * Its parent node's RunContext instance (so it can make its own based on that if needed)
                * The Journal instance for sending messages
                * The AgentToolFactory instance so its later possible tool calls can go through the same procedure
                * A copy of its own agent spec dictionary
                * The arguments passed by the LLM
                * The single sly_data instance for private data shared by all the agents within the network.

        * A build() method is invoked on the node/tool.  This sets the tool in motion (asynchronously),
          but this means different things for different kinds of nodes/tools:
            * ExternalTool - invoke the external agent network referenced in the spec
                    by calling its streaming_chat() and wait for the results to come in
            * ClassTool - instantiate and call the invoke() method of the CodedTool referenced in the spec
                    results are returned as a plaintext string.  It's within a CodedTool's invoke()
                    that calls to web services and use of the sly_data is made if needed.
            * BranchTool - Do a bunch of things:
                * Call create_resources() on its new RunContext
                * Invoke the Agent/LLM with a call to RunContext.submit_message() with
                      the instructions and command from its spec, along with text that
                      specifies what the arguments are.
                * Wait on the Run that is produced from that submit_message()
                * Enter a similar loop as that of  the front man which looks to see
                        if the results require more action. If more action is required,
                        a recursion into make_tool_function_calls() is made, but this time
                        at the level of a different agent within the hierarchy (not the front man).
                * Report the results when that loop is finished.

        * Results from each tool/node invoked (there might be more than one at a time)
            are compiled back into the chat history stored in the RunContext
            and sent over the queue in the Journal for reporting back to the client.

        * Each tool/node that is actualy called has its RunContext's delete_resources() method called,
            thus tearing down any resources associated with that agent's communication with the
            outside world (LLM or agent network, or whatever).

Here is an image to help:

![NeuroSan Information Flow](neuro_san_information_flow_bw.png)
