#!/usr/bin/env python3
"""
PubChemPy FastMCP Server

A FastMCP server providing chemical compound search capabilities
using PubChem database via pubchempy library.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import os

import pubchempy as pcp
import httpx
from pydantic import BaseModel
from fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data models
class ChemicalInfo(BaseModel):
    cid: Optional[int] = None
    iupac_name: Optional[str] = None
    molecular_formula: Optional[str] = None
    molecular_weight: Optional[float] = None
    smiles: Optional[str] = None
    inchi: Optional[str] = None
    inchi_key: Optional[str] = None
    synonyms: List[str] = []
    properties: Dict[str, Any] = {}

class ChemicalSearchResponse(BaseModel):
    success: bool
    query: str
    search_type: str
    results: List[ChemicalInfo] = []
    error: Optional[str] = None
    source: str = "pubchempy"

# Create FastMCP server instance
mcp = FastMCP("pubchempy-mcp-server")

# Global HTTP client
http_client = None

async def get_http_client():
    """Get or create HTTP client"""
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=30.0)
    return http_client

async def cleanup_http_client():
    """Cleanup HTTP client"""
    global http_client
    if http_client:
        await http_client.aclose()
        http_client = None

def extract_compound_properties(compound) -> ChemicalInfo:
    """Extract properties from pubchempy Compound object"""
    try:
        synonyms = []
        if hasattr(compound, 'synonyms') and compound.synonyms:
            synonyms = compound.synonyms[:10]
        
        return ChemicalInfo(
            cid=getattr(compound, 'cid', None),
            iupac_name=getattr(compound, 'iupac_name', None),
            molecular_formula=getattr(compound, 'molecular_formula', None),
            molecular_weight=getattr(compound, 'molecular_weight', None),
            smiles=getattr(compound, 'canonical_smiles', None),
            inchi=getattr(compound, 'inchi', None),
            inchi_key=getattr(compound, 'inchikey', None),
            synonyms=synonyms,
            properties={
                'heavy_atom_count': getattr(compound, 'heavy_atom_count', None),
                'atom_stereo_count': getattr(compound, 'atom_stereo_count', None),
                'bond_stereo_count': getattr(compound, 'bond_stereo_count', None),
                'rotatable_bond_count': getattr(compound, 'rotatable_bond_count', None),
                'h_bond_acceptor_count': getattr(compound, 'h_bond_acceptor_count', None),
                'h_bond_donor_count': getattr(compound, 'h_bond_donor_count', None),
                'topological_polar_surface_area': getattr(compound, 'tpsa', None),
                'xlogp': getattr(compound, 'xlogp', None)
            }
        )
    except Exception as e:
        logger.error(f"Error extracting compound properties: {str(e)}")
        return ChemicalInfo()

async def search_pubchempy(query: str, search_type: str) -> List[ChemicalInfo]:
    """Search using pubchempy library"""
    namespace_map = {
        "name": "name",
        "formula": "formula", 
        "smiles": "smiles"
    }
    
    namespace = namespace_map.get(search_type, "formula")
    
    # Run in thread pool since pubchempy is synchronous
    loop = asyncio.get_event_loop()
    compounds = await loop.run_in_executor(
        None, 
        lambda: pcp.get_compounds(query, namespace=namespace)
    )
    
    results = []
    for compound in compounds[:5]:  # Limit to first 5 results
        props = await loop.run_in_executor(
            None,
            lambda c=compound: extract_compound_properties(c)
        )
        results.append(props)
        
    return results

async def get_synonyms_direct(cid: int, client: httpx.AsyncClient) -> List[str]:
    """Get synonyms using direct API"""
    try:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
        response = await client.get(url)
        
        if response.status_code == 200:
            data = response.json()
            synonyms = data.get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
            return synonyms[:10]  # Limit to first 10
        return []
    except:
        return []

async def search_direct_api(query: str, search_type: str) -> List[ChemicalInfo]:
    """Search using direct PubChem REST API"""
    client = await get_http_client()
    
    input_map = {
        "name": "name",
        "formula": "formula",
        "smiles": "smiles"
    }
    
    input_type = input_map.get(search_type, "formula")
    
    # Get CIDs first
    search_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/{input_type}/{query}/cids/JSON"
    
    response = await client.get(search_url)
    response.raise_for_status()
    
    data = response.json()
    cids = data.get("IdentifierList", {}).get("CID", [])
    
    if not cids:
        return []
    
    # Limit to first 5 CIDs
    cids = cids[:5]
    cid_list = ",".join(map(str, cids))
    
    # Get compound properties
    props_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid_list}/property/MolecularFormula,MolecularWeight,CanonicalSMILES,InChI,InChIKey,IUPACName/JSON"
    
    props_response = await client.get(props_url)
    props_response.raise_for_status()
    
    props_data = props_response.json()
    properties = props_data.get("PropertyTable", {}).get("Properties", [])
    
    results = []
    for prop in properties:
        cid = prop.get("CID")
        synonyms = await get_synonyms_direct(cid, client)
        
        results.append(ChemicalInfo(
            cid=cid,
            iupac_name=prop.get("IUPACName"),
            molecular_formula=prop.get("MolecularFormula"),
            molecular_weight=prop.get("MolecularWeight"),
            smiles=prop.get("CanonicalSMILES"),
            inchi=prop.get("InChI"),
            inchi_key=prop.get("InChIKey"),
            synonyms=synonyms
        ))
    
    return results

@mcp.tool(tags={"search", "chemistry"})
async def search_chemical(
    query: str,
    search_type: str = "formula",
    use_fallback: bool = False,
    ctx: Context = None
) -> str:
    """
    Search for chemical compounds by name, molecular formula, or SMILES string.
    
    Args:
        query: Chemical name, molecular formula, or SMILES string to search for
        search_type: Type of search - 'name', 'formula', or 'smiles'
        use_fallback: Use direct PubChem API instead of pubchempy library
    
    Returns:
        Formatted search results or error message
    """
    if ctx:
        await ctx.info(f"Searching for chemical: {query}")
    
    if search_type not in ["name", "formula", "smiles"]:
        raise ValueError("search_type must be one of: name, formula, smiles")
    
    try:
        results = []
        source = "pubchempy"
        error = None
        
        if not use_fallback:
            try:
                results = await search_pubchempy(query, search_type)
                if ctx:
                    await ctx.info(f"Found {len(results)} compounds using PubChemPy")
            except Exception as e:
                if ctx:
                    await ctx.warning(f"PubChemPy failed: {str(e)}, trying direct API")
                error = f"PubChemPy search failed: {str(e)}"
                
                # Auto-fallback to direct API
                try:
                    results = await search_direct_api(query, search_type)
                    source = "direct_api"
                    error = None
                    if ctx:
                        await ctx.info(f"Found {len(results)} compounds using direct API")
                except Exception as e2:
                    error = f"Both PubChemPy and direct API failed. PubChemPy: {str(e)}, Direct API: {str(e2)}"
                    if ctx:
                        await ctx.error(error)
        else:
            # Use direct API
            try:
                results = await search_direct_api(query, search_type)
                source = "direct_api"
                if ctx:
                    await ctx.info(f"Found {len(results)} compounds using direct API")
            except Exception as e:
                error = f"Direct API search failed: {str(e)}"
                if ctx:
                    await ctx.error(error)
        
        # Create response
        response = ChemicalSearchResponse(
            success=len(results) > 0 and error is None,
            query=query,
            search_type=search_type,
            results=results,
            error=error,
            source=source
        )
        
        # Format the response
        if response.success and response.results:
            # Create formatted text response
            response_text = f"🧪 Chemical Search Results\n"
            response_text += f"Query: {response.query}\n"
            response_text += f"Search Type: {response.search_type}\n"
            response_text += f"Source: {response.source}\n"
            response_text += f"Found {len(response.results)} compound(s)\n\n"
            
            for i, compound in enumerate(response.results, 1):
                response_text += f"--- Compound {i} ---\n"
                
                if compound.cid:
                    response_text += f"PubChem CID: {compound.cid}\n"
                if compound.iupac_name:
                    response_text += f"IUPAC Name: {compound.iupac_name}\n"
                if compound.molecular_formula:
                    response_text += f"Molecular Formula: {compound.molecular_formula}\n"
                if compound.molecular_weight:
                    response_text += f"Molecular Weight: {compound.molecular_weight:.2f} g/mol\n"
                if compound.smiles:
                    response_text += f"SMILES: {compound.smiles}\n"
                if compound.inchi_key:
                    response_text += f"InChI Key: {compound.inchi_key}\n"
                
                if compound.synonyms:
                    synonyms_text = ", ".join(compound.synonyms[:5])
                    if len(compound.synonyms) > 5:
                        synonyms_text += f" (and {len(compound.synonyms) - 5} more)"
                    response_text += f"Synonyms: {synonyms_text}\n"
                
                if compound.properties:
                    response_text += "Properties:\n"
                    for key, value in compound.properties.items():
                        if value is not None:
                            key_formatted = key.replace('_', ' ').title()
                            response_text += f"  {key_formatted}: {value}\n"
                
                response_text += "\n"
            
            return response_text
        
        else:
            # No results or error
            error_text = f"❌ Chemical Search Failed\n"
            error_text += f"Query: {response.query}\n"
            error_text += f"Search Type: {response.search_type}\n"
            
            if response.error:
                error_text += f"Error: {response.error}\n"
            else:
                error_text += "No compounds found matching the query.\n"
            
            return error_text
            
    except Exception as e:
        error_msg = f"❌ Search Error: {str(e)}"
        if ctx:
            await ctx.error(error_msg)
        logger.error(f"Tool execution failed: {str(e)}")
        return error_msg



# Custom HTTP endpoints

@mcp.custom_route("/api/search/chemical", methods=["POST"])
async def search_chemical_api(request: Request) -> JSONResponse:
    """Direct API endpoint for chemical search using tagged tools"""
    try:
        # Parse request body
        body = await request.json()
        query = body.get("query", "")
        search_type = body.get("search_type", "formula")
        use_fallback = body.get("use_fallback", False)
        
        if not query:
            return JSONResponse(
                {"error": "Query parameter is required"}, 
                status_code=400
            )
        
        if search_type not in ["name", "formula", "smiles"]:
            return JSONResponse(
                {"error": "search_type must be one of: name, formula, smiles"}, 
                status_code=400
            )
        
        # Call the search_chemical function directly
        result = await search_chemical(query, search_type, use_fallback, None)
        
        return JSONResponse({
            "success": True,
            "query": query,
            "search_type": search_type,
            "result": result,
            "endpoint": "custom_api",
            "tags_used": ["search", "chemistry"]
        })
        
    except Exception as e:
        logger.error(f"Error in search_chemical_api: {e}")
        return JSONResponse(
            {"error": f"Search failed: {str(e)}"}, 
            status_code=500
        )



# Removed custom tag-based API endpoints - tool discovery and filtering
# is now handled in the pipeline layer



@mcp.custom_route("/api/health", methods=["GET"])
async def api_health_check(request: Request) -> JSONResponse:
    """API health check endpoint"""
    return JSONResponse({
        "status": "healthy",
        "service": "PubChemPy FastMCP Server",
        "version": "2.0.0",
        "endpoints": {
            "mcp": "/mcp",
            "search_chemical": "/api/search/chemical",
            "health": "/api/health"
        }
    })

async def cleanup():
    """Cleanup resources on shutdown"""
    try:
        await cleanup_http_client()
        logger.info("Cleanup completed successfully")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")

if __name__ == "__main__":
    try:
        # Register cleanup function
        import atexit
        import signal
        
        def sync_cleanup():
            asyncio.run(cleanup())
            
        atexit.register(sync_cleanup)
        
        # Handle signals
        def signal_handler(signum, frame):
            logger.info("Received shutdown signal")
            asyncio.run(cleanup())
            exit(0)
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Run the server with HTTP transport only
        port = int(os.getenv("PORT", "8989"))
        logger.info(f"Starting PubChemPy FastMCP Server on HTTP transport at port {port}...")
        mcp.run(transport="http", host="0.0.0.0", port=port)
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        exit(1) 