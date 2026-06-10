import asyncio
import os
import sys

async def test():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from langchain_mcp_adapters.tools import load_mcp_tools
    from services.agent.incident_agent import IncidentAgent
    
    agent = IncidentAgent()
    print('base_tools args_schemas:')
    for t in agent.base_tools:
        print(f'{t.name}: {getattr(t, "args_schema")}')

    python_exe = os.path.join(os.getcwd(), 'venv', 'Scripts', 'python.exe')
    server_params = StdioServerParameters(
        command=python_exe,
        args=['-m', 'services.diagnostics.server']
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            raw_mcp_tools = await load_mcp_tools(session)
            print('\nraw_mcp_tools args_schemas:')
            for t in raw_mcp_tools:
                print(f'{t.name}: {getattr(t, "args_schema")}')
                
            mcp_tools = []
            from langchain_core.tools import Tool
            import json
            
            for t in raw_mcp_tools:
                def make_wrapper(orig_tool):
                    def wrapped(*args, **kwargs) -> str:
                        action_input = args[0] if args else kwargs.get("action_input", kwargs.get("tool_input", ""))
                        if not isinstance(action_input, str): action_input = str(action_input)
                        try:
                            parsed_kwargs = json.loads(action_input)
                        except Exception:
                            parsed_kwargs = {"service_name": action_input.strip()}
                        return orig_tool.invoke(parsed_kwargs)
                    return Tool(
                        name=orig_tool.name,
                        description=orig_tool.description,
                        func=wrapped
                    )
                mcp_tools.append(make_wrapper(t))
                
            print('\nwrapped_mcp_tools args_schemas:')
            for t in mcp_tools:
                print(f'{t.name}: {getattr(t, "args_schema")}')

asyncio.run(test())
