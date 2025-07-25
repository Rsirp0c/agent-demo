from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json, os
import asyncio
import urllib.parse

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


def load_model_data(file_path: str = "model_info.json") -> dict:
    """Load model data from JSON file."""
    with open(file_path, "r") as f:
        return json.load(f)


def get_azure_credential():
    """Get Azure credential for authentication based on environment."""
    # env = os.getenv("PROD_OR_TEST", "test").lower()
    if env == "prod":
        class StaticTokenCredential(TokenCredential):
            """Wrap an already-acquired ARM token so SDK clients will accept it."""
            def __init__(self, token: str, expires_in_sec: int = 360000):
                self._access_token = AccessToken(
                    token=token,
                    expires_on=int((datetime.utcnow() + timedelta(seconds=expires_in_sec)).timestamp())
                )

            def get_token(self, *scopes, **kwargs):
                return self._access_token

        return StaticTokenCredential(os.getenv("AZURE_ACCESS_TOKEN"))
    else:
        return DefaultAzureCredential()
    # return DefaultAzureCredential()


async def fetch_cognitive_service_accounts(credential, subscription_id: str) -> List[Dict]:
    """
    Fetch all cognitive service accounts from Azure Resource Graph.
    
    Args:
        credential: Azure credential object
        subscription_id: Azure subscription ID
        
    Returns:
        List[Dict]: List of cognitive service accounts
    """
    rg_client = ResourceGraphClient(credential)
    
    query = QueryRequest(
        query="""
        Resources
        | where type == 'microsoft.cognitiveservices/accounts'
        | where kind =~ 'AIServices'
        | where resourceGroup == 'harry-foundry-agent-test-group'
        | project id, name, subscriptionId, resourceGroup, location
        """,
        subscriptions=[subscription_id],
        result_format="objectArray"
    )
    
    return rg_client.resources(query).data


async def fetch_deployments_for_account(credential, subscription_id: str, account: Dict) -> List[Dict]:
    """
    Fetch all deployments for a specific cognitive service account.
    
    Args:
        credential: Azure credential object
        subscription_id: Azure subscription ID
        account: Account dictionary with name, resourceGroup, and location
        
    Returns:
        List[Dict]: List of deployments for the account
    """
    client = CognitiveServicesManagementClient(credential, subscription_id)
    deployments = []
    
    for d in client.deployments.list(account["resourceGroup"], account["name"]):
        deployments.append({
            "account_name": account["name"],
            "resource_group": account["resourceGroup"],
            "location": account["location"],
            "deployment_name": d.name,
            "model": d.properties.model.name,
            "version": d.properties.model.version,
            "sku": d.sku.name,
            "capacity": d.sku.capacity
        })
    
    return deployments

def apply_deployment_filters(deployments: List[Dict], 
                           model_filter: Optional[List[str]] = None,
                           sku_filter: Optional[List[str]] = None,
                           location_filter: Optional[List[str]] = None) -> List[Dict]:
    """
    Apply additional filters to deployment list.
    
    Args:
        deployments: List of deployment dictionaries
        model_filter: Filter by model names
        sku_filter: Filter by SKU names
        location_filter: Filter by deployment locations
    """
    filtered_deployments = []

    for deployment in deployments:
        if model_filter and deployment.get("model") not in model_filter:
            continue
        if sku_filter and deployment.get("sku") not in sku_filter:
            continue
        if location_filter and deployment.get("location") not in location_filter:
            continue

        filtered_deployments.append(deployment)

    return filtered_deployments


def query_model_retirement_info(model_data: dict, model_name: str, version: str) -> Dict:
    """
    Query retirement information for a specific model and version.
    
    Args:
        model_data: Dictionary containing model retirement information
        model_name: Name of the model
        version: Version of the model
        
    Returns:
        Dict: Dictionary with retirement_date, replacement_model, or error info
    """
    if model_name not in model_data:
        return {
            "model_name": model_name, 
            "version": version, 
            "error": f"Model '{model_name}' not found."
        }

    version_dict = model_data[model_name]
    if version not in version_dict:
        return {
            "model_name": model_name, 
            "version": version, 
            "error": f"Version '{version}' not found for model '{model_name}'."
        }

    entry = version_dict[version]
    return {
        "model_name": model_name,
        "version": version,
        "retirement_date": entry.get("retirement_date", "Unknown"),
        "replacement_model": entry.get("replacement_model", "None")
    }


async def get_existing_deployment(credential, subscription_id: str, resource_group: str, 
                                account_name: str, deployment_name: str):
    """
    Retrieve an existing deployment configuration.
    
    Args:
        credential: Azure credential object
        subscription_id: Azure subscription ID
        resource_group: Resource group name
        account_name: Cognitive service account name
        deployment_name: Deployment name
        
    Returns:
        Tuple[deployment_object_or_None, error_message_or_None]
    """
    client = CognitiveServicesManagementClient(credential, subscription_id)
    
    try:
        deployment = client.deployments.get(
            resource_group_name=resource_group,
            account_name=account_name,
            deployment_name=deployment_name
        )
        return deployment, None
    except Exception as e:
        error_msg = f"Failed to retrieve deployment '{deployment_name}' in account '{account_name}': {str(e)}"
        print(f"Error retrieving existing deployment: {error_msg}")
        return None, error_msg


def create_deployment_model(model_name: str, model_version: Optional[str] = None) -> DeploymentModel:
    """
    Create a DeploymentModel object.
    
    Args:
        model_name: Name of the model
        model_version: Version of the model
        
    Returns:
        DeploymentModel: Configured deployment model
    """
    return DeploymentModel(
        name=model_name,
        version=model_version,
        format="OpenAI"
    )


def create_deployment_properties(existing_deployment, new_model: DeploymentModel) -> DeploymentProperties:
    """
    Create deployment properties preserving existing configuration with new model.
    
    Args:
        existing_deployment: Existing deployment object
        new_model: New deployment model
        
    Returns:
        DeploymentProperties: Configured deployment properties
    """
    return DeploymentProperties(
        provisioning_state=existing_deployment.properties.provisioning_state,
        model=new_model,
        capabilities=existing_deployment.properties.capabilities,
        rai_policy_name=existing_deployment.properties.rai_policy_name,
        rate_limits=existing_deployment.properties.rate_limits,
        version_upgrade_option=getattr(existing_deployment.properties, 'version_upgrade_option', None),
        current_capacity=getattr(existing_deployment.properties, 'current_capacity', None)
    )


def create_sku(existing_deployment:Sku, new_sku_name: Optional[str] = None, 
               new_sku_capacity: Optional[int] = None) -> Sku:
    """
    Create SKU configuration, preserving existing values if new ones aren't provided.
    
    Args:
        existing_deployment: Existing deployment object
        new_sku_name: New SKU name (optional)
        new_sku_capacity: New SKU capacity (optional)
        
    Returns:
        Sku: Configured SKU object
    """
    if new_sku_name is not None or new_sku_capacity is not None:
        sku_name = new_sku_name or existing_deployment.sku.name
        sku_capacity = new_sku_capacity or existing_deployment.sku.capacity
        return Sku(name=sku_name, capacity=sku_capacity)
    else:
        return Sku(
            name="GlobalStandard",
            capacity=existing_deployment.sku.capacity
        )


async def execute_deployment_update(credential, subscription_id: str, resource_group: str,
                                   account_name: str, deployment_name: str, 
                                   deployment_parameters: Deployment) -> tuple[Optional[Dict], Optional[str]]:
    """
    Execute the deployment update operation.
    
    Args:
        credential: Azure credential object
        subscription_id: Azure subscription ID
        resource_group: Resource group name
        account_name: Account name
        deployment_name: Deployment name
        deployment_parameters: Deployment configuration
        
    Returns:
        Tuple[result_dict_or_None, error_message_or_None]: 
            - Success: ({"deployment": dict, "url": str}, None)
            - Failure: (None, error_message)
    """
    client = CognitiveServicesManagementClient(credential, subscription_id)
    
    try:
        print(f"Starting deployment update for '{deployment_name}' in account '{account_name}'...")
        
        poller = client.deployments.begin_create_or_update(
            resource_group_name=resource_group,
            account_name=account_name,
            deployment_name=deployment_name,
            deployment=deployment_parameters
        )
        
        # Wait for the operation to complete
        updated_deployment = poller.result()
        deployment_dict = (
            updated_deployment.as_dict()
            if hasattr(updated_deployment, "as_dict")
            else str(updated_deployment)
        )
        # Construct Foundry (AI Studio) URL
        resource_id = updated_deployment.id
        encoded_resource_id = urllib.parse.quote(resource_id, safe='')
        wsid = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.CognitiveServices/accounts/{account_name}/projects/firstProject"
        encoded_wsid = urllib.parse.quote(wsid, safe='')
        tenant_id = os.getenv("AZURE_TENANT_ID")
        foundry_url = f"https://ai.azure.com/resource/deployments/{encoded_resource_id}?wsid={encoded_wsid}&tid={tenant_id}"

        print(f"Successfully updated deployment '{deployment_name}'")
        return {"deployment": deployment_dict, "url": foundry_url}, None
    
    except Exception as e:
        error_msg = f"Failed to update deployment '{deployment_name}' in account '{account_name}': {str(e)}"
        print(f"Error updating deployment: {error_msg}")
        return None, error_msg


def validate_update_request(update_info) -> Optional[str]:
    """
    Validate a deployment update request. Either model update or SKU update is allowed, but not both.

    Args:
        update_info: DeploymentUpdateRequest object

    Returns:
        str: Error message if validation fails, None if valid
    """
    try:
        if not update_info.resource_group:
            return "Missing required field: resource_group"
        if not update_info.account_name:
            return "Missing required field: account_name"
        if not update_info.update.deployment_name:
            return "Missing required field: deployment_name"

        updating_model = bool(update_info.update.new_model_name)
        updating_sku = (
            bool(update_info.update.new_sku_name) or
            update_info.update.new_sku_capacity is not None
        )

        if updating_model and updating_sku:
            return "Cannot update model and SKU simultaneously"
        if not updating_model and not updating_sku:
            return "Must specify either a model update or a SKU update"

        if updating_model and not update_info.update.new_model_version:
            return "Missing model version for model update"

        if update_info.update.new_sku_capacity is not None:
            if not isinstance(update_info.update.new_sku_capacity, int) or update_info.update.new_sku_capacity <= 0:
                return "SKU capacity must be a positive integer"

        return None
    except Exception as e:
        return f"Validation error: {str(e)}"

    
def get_quota_usage(credential, subscription_id: str, location: str) -> List[Dict]:
    """
    Get quota usage for deployed models with optional filtering.
    
    Args:
        credential: Azure credential object
        subscription_id: Azure subscription ID  
        location: Azure region/location
        
    Returns:
        List[dict]: Filtered list of usage/quota dictionaries
    """
    client = CognitiveServicesManagementClient(credential, subscription_id)
    usages = [usage.as_dict() for usage in client.usages.list(location=location)]
    
    return usages