import os
import requests
import json
from dotenv import load_dotenv

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp library not found. Please install with: pip install \"mcp[cli]\" requests python-dotenv")
    import sys
    sys.exit(1)

# Load environment variables
load_dotenv()

N8N_API_KEY = os.getenv("N8N_API_KEY")
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "https://n8n.parallext.cloud").rstrip('/')

# Create MCP server using FastMCP
mcp = FastMCP("n8n-manager")

def _request(method, endpoint, data=None, params=None):
    """Helper for n8n API requests"""
    if not N8N_API_KEY:
        return {"error": "N8N_API_KEY not found in .env"}
        
    url = f"{N8N_BASE_URL}/api/v1/{endpoint}"
    headers = {"X-N8N-API-KEY": N8N_API_KEY}
    
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            # For activation/deactivation, some endpoints accept empty body or specific params
            resp = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            resp = requests.put(url, headers=headers, json=data)
        else:
            return {"error": f"Method {method} not supported"}
            
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
             error_msg += f" Response: {e.response.text}"
        return {"error": error_msg}

@mcp.tool()
def list_workflows(active_only: bool = False) -> str:
    """List all n8n workflows. Returns a formatted table string."""
    params = {"active": "true"} if active_only else {}
    data = _request("GET", "workflows", params=params)
    
    if "error" in data:
        return f"Error Listing Workflows: {data['error']}"
    
    wfs = data.get("data", [])
    if not wfs:
        return "No workflows found."
        
    result = f"{'ID':<25} {'STATUS':<10} {'NAME'}\n"
    result += "-" * 60 + "\n"
    for wf in wfs:
        status = "Active" if wf.get("active") else "Inactive"
        result += f"{wf['id']:<25} {status:<10} {wf['name']}\n"
    return result

@mcp.tool()
def get_workflow(workflow_id: str) -> str:
    """Get full JSON definition of a workflow."""
    data = _request("GET", f"workflows/{workflow_id}")
    if "error" in data:
        return f"Error Getting Workflow: {data['error']}"
    return json.dumps(data, indent=2, ensure_ascii=False)

@mcp.tool()
def activate_workflow(workflow_id: str, active: bool = True) -> str:
    """Activate or deactivate a workflow."""
    action = "activate" if active else "deactivate"
    endpoint = f"workflows/{workflow_id}/{action}"
    
    # activation endpoint is POST /workflows/{id}/activate
    data = _request("POST", endpoint)
    if "error" in data:
        return f"Error {action}ing workflow: {data['error']}"
    
    return f"Workflow {workflow_id} {action}d successfully."

@mcp.tool()
def update_node_parameter(workflow_id: str, node_name: str, parameter_path: str, value: str) -> str:
    """
    Update a specific parameter in a node (e.g. 'parameters.options.systemMessage').
    Note: Value is treated as string. To update nested objects or arrays, pass JSON string.
    """
    # 1. Fetch current workflow
    wf_data = _request("GET", f"workflows/{workflow_id}")
    if "error" in wf_data: return f"Error fetching workflow: {wf_data['error']}"
    
    # 2. Find node
    nodes = wf_data.get("nodes", [])
    target_node = next((n for n in nodes if n["name"] == node_name), None)
    
    if not target_node:
        return f"Node '{node_name}' not found in workflow {workflow_id}."
        
    # 3. Update paths
    keys = parameter_path.split('.')
    current = target_node
    
    try:
        # Navigate to the parent object of the target key
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
            
        # Set the value
        target_key = keys[-1]
        current[target_key] = value
    except Exception as e:
         return f"Error navigating parameter path: {str(e)}"
    
    # 4. Push update (PUT)
    # n8n API expects full workflow object
    update_res = _request("PUT", f"workflows/{workflow_id}", data=wf_data)
    
    if "error" in update_res:
         return f"Error updating workflow: {update_res['error']}"
         
    return f"Node '{node_name}' updated successfully."

if __name__ == "__main__":
    mcp.run()
