import asyncio
import os
import sys

async def test():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from langchain_mcp_adapters.tools import load_mcp_tools
    from services.agent.incident_agent import IncidentAgent
    
    agent = IncidentAgent()

    python_exe = os.path.join(os.getcwd(), 'venv', 'Scripts', 'python.exe')
    server_params = StdioServerParameters(
        command=python_exe,
        args=['-m', 'services.diagnostics.server']
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            raw_mcp_tools = await load_mcp_tools(session)
            mcp_tools = []
            from langchain_core.tools import Tool
            import json
            
            for t in raw_mcp_tools:
                def make_wrapper(orig_tool):
                    def wrapped(*args, **kwargs) -> str:
                        return "Hello"
                    return Tool(
                        name=orig_tool.name,
                        description=orig_tool.description,
                        func=wrapped
                    )
                mcp_tools.append(make_wrapper(t))
                
            all_tools = agent.base_tools + mcp_tools
            
            # Let's manually trigger the tool parsing logic!
            for tool in all_tools:
                if tool.name == "fetch_recent_logs":
                    print("Testing fetch_recent_logs...")
                    try:
                        tool.run("checkout service, last 20 minutes")
                        print("SUCCESS!")
                    except Exception as e:
                        import traceback
                        traceback.print_exc()

asyncio.run(test())
