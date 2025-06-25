from typing import Dict, List, Optional
import os
import asyncio

from azure.mgmt.cognitiveservices.models import Deployment
from schema import ModelInfo, DeploymentUpdateRequest

# Import utility functions
from utils import (
    load_model_data,
    get_azure_credential,
    fetch_cognitive_service_accounts,
    fetch_deployments_for_account,
    query_model_retirement_info,
    get_existing_deployment,
    apply_deployment_filters, 
    create_deployment_model,
    create_deployment_properties,
    create_sku,
    execute_deployment_update,
    get_quota_usage,
    validate_update_request
)


# Initialize Azure credentials and load model data
model_data = load_model_data()
cred = get_azure_credential()


async def get_deployed_models(model_filter: Optional[List[str]] = None,
                            sku_filter: Optional[List[str]] = None,
                            location_filter: Optional[List[str]] = None,
                            account_filter: Optional[List[str]] = None,
                            resource_group_filter: Optional[List[str]] = None) -> List[Dict]:
    """
    Get all deployed OpenAI models for a given subscription ID with optional filtering.
    
    Args:
        model_filter: Filter by model names
        sku_filter: Filter by SKU names
        location_filter: Filter by deployment locations
        account_filter: Filter by account names
        resource_group_filter: Filter by resource group names
    
    Returns:
        List[Dict]: List of deployments with their details
    """
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    
    # Get all cognitive service accounts
    accounts = await fetch_cognitive_service_accounts(cred, subscription_id)

    # Apply account and resource group filters if provided
    if account_filter:
        accounts = [a for a in accounts if a.get('name') in account_filter]
    if resource_group_filter:
        accounts = [a for a in accounts if a.get('resourceGroup') in resource_group_filter]
    
    # Get deployments for each account
    deployments = []
    
    async def _collect_deployments(account):
        account_deployments = await fetch_deployments_for_account(cred, subscription_id, account)
        deployments.extend(account_deployments)
            
    await asyncio.gather(*[_collect_deployments(account) for account in accounts])

    # Ensure all deployments are serializable
    serializable_deployments = [dict(d) for d in deployments]
    
    # Apply filters if provided
    if model_filter or sku_filter or location_filter:
        serializable_deployments = apply_deployment_filters(
            serializable_deployments, 
            model_filter, 
            sku_filter, 
            location_filter
        )

    # Apply account and resource group filters to deployments as well (in case needed)
    if account_filter:
        serializable_deployments = [d for d in serializable_deployments if d.get('account_name') in account_filter]
    if resource_group_filter:
        serializable_deployments = [d for d in serializable_deployments if d.get('resource_group') in resource_group_filter]

    return serializable_deployments


async def query_model_info(model_infos: List[ModelInfo]) -> List[Dict]:
    """
    Query the retirement date and replacement model for given model names and versions.

    Args:
        model_infos (List[ModelInfo]): List of ModelInfo objects containing model names and versions.

    Returns:
        List[Dict]: List of dictionaries with retirement_date and replacement_model, or error info for each pair.
    """
    results = []
    for info in model_infos:
        model_name = info.model_name
        version = info.model_version
        
        result = query_model_retirement_info(model_data, model_name, version)
        results.append(result)
    
    return results


async def update_deployed_model(
    resource_group: str,
    account_name: str,
    deployment_name: str,
    new_model_name: Optional[str] = None,
    new_model_version: Optional[str] = None,
    new_sku_name: Optional[str] = None,
    new_sku_capacity: Optional[int] = None
) -> Dict:
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")

    try:
        if not all([resource_group, account_name, deployment_name]):
            return {
                "success": False,
                "error": "Missing required parameters: resource_group, account_name, or deployment_name",
                "message": f"Failed to update deployment '{deployment_name}'"
            }

        # Ensure update intent is unambiguous
        updating_model = new_model_name is not None
        updating_sku = new_sku_name is not None or new_sku_capacity is not None

        # if updating_model and updating_sku:
        #     return {
        #         "success": False,
        #         "error": "Cannot update both model and SKU in the same operation",
        #         "message": f"Failed to update deployment '{deployment_name}'"
        #     }

        if not updating_model and not updating_sku:
            return {
                "success": False,
                "error": "No changes specified: either model or SKU must be updated",
                "message": f"No update performed for deployment '{deployment_name}'"
            }

        existing, error_msg = await get_existing_deployment(
            cred, subscription_id, resource_group, account_name, deployment_name
        )
        if existing is None:
            return {
                "success": False,
                "error": error_msg or f"Deployment '{deployment_name}' not found",
                "message": f"Failed to retrieve deployment '{deployment_name}'"
            }

        # Prepare updated model and properties
        model = existing.properties.model
        if updating_model:
            try:
                model = create_deployment_model(new_model_name, new_model_version)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to create model configuration: {str(e)}",
                    "message": f"Invalid model configuration for '{deployment_name}'"
                }

        try:
            new_properties = create_deployment_properties(existing, model)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create deployment properties: {str(e)}",
                "message": f"Invalid deployment properties for '{deployment_name}'"
            }

        try:
            sku = create_sku(existing, new_sku_name, new_sku_capacity)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create SKU configuration: {str(e)}",
                "message": f"Invalid SKU configuration for '{deployment_name}'"
            }

        deployment_parameters = Deployment(sku=sku, properties=new_properties)

        result, error_msg = await execute_deployment_update(
            cred, subscription_id, resource_group, account_name,
            deployment_name, deployment_parameters
        )
        if result is None:
            return {
                "success": False,
                "error": error_msg or "Unknown error during deployment update",
                "message": f"Failed to update deployment '{deployment_name}'"
            }

        return {
            "success": True,
            "data": result,
            "message": f"Successfully updated deployment '{deployment_name}'"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "message": f"Failed to update deployment '{deployment_name}'"
        }


async def batch_update_deployed_models(ListUpdateInfo: List[DeploymentUpdateRequest]) -> List[Dict]:
    if not ListUpdateInfo:
        return [{
            "success": False,
            "error": "No update requests provided",
            "message": "Batch update failed: Empty request list"
        }]

    results = []
    successful_updates = 0
    failed_updates = 0

    print(f"Starting batch update for {len(ListUpdateInfo)} deployments...")

    for i, update_info in enumerate(ListUpdateInfo, 1):
        try:
            print(f"\nProcessing update {i}/{len(ListUpdateInfo)}")

            # validation_error = validate_update_request(update_info)
            # if validation_error:
            #     result = {
            #         "success": False,
            #         "error": validation_error,
            #         "message": f"Validation failed for deployment '{getattr(update_info.update, 'deployment_name', 'unknown')}'"
            #     }
            #     results.append(result)
            #     failed_updates += 1
            #     print(f"Validation failed: {validation_error}")
            #     continue

            result = await update_deployed_model(
                resource_group=update_info.resource_group,
                account_name=update_info.account_name,
                deployment_name=update_info.update.deployment_name,
                new_model_name=getattr(update_info.update, "new_model_name", None),
                new_model_version=getattr(update_info.update, "new_model_version", None),
                new_sku_name=getattr(update_info.update, "new_sku_name", None),
                new_sku_capacity=getattr(update_info.update, "new_sku_capacity", None),
            )

            result["deployment_info"] = {
                "resource_group": update_info.resource_group,
                "account_name": update_info.account_name,
                "deployment_name": update_info.update.deployment_name
            }

            results.append(result)

            if result["success"]:
                successful_updates += 1
                print(f"✓ Successfully updated deployment '{update_info.update.deployment_name}'")
            else:
                failed_updates += 1
                print(f"✗ Failed to update deployment '{update_info.update.deployment_name}': {result.get('error', 'Unknown error')}")

        except Exception as e:
            error_result = {
                "success": False,
                "error": f"Unexpected error during update: {str(e)}",
                "message": f"Failed to process update for deployment '{getattr(update_info.update, 'deployment_name', 'unknown')}'",
                "deployment_info": {
                    "resource_group": getattr(update_info, 'resource_group', 'unknown'),
                    "account_name": getattr(update_info, 'account_name', 'unknown'),
                    "deployment_name": getattr(update_info.update, 'deployment_name', 'unknown') if hasattr(update_info, 'update') else 'unknown'
                }
            }
            results.append(error_result)
            failed_updates += 1
            print(f"✗ Unexpected error processing update {i}: {str(e)}")

    summary = {
        "batch_summary": {
            "total_requests": len(ListUpdateInfo),
            "successful_updates": successful_updates,
            "failed_updates": failed_updates,
            "success_rate": f"{(successful_updates / len(ListUpdateInfo) * 100):.1f}%" if ListUpdateInfo else "0%"
        }
    }

    print(f"\nBatch update completed:")
    print(f"  Total requests: {len(ListUpdateInfo)}")
    print(f"  Successful: {successful_updates}")
    print(f"  Failed: {failed_updates}")
    print(f"  Success rate: {summary['batch_summary']['success_rate']}")

    if results:
        results[0].update(summary)
    else:
        results.append({
            "success": False,
            "error": "No valid updates processed",
            "message": "Batch update completed with no valid operations",
            **summary
        })

    return results


def get_model_quota(location: str) -> List[dict]:
    """
    Get quota usage for deployed models in a given location, optionally filtered by deployment type and model name.

    Args:
        location: Azure region/location (e.g., "eastus")
        deployment_type: Filter by deployment type (e.g., "Standard") (optional)
        model_name: Filter by model name (optional)

    Returns:
        List[dict]: List of usage/quota dictionaries
    """
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    return get_quota_usage(cred, subscription_id, location)


# Define available tools for the API
available_tools = [
    {
        "type": "function",
        "function": {
            "name": "get_deployed_models",
            "description": "Get detail information about all deployed OpenAI models with optional filtering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by model names (optional)"
                    },
                    "sku_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by SKU names (optional)"
                    },
                    "location_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by deployment locations (optional)"
                    },
                    "account_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by account names (optional)"
                    },
                    "resource_group_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by resource group names (optional)"
                    }
                },
                "required": ['model_filter', 'sku_filter', 'location_filter', 'account_filter', 'resource_group_filter'],
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
            "description": "Batch update Azure deployments by model or SKU change (but not both).",
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
                                    "required": ["deployment_name", "new_model_name", "new_model_version", "new_sku_name", "new_sku_capacity"], 
                                    "additionalProperties": False
                                }
                            },
                            "required": ["resource_group", "account_name", "update"],
                            "additionalProperties": False
                        },
                        "description": "List of deployment update requests. Must include deployment_name, and either model or SKU update (not both)."
                    }
                },
                "required": ["ListUpdateInfo"],
                "additionalProperties": False
            },
            "strict": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_model_quota",
            "description": "Get quota usage for deployed models in a given location, optionally filtered by deployment type and model name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Azure region/location (e.g., 'eastus')."
                    }
                },
                "required": ['location'],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
]


async def call_function(name: str, args: dict):
    """
    Function dispatcher for handling tool calls.
    
    Args:
        name: Function name to call
        args: Arguments to pass to the function
        
    Returns:
        Function result
    """
    if name == "get_deployed_models":
        print("\nPython running get_deployed_models")
        return await get_deployed_models(
            model_filter=args.get("model_filter"),
            sku_filter=args.get("sku_filter"),
            location_filter=args.get("location_filter"),
            account_filter=args.get("account_filter"),
            resource_group_filter=args.get("resource_group_filter")
        )
    elif name == "query_model_info":
        print("\nPython running query_model_info")
        model_infos = [ModelInfo(**info) for info in args["model_infos"]]
        return await query_model_info(model_infos)
    elif name == "batch_update_deployed_models":
        print("\nPython running batch_update_deployed_models")
        try:
            ListUpdateInfo = [DeploymentUpdateRequest(**info) for info in args["ListUpdateInfo"]]
            return await batch_update_deployed_models(ListUpdateInfo)
        except Exception as e:
            return [{
                "success": False,
                "error": f"Failed to parse update requests: {str(e)}",
                "message": "Batch update failed due to invalid request format",
                "batch_summary": {
                    "total_requests": len(args.get("ListUpdateInfo", [])),
                    "successful_updates": 0,
                    "failed_updates": len(args.get("ListUpdateInfo", [])),
                    "success_rate": "0%"
                }
            }]
    elif name == "get_model_quota":
        print("\nPython running get_model_quota")
        return get_model_quota(
            location=args.get("location")
        )
    raise ValueError(f"Unknown function: {name}")