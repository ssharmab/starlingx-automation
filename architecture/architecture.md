

---------------------------------------------------------
| Area            | Decision                            |
| --------------- | ----------------------------------- |
| State ownership | Agent owns state                    |
| Tool ownership  | Tools return facts only             |
| Observe()       | Returns ToolResult                  |
| Reason()        | Produces conclusions                |
| Decide()        | Produces Decision                   |
| Act()           | Executes tool                       |
| Failures        | Become observations                 |
| Missing tool    | ToolResult failure, not exception   |
| Human input     | Decision(tool="request_user_input") |
| Goal model      | Single goal per agent               |
| History         | Store decisions, not tool names     |
| Correlation ID  | BaseAgent owns it                   |
| Infinite loops  | Maximum iteration count             |


## The run loop



