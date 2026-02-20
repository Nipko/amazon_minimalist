#!/usr/bin/env python3
"""
n8n Manager — CLI tool to manage n8n workflows via API.
"""

import os
import sys
import json
import requests
import argparse
import datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
N8N_API_KEY = os.getenv("N8N_API_KEY")
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "https://n8n.parallext.cloud").rstrip('/')

# ANSI Colors
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'
BOLD = '\033[1m'

class N8nClient:
    def __init__(self, api_key: str, base_url: str):
        if not api_key:
            print(f"{RED}Error: N8N_API_KEY not found in .env file.{RESET}")
            print(f"Please add N8N_API_KEY=your-key to your .env file.")
            sys.exit(1)
            
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "X-N8N-API-KEY": self.api_key
        }

    def _get(self, endpoint: str, params: Dict = None) -> Any:
        try:
            url = f"{self.base_url}/api/v1/{endpoint}"
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"{RED}API Error (GET {endpoint}): {e}{RESET}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"{RED}Response: {e.response.text}{RESET}")
            return None

    def _post(self, endpoint: str, data: Dict) -> Any:
        try:
            url = f"{self.base_url}/api/v1/{endpoint}"
            headers = self.headers.copy()
            headers["Content-Type"] = "application/json"
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"{RED}API Error (POST {endpoint}): {e}{RESET}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"{RED}Response: {e.response.text}{RESET}")
            return None

    def _put(self, endpoint: str, data: Dict) -> Any:
        try:
            url = f"{self.base_url}/api/v1/{endpoint}"
            headers = self.headers.copy()
            headers["Content-Type"] = "application/json"
            response = requests.put(url, headers=headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"{RED}API Error (PUT {endpoint}): {e}{RESET}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"{RED}Response: {e.response.text}{RESET}")
            return None

    def list_workflows(self, active: Optional[bool] = None):
        params = {}
        if active is not None:
            params["active"] = "true" if active else "false"
            
        data = self._get("workflows", params)
        if not data:
            return

        print(f"\n{BOLD}Available Workflows:{RESET}")
        print(f"{'ID':<25} {'STATUS':<10} {'NAME'}")
        print("-" * 60)
        
        for wf in data.get("data", []):
            status = f"{GREEN}Active{RESET}" if wf.get("active") else f"{YELLOW}Inactive{RESET}"
            print(f"{wf['id']:<25} {status:<18} {wf['name']}")
        print("")

    def get_workflow(self, wf_id: str) -> Optional[Dict]:
        data = self._get(f"workflows/{wf_id}")
        return data

    def activate_workflow(self, wf_id: str, activate: bool):
        action = "activate" if activate else "deactivate"
        print(f"Trying to {action} workflow {wf_id}...")
        
        # To activate/deactivate, we use the specific endpoint
        endpoint = f"workflows/{wf_id}/{action}"
        result = self._post(endpoint, {})
        
        if result:
            status = "Activated" if activate else "Deactivated"
            print(f"{GREEN}Success: Workflow {status}!{RESET}")

    def export_workflow(self, wf_id: str, filename: str = None):
        wf = self.get_workflow(wf_id)
        if not wf:
            return

        if not filename:
            safe_name = "".join([c if c.isalnum() else "_" for c in wf['name']])
            filename = f"{safe_name}_{wf_id}.json"

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(wf, f, indent=4, ensure_ascii=False)
            print(f"{GREEN}Workflow exported to: {BOLD}{filename}{RESET}")
        except IOError as e:
            print(f"{RED}Error saving file: {e}{RESET}")

    def import_workflow(self, filename: str):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                wf_data = json.load(f)
            
            # Remove ID to create new, or keep to update? usually import implies create new
            if 'id' in wf_data:
                del wf_data['id']
                
            result = self._post("workflows", wf_data)
            if result:
                print(f"{GREEN}Workflow imported successfully! ID: {result['id']}{RESET}")
        except Exception as e:
            print(f"{RED}Error importing workflow: {e}{RESET}")

    def update_node_parameter(self, wf_id: str, node_name: str, param_path: str, value: Any):
        """
        Updates a specific parameter in a node.
        WARNING: This fetches the whole workflow, modifies it locally, and pushes it back.
        """
        print(f"Fetching workflow {wf_id}...")
        wf = self.get_workflow(wf_id)
        if not wf:
            return

        # Create backup first
        self.export_workflow(wf_id, f"backup_{wf_id}.json")
        
        nodes = wf.get("nodes", [])
        target_node = next((n for n in nodes if n["name"] == node_name), None)
        
        if not target_node:
            print(f"{RED}Node '{node_name}' not found in workflow.{RESET}")
            return

        # Navigate and set value
        # param_path supports dot notation e.g. "parameters.options.systemMessage"
        keys = param_path.split('.')
        current = target_node
        
        for i, key in enumerate(keys[:-1]):
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value
        
        print(f"Updating node '{node_name}' param '{param_path}'...")
        
        # PUT request expects the standard workflow object structure
        # Remove metadata not needed for update (like id in root if it causes issues, but PUT /workflows/{id} usually ignores it or expects it match)
        
        update_result = self._put(f"workflows/{wf_id}", wf)
        if update_result:
            print(f"{GREEN}Workflow updated successfully!{RESET}")

    def update_system_prompt(self, wf_id: str, prompt_file: str = "system_prompt.md"):
        """Special helper to update the AI Agent system prompt"""
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                new_prompt = f.read()
        except FileNotFoundError:
            print(f"{RED}File {prompt_file} not found.{RESET}")
            return

        # Find the agent node - usually named "🤖 Sales Agent" or check type
        wf = self.get_workflow(wf_id)
        if not wf:
            return

        agent_node = next((n for n in wf.get("nodes", []) if "n8n-nodes-langchain.agent" in n["type"] or n["name"] == "🤖 Sales Agent"), None)
        
        if not agent_node:
            print(f"{RED}No AI Agent node found.{RESET}")
            return

        node_name = agent_node["name"]
        print(f"Found agent node: {BOLD}{node_name}{RESET}")
        
        # Verify where the prompt is stored. Usually parameters.options.systemMessage or parameters.text if promptType is define
        # Based on previous file view: parameters.options.systemMessage
        
        self.update_node_parameter(wf_id, node_name, "parameters.options.systemMessage", new_prompt)

    def list_executions(self, wf_id: str = None, limit: int = 10):
        params = {"limit": limit}
        if wf_id:
            params["workflowId"] = wf_id
            
        data = self._get("executions", params)
        if not data:
            return

        print(f"\n{BOLD}Recent Executions:{RESET}")
        print(f"{'ID':<10} {'STATUS':<10} {'START TIME':<25} {'WORKFLOW ID'}")
        print("-" * 65)
        
        for ex in data.get("data", []):
            status = ex.get("finished", False)
            status_str = f"{GREEN}Success{RESET}" if status else f"{YELLOW}Running{RESET}"
            # Check for error
            if ex.get("data", {}).get("resultData", {}).get("error"):
                 status_str = f"{RED}Error{RESET}"
                 
            start_time = ex.get("startedAt", "Unknown")
            print(f"{ex['id']:<10} {status_str:<18} {start_time:<25} {ex['workflowId']}")
        print("")

# --- CLI Interface ---

def main():
    parser = argparse.ArgumentParser(description="n8n Manager CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # List
    subparsers.add_parser("list", help="List all workflows")
    
    # Get
    get_parser = subparsers.add_parser("get", help="Get workflow JSON")
    get_parser.add_argument("id", help="Workflow ID")
    
    # Export
    export_parser = subparsers.add_parser("export", help="Export workflow to file")
    export_parser.add_argument("id", help="Workflow ID")
    export_parser.add_argument("file", nargs="?", help="Output filename")
    
    # Import
    import_parser = subparsers.add_parser("import", help="Import workflow from file")
    import_parser.add_argument("file", help="Input JSON file")
    
    # Activate/Deactivate
    subparsers.add_parser("activate", help="Activate workflow").add_argument("id", help="Workflow ID")
    subparsers.add_parser("deactivate", help="Deactivate workflow").add_argument("id", help="Workflow ID")
    
    # Update Node
    update_parser = subparsers.add_parser("update-node", help="Update a specific node parameter")
    update_parser.add_argument("id", help="Workflow ID")
    update_parser.add_argument("node_name", help="Name of the node")
    update_parser.add_argument("param", help="Parameter path (e.g. parameters.url)")
    update_parser.add_argument("value", help="New value")
    
    # Update Prompt
    prompt_parser = subparsers.add_parser("update-prompt", help="Update AI Agent system prompt from valid source file")
    prompt_parser.add_argument("id", help="Workflow ID")
    prompt_parser.add_argument("file", nargs="?", default="system_prompt.md", help="Prompt file (default: system_prompt.md)")
    
    # Executions
    exec_parser = subparsers.add_parser("executions", help="List executions")
    exec_parser.add_argument("id", nargs="?", help="Filter by Workflow ID")
    exec_parser.add_argument("--limit", type=int, default=10, help="Number of executions")

    args = parser.parse_args()
    client = N8nClient(N8N_API_KEY, N8N_BASE_URL)

    if args.command == "list":
        client.list_workflows()
    elif args.command == "get":
        wf = client.get_workflow(args.id)
        if wf:
            print(json.dumps(wf, indent=2, ensure_ascii=False))
    elif args.command == "export":
        client.export_workflow(args.id, args.file)
    elif args.command == "import":
        client.import_workflow(args.file)
    elif args.command == "activate":
        client.activate_workflow(args.id, True)
    elif args.command == "deactivate":
        client.activate_workflow(args.id, False)
    elif args.command == "update-node":
        client.update_node_parameter(args.id, args.node_name, args.param, args.value)
    elif args.command == "update-prompt":
        client.update_system_prompt(args.id, args.file)
    elif args.command == "executions":
        client.list_executions(args.id, args.limit)
    else:
        # Interactive mode if no args
        while True:
            print(f"\n{BOLD}n8n Manager Request{RESET}")
            print("1. List Workflows")
            print("2. Get Workflow Details")
            print("3. Export Workflow")
            print("4. Update System Prompt")
            print("5. List Executions")
            print("q. Quit")
            
            choice = input(f"\n{CYAN}Select option: {RESET}")
            
            if choice == '1':
                client.list_workflows()
            elif choice == '2':
                wid = input("Workflow ID: ")
                wf = client.get_workflow(wid)
                if wf:
                    print(json.dumps(wf, indent=2, ensure_ascii=False))
            elif choice == '3':
                wid = input("Workflow ID: ")
                client.export_workflow(wid)
            elif choice == '4':
                wid = input("Workflow ID: ")
                client.update_system_prompt(wid)
            elif choice == '5':
                wid = input("Workflow ID (optional): ")
                client.list_executions(wid if wid else None)
            elif choice.lower() == 'q':
                break

if __name__ == "__main__":
    main()
