# What we added on top of ADK to use all of A2A

ADK ships one way to reach a remote A2A agent: `RemoteA2aAgent`. It covers one
part of the protocol well and leaves the rest unused. This note lists what ADK
gives out of the box, what is missing, and the small pieces added in this repo
to fill the gap. Everything is verified against google-adk 2.14.1 and
a2a-sdk 1.3.0.

## 1. What A2A offers

An A2A server exposes an agent card and a JSON-RPC endpoint. Beyond "send a
message and read the reply", the protocol has a task lifecycle:

| A2A method | Purpose |
|---|---|
| `message/send` | Send a message. With `return_immediately` the server answers at once with a Task in state `submitted` and keeps working. |
| `message/stream` | Same, but the reply streams status and artifact updates. |
| `tasks/get` | Read a task: state, status message, artifacts, history. |
| `tasks/cancel` | Stop a running task. |
| `tasks/list` | List tasks, filterable by context and state. |
| `tasks/subscribe` | Re-attach to a running task's stream. |
| `tasks/pushNotificationConfig/*` | Register a webhook the server calls when a task changes. |

Two identifiers tie it together. A **task id** names one unit of work. A
**context id** names a conversation; several tasks can share it, and the
server keeps the history.

## 2. What ADK gives out of the box

### Server side: `to_a2a(agent)`

One call wraps any ADK agent in a Starlette app. The ADK executor behind it
already:

- builds the agent card from the agent's name, description and tools;
- emits `submitted`, `working`, `completed`, `failed`, `canceled`;
- stores tasks (in memory by default, a database store can be passed);
- maps the A2A context id to the agent's ADK session, so a later message with
  the same context id continues the conversation;
- honours `tasks/cancel`.

Nothing was added on the server. It supports the whole lifecycle as shipped.

### Client side: `RemoteA2aAgent`

It resolves the agent card, converts ADK content to A2A parts, calls
`message/stream`, and turns the streamed updates back into ADK events. It is
a **call-and-wait** primitive: the caller gets control back only when the
remote agent is done.

How it can be placed under an orchestrator:

| Placement | Behaviour | Parallel calls |
|---|---|---|
| `sub_agents=[remote]` | `transfer_to_agent`: the orchestrator hands over the conversation and stops | no |
| `sub_agents=[remote]`, `mode="task"` | `finish_task` round trip; control returns, but ADK's tool text says "do NOT call this tool in parallel" and the remote must be an ADK task-mode agent | no |
| `tools=[AgentTool(agent=remote)]` | an ordinary function tool; several in one turn run concurrently | **yes** |

What `RemoteA2aAgent` does not expose: returning before the task is done,
reading a task's state later, following up on a task, cancelling, listing.

## 3. What this repo adds

Two files on the client, no changes to ADK itself.

### `client/a2a_client.py`: the lifecycle in plain Python

A thin class over the a2a-sdk client, so the protocol can be used and read
without ADK in the way:

| Method | A2A call | Note |
|---|---|---|
| `start(request)` | `message/send` with `return_immediately=True` | Returns the Task at once. `ClientConfig(streaming=False, polling=True)` makes every send ask for this. |
| `get(task_id)` | `tasks/get` | Flattened to `{task_id, context_id, state, done, status_message, result}`. |
| `wait(task_id, timeout)` | `tasks/get` in a loop | Until terminal or timeout. |
| `follow_up(task_id, message)` | `message/send` with `task_id` or `context_id` | See below. |
| `cancel(task_id)` | `tasks/cancel` | |
| `call(request)` | `start` + `wait` | The blocking call, for comparison. |

The follow-up rule matters. The server rejects a message that names a task
already in a terminal state. So while a task is open (working, input
required) the follow-up names the task; once it is finished the follow-up
names only the context. That starts a new task in the same conversation, and
because ADK maps the context id to its session, the remote agent still has
the earlier exchange. The test proves it: the remote model's second request
carries more history than its first.

### `client/a2a_tools.py`: the same lifecycle as ADK tools

Six functions with a `tool_context` parameter, which ADK injects. Add the list
to an `LlmAgent`'s `tools` and the model can:

- `start_task(request)` and carry on with other tool calls;
- `check_task(task_id)` to peek;
- `wait_for_task(task_id, timeout_seconds)` to collect;
- `send_task_message(task_id, message)` to follow up;
- `cancel_task(task_id)`;
- `list_tasks()`.

The one extra is bookkeeping: each task the model starts is written to
session state under `a2a_tasks`, so a later turn, or a later user message in
the same session, can act on a task id alone. The ADK dev UI shows that state.

### `client/orchestrator/agent.py`: both ways side by side

```python
helper = RemoteA2aAgent(name="helper", agent_card=f"{SERVER_URL}/.well-known/agent-card.json", description="...")
root_agent = LlmAgent(
    model=...,
    instruction=...,
    tools=[AgentTool(agent=helper), *make_task_tools(SERVER_URL)],
)
```

`helper(request)` is the call-and-wait path through ADK's own classes.
`start_task` and friends are the fire-and-forget path. The instruction tells
the model when each fits.

## 4. What is still unused

Available from the same a2a-sdk client, not wired as tools because nothing
here needs them yet:

- `tasks/subscribe`, to re-attach to a running task's stream after a
  disconnect;
- push notifications, so the server calls a webhook instead of the client
  polling `tasks/get`. `ClientConfig(push_notification_config=...)` sets it on
  every send; the client would need an HTTP endpoint to receive them;
- `tasks/list` on the server, which would replace the session-state
  bookkeeping with a server-side query by context id.

## 5. Gotchas met on the way

- a2a-sdk 1.x types are protobuf. The card has no `url` field; the endpoint is
  `supportedInterfaces[0].url`. Parse a card JSON with
  `a2a.client.card_resolver.parse_agent_card`, not `model_validate`.
- `RemoteA2aAgent` resolves its card lazily, so `AgentTool`'s declaration has
  an empty description unless a description, or the card object, is passed at
  construction.
- ADK wraps a list returned by a tool as `{"result": [...]}`. Return dicts.
- httpx clients are bound to an event loop. The tools keep one a2a client per
  running loop.
