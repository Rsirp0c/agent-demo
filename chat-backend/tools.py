from typing import Dict, List
import asyncio
from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient



async def get_deployed_models(subscription_id: str) -> List[Dict]:
    """
    Get all deployed OpenAI models for a given subscription ID.
    
    Args:
        subscription_id (str): Azure subscription ID
        
    Returns:
        List[Dict]: List of deployments with their details
    """
    # Initialize clients
    cred = DefaultAzureCredential()
    rg_client = ResourceGraphClient(cred)
    
    # Query Resource Graph for OpenAI accounts
    query = QueryRequest(
        query="""
        Resources
        | where type == 'microsoft.cognitiveservices/accounts'
        | where kind =~ 'AIServices'
        | project id, name, subscriptionId, resourceGroup, location
        """,
        subscriptions=[subscription_id],
        result_format="objectArray"
    )
    accounts = rg_client.resources(query).data
    
    # Get deployments for each account
    deployments = []
    async def _get_deployments(acct):
        client = CognitiveServicesManagementClient(cred, subscription_id)
        for d in client.deployments.list(acct["resourceGroup"], acct["name"]):
            deployments.append({
                "account_name": acct["name"],
                "resource_group": acct["resourceGroup"],
                "location": acct["location"],
                "deployment_name": d.name,
                "model": d.properties.model.name,
                "version": d.properties.model.version,
                "sku": d.sku.name,
                "capacity": d.sku.capacity
            })
            
    await asyncio.gather(*[_get_deployments(a) for a in accounts])

    # Convert the results to a JSON-serializable format first
    serializable_deployments = [dict(d) for d in deployments]
    
    # save return results to a file
    with open("deployments.json", "w") as f:
        import json
        json.dump(serializable_deployments, f, indent=4)

    return serializable_deployments


# Define available tools
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_deployed_models",
            "description": "Get detail information about all deployed OpenAI models.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
]