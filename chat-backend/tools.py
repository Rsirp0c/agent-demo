from typing import Dict, List, Optional
import json, os
import asyncio

from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.mgmt.cognitiveservices.models import (
    Deployment,
    DeploymentProperties,
    DeploymentModel,
    Sku
)

# Initialize Azure credentials and load model data
with open("model_info.json", "r") as f:
    model_data = json.load(f)

cred = DefaultAzureCredential()


# Function for tool use
async def get_deployed_models() -> List[Dict]:
    """
    Get all deployed OpenAI models for a given subscription ID.
    
    Args:
        subscription_id (str): Azure subscription ID
        
    Returns:
        List[Dict]: List of deployments with their details
    """
    rg_client = ResourceGraphClient(cred)
    
    # Query Resource Graph for OpenAI accounts
    query = QueryRequest(
        query="""
        Resources
        | where type == 'microsoft.cognitiveservices/accounts'
        | where kind =~ 'AIServices'
        | where resourceGroup == 'harry-foundry-agent-test-group'
        | project id, name, subscriptionId, resourceGroup, location
        """,
        subscriptions=[os.getenv("AZURE_SUBSCRIPTION_ID")],
        result_format="objectArray"
    )
    accounts = rg_client.resources(query).data

    # save accounts to a file
    with open("accounts.json", "w") as f:
        import json
        json.dump([dict(a) for a in accounts], f, indent=4)
    

    if not accounts:
        accounts = [
            {
                "id": "/subscriptions/ce6cadb9-b67f-4f21-9b04-e3e9cbc558b2/resourceGroups/harry-foundry-agent-test-group/providers/Microsoft.CognitiveServices/accounts/foundry-agent-test",
                "name": "foundry-agent-test",
                "subscriptionId": "ce6cadb9-b67f-4f21-9b04-e3e9cbc558b2",
                "resourceGroup": "harry-foundry-agent-test-group",
                "location": "eastus"
            }
        ]

    
    # Get deployments for each account
    deployments = []
    async def _get_deployments(acct):
        client = CognitiveServicesManagementClient(cred, os.getenv("AZURE_SUBSCRIPTION_ID"))
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

    serializable_deployments = [dict(d) for d in deployments]
    
    # save return results to a file
    with open("deployments.json", "w") as f:
        import json
        json.dump(serializable_deployments, f, indent=4)

    return serializable_deployments

async def query_model_info(model_names: List[str], versions: List[str]) -> List[Dict]:
    """
    Query the retirement date and replacement model for given model names and versions.

    Args:
        model_names (List[str]): List of model names to query.
        versions (List[str]): List of version strings (use empty string if not versioned).

    Returns:
        List[Dict]: List of dictionaries with retirement_date and replacement_model, or error info for each pair.
    """
    results = []
    for model_name, version in zip(model_names, versions):
        if model_name not in model_data:
            results.append({"model_name": model_name, "version": version, "error": f"Model '{model_name}' not found."})
            continue

        version_dict = model_data[model_name]
        if version not in version_dict:
            results.append({"model_name": model_name, "version": version, "error": f"Version '{version}' not found for model '{model_name}'."})
            continue

        entry = version_dict[version]
        results.append({
            "model_name": model_name,
            "version": version,
            "retirement_date": entry.get("retirement_date", "Unknown"),
            "replacement_model": entry.get("replacement_model", "None")
        })
    return results
    
async def update_deployed_model(
    resource_group: str,
    account_name: str,
    deployment_name: str,
    new_model_name: str,
    new_model_version: Optional[str] = None,  
    new_sku_name: Optional[str] = None,       
    new_sku_capacity: Optional[int] = None    
):
    """
    Updates the model family or version of an existing Azure Cognitive Services deployment.

    Only model fields are replaced; other deployment properties are preserved.
    SKU can be updated if specified.

    Returns:
        dict: {
            "deployment": <updated deployment as dict>,
            "url": <Azure Portal URL>
        } or None if failed.
    """
    client = CognitiveServicesManagementClient(cred, os.getenv("AZURE_SUBSCRIPTION_ID"))

    try:
        existing = client.deployments.get(
            resource_group_name=resource_group,
            account_name=account_name,
            deployment_name=deployment_name
        )
    except Exception:
        return None

    new_model = DeploymentModel(
        name=new_model_name,
        version=new_model_version,
        format="OpenAI"
    )

    new_properties = DeploymentProperties(
        provisioning_state=existing.properties.provisioning_state,
        model=new_model,
        capabilities=existing.properties.capabilities,
        rai_policy_name=existing.properties.rai_policy_name,
        rate_limits=existing.properties.rate_limits,
        version_upgrade_option=getattr(existing.properties, 'version_upgrade_option', None),
        current_capacity=getattr(existing.properties, 'current_capacity', None)
    )

    if new_sku_name is not None or new_sku_capacity is not None:
        sku_name = new_sku_name or existing.sku.name
        sku_capacity = new_sku_capacity or existing.sku.capacity
        sku = Sku(name=sku_name, capacity=sku_capacity)
    else:
        sku = existing.sku

    deployment_parameters = Deployment(
        sku=sku,
        properties=new_properties
    )

    try:
        poller = client.deployments.begin_create_or_update(
            resource_group_name=resource_group,
            account_name=account_name,
            deployment_name=deployment_name,
            deployment=deployment_parameters
        )
        updated_deployment = poller.result()
        deployment_dict = (
            updated_deployment.as_dict()
            if hasattr(updated_deployment, "as_dict")
            else str(updated_deployment)
        )
        url = f"https://portal.azure.com/#resource{updated_deployment.id}"
        return {"deployment": deployment_dict, "url": url}
    except Exception:
        return None

async def batch_update_deployed_models(
    resource_group: List[str],
    account_name: List[str],
    updates: List[Dict]
) -> List[Dict]:
    """
    Batch updates multiple Azure Cognitive Services deployments.

    Args:
        resource_group (List[str]): List of resource groups for each deployment.
        account_name (List[str]): List of account names for each deployment.
        updates (List[Dict]): List of update parameters for each deployment.

    Returns:
        List[Dict]: List of results for each update operation.
    """
    tasks = []
    for rg, acct, update in zip(resource_group, account_name, updates):
        task = update_deployed_model(
            resource_group=rg,
            account_name=acct,
            deployment_name=update["deployment_name"],
            new_model_name=update["new_model_name"],
            new_model_version=update.get("new_model_version"),
            new_sku_name=update.get("new_sku_name"),
            new_sku_capacity=update.get("new_sku_capacity")
        )
        tasks.append(task)

    return await asyncio.gather(*tasks)

# Define available tools
available_tools = [
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
    },
    {
        "type": "function",
        "function": {
            "name": "query_model_info",
            "description": "Query the retirement date and replacement model for given model names and versions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of model names to query."
                    },
                    "versions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of version strings (use empty string if not versioned)."
                    }
                },
                "required": ["model_names", "versions"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_update_deployed_models",
            "description": "Batch update multiple Azure Cognitive Services deployments. Each update should include deployment_name, new_model_name, and optionally new_model_version, new_sku_name, new_sku_capacity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_group": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of resource groups for each deployment."
                    },
                    "account_name": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of account names for each deployment."
                    },
                    "updates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "deployment_name": {"type": "string"},
                                "new_model_name": {"type": "string"},
                                "new_model_version": {"type": "string"},
                                "new_sku_name": {"type": "string"},
                                "new_sku_capacity": {"type": "integer"}
                            },
                            "required": ["deployment_name", "new_model_name", "new_model_version", "new_sku_name", "new_sku_capacity"], 
                            "additionalProperties": False,
                        },
                        "description": "List of update parameters for each deployment."
                    }
                },
                "required": ["resource_group", "account_name", "updates"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
]

async def call_function(name: str, args: dict):
    if name == "get_deployed_models":
        return await get_deployed_models()
    elif name == "query_model_info":
        return await query_model_info(args["model_names"], args["versions"])
    elif name == "batch_update_deployed_models":
        return await batch_update_deployed_models(
            args["resource_group"],
            args["account_name"],
            args["updates"]
        )
    raise ValueError(f"Unknown function: {name}")