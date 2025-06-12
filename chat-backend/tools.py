from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json, os
import asyncio

from azure.identity import DefaultAzureCredential
from azure.core.credentials import AccessToken, TokenCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.mgmt.cognitiveservices.models import (
    Deployment,
    DeploymentProperties,
    DeploymentModel,
    Sku
)
from schema import ModelInfo, DeploymentUpdateRequest


# Initialize Azure credentials and load model data
with open("model_info.json", "r") as f:
    model_data = json.load(f)

# Use DefaultAzureCredential for local development and production
# cred = DefaultAzureCredential()

# For testing purposes, we will use a static token credential
class StaticTokenCredential(TokenCredential):
    """Wrap an already-acquired ARM token so SDK clients will accept it."""
    def __init__(self, token: str, expires_in_sec: int = 360000):
        self._access_token = AccessToken(
            token=token,
            expires_on=int((datetime.utcnow() + timedelta(seconds=expires_in_sec)).timestamp())
        )

    def get_token(self, *scopes, **kwargs):
        return self._access_token

cred = StaticTokenCredential(os.getenv("AZURE_ACCESS_TOKEN"))

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

    return serializable_deployments


async def query_model_info(model_infos: List[ModelInfo]) -> List[Dict]:
    """
    Query the retirement date and replacement model for given model names and versions.

    Args:
        model_infos (List[ModelInfo]): List of ModelInfo objects containing model names and versions.
        class ModelInfo(BaseModel):
            model_name: str
            model_version: str

    Returns:
        List[Dict]: List of dictionaries with retirement_date and replacement_model, or error info for each pair.
    """
    results = []
    for info in model_infos:
        model_name = info.model_name
        version = info.model_version

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
    except Exception as e:
        print(f"Error retrieving existing deployment: {e}")
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
        sku = Sku(
            name="GlobalStandard",
            capacity=existing.sku.capacity
        )

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
    
    except Exception as e:
        print(f"Error updating deployment: {e}")
        return None


async def batch_update_deployed_models(ListUpdateInfo: List[DeploymentUpdateRequest]) -> List[Dict]:
    """
    Batch updates multiple Azure Cognitive Services deployments.

    Args:
        class Update(BaseModel):
            deployment_name: str
            new_model_name: str
            new_model_version: str
            new_sku_name: Optional[str] = None
            new_sku_capacity: Optional[int] = None

        class DeploymentUpdateRequest(BaseModel):
            resource_group: str
            account_name: str
            update: Update

    Returns:
        List[Dict]: List of results for each update operation.
    """
    results = []
    for update_info in ListUpdateInfo:
        result = await update_deployed_model(
            resource_group=update_info.resource_group,
            account_name=update_info.account_name,
            deployment_name=update_info.update.deployment_name,
            new_model_name=update_info.update.new_model_name,
            new_model_version=update_info.update.new_model_version,
            new_sku_name=update_info.update.new_sku_name,
            new_sku_capacity=update_info.update.new_sku_capacity
        )
        results.append(result)
    return results

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
                    "model_infos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "model_name": {"type": "string"},
                                "model_version": {"type": "string"}
                            },
                            "required": ["model_name", "model_version"],
                            "additionalProperties": False,
                        },
                        "description": "List of model info objects, each with model_name and model_version."
                    }
                },
                "required": ["model_infos"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_update_deployed_models",
            "description": "Batch update multiple Azure Cognitive Services deployments. Each update should include resource_group, account_name, and update (with deployment_name, new_model_name, new_model_version, new_sku_name, new_sku_capacity).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ListUpdateInfo": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "resource_group": {"type": "string"},
                                "account_name": {"type": "string"},
                                "update": {
                                    "type": "object",
                                    "properties": {
                                        "deployment_name": {"type": "string"},
                                        "new_model_name": {"type": "string"},
                                        "new_model_version": {"type": "string"},
                                        "new_sku_name": {"type": "string"},
                                        "new_sku_capacity": {"type": "integer"}
                                    },
                                    "required": [
                                        "deployment_name",
                                        "new_model_name",
                                        "new_model_version",
                                        "new_sku_name",
                                        "new_sku_capacity"
                                    ],
                                    "additionalProperties": False,
                                }
                            },
                            "required": ["resource_group", "account_name", "update"],
                            "additionalProperties": False,
                        },
                        "description": "List of deployment update requests."
                    }
                },
                "required": ["ListUpdateInfo"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
]

async def call_function(name: str, args: dict):
    if name == "get_deployed_models":
        print("\nPython running get_deployed_models")
        return await get_deployed_models()
    elif name == "query_model_info":
        print("\nPython running query_model_info")
        # Convert dicts to ModelInfo objects
        model_infos = [ModelInfo(**info) for info in args["model_infos"]]
        return await query_model_info(model_infos)
    elif name == "batch_update_deployed_models":
        print("\nPython running batch_update_deployed_models")
        # Convert dicts to DeploymentUpdateRequest objects
        ListUpdateInfo = [DeploymentUpdateRequest(**info) for info in args["ListUpdateInfo"]]
        return await batch_update_deployed_models(ListUpdateInfo)
    raise ValueError(f"Unknown function: {name}")
