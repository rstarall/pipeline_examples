#!/usr/bin/env python3
"""
PubChemPy FastMCP Server with Molecular Image Generation

A FastMCP server providing chemical compound search capabilities
using PubChem database via pubchempy library, with molecular image generation.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import os
import base64
import io
import tempfile

import pubchempy as pcp
import httpx
from pydantic import BaseModel
from fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse

# RDKit and image processing imports
try:
    from rdkit import Chem
    from rdkit.Chem import Draw
    from PIL import Image
    import matplotlib.pyplot as plt
    RDKIT_AVAILABLE = True
except ImportError as e:
    logging.warning(f"RDKit or image processing libraries not available: {e}")
    RDKIT_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global configuration
IMAGE_SERVER_HOST = "43.154.132.202:8083"
IMAGE_UPLOAD_URL = f"http://{IMAGE_SERVER_HOST}/upload/base64"

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
    image_url: Optional[str] = None
    image_hash: Optional[str] = None
    image_base64: Optional[str] = None

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

async def generate_molecule_image(smiles: str) -> Optional[str]:
    """Generate molecular structure image from SMILES string and return base64 encoded image"""
    if not RDKIT_AVAILABLE or not smiles:
        return None
    
    try:
        # Parse SMILES
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            logger.warning(f"Invalid SMILES string: {smiles}")
            return None
        
        # Generate 2D coordinates
        from rdkit.Chem import rdDepictor
        rdDepictor.Compute2DCoords(mol)
        
        # Draw molecule
        img = Draw.MolToImage(mol, size=(300, 300))
        
        # Convert PIL Image to base64
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        # Encode to base64
        img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
        return img_base64
        
    except Exception as e:
        logger.error(f"Error generating molecule image: {str(e)}")
        return None

async def upload_image_to_server(image_base64: str, filename: str = "molecule.png") -> Optional[Dict[str, Any]]:
    """Upload base64 encoded image to remote image server"""
    if not image_base64:
        return None
    
    try:
        client = await get_http_client()
        
        payload = {
            "image_data": image_base64,
            "filename": filename
        }
        
        response = await client.post(IMAGE_UPLOAD_URL, json=payload, timeout=30.0)
        
        if response.status_code == 200:
            result = response.json()
            # Replace localhost with actual server address if needed
            if "localhost:8083" in result.get("image_url", ""):
                result["image_url"] = result["image_url"].replace("localhost:8083", IMAGE_SERVER_HOST)
            
            return result
        else:
            logger.error(f"Image upload failed with status {response.status_code}: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error uploading image: {str(e)}")
        return None

async def extract_compound_properties(compound) -> ChemicalInfo:
    """Extract properties from pubchempy Compound object and generate molecular image"""
    try:
        synonyms = []
        if hasattr(compound, 'synonyms') and compound.synonyms:
            synonyms = compound.synonyms[:10]
        
        smiles = getattr(compound, 'canonical_smiles', None) or getattr(compound, 'smiles', None)
        
        # Generate molecular image
        image_base64 = None
        image_url = None
        image_hash = None
        cid = getattr(compound, 'cid', None)
        
        if smiles and RDKIT_AVAILABLE:
            # Use SMILES to generate image via RDKit
            try:
                image_base64 = await generate_molecule_image(smiles)
                if image_base64:
                    # Upload image to remote server
                    filename = f"molecule_{cid}.png"
                    upload_result = await upload_image_to_server(image_base64, filename)
                    
                    if upload_result:
                        image_url = upload_result.get('image_url')
                        image_hash = upload_result.get('hash')
                        logger.info(f"Successfully uploaded molecular image for CID {cid}")
                    else:
                        logger.warning(f"Failed to upload molecular image for CID {cid}")
            except Exception as img_error:
                logger.error(f"Error processing molecular image: {str(img_error)}")
        elif cid:
            # If no SMILES but have CID, use PubChem image service
            try:
                image_url = f"https://pubchem.ncbi.nlm.nih.gov/image/imgsrv.fcgi?cid={cid}&t=l"
                logger.info(f"Using PubChem image service for CID {cid}")
            except Exception as img_error:
                logger.error(f"Error generating PubChem image URL for CID {cid}: {str(img_error)}")
        
        return ChemicalInfo(
            cid=getattr(compound, 'cid', None),
            iupac_name=getattr(compound, 'iupac_name', None),
            molecular_formula=getattr(compound, 'molecular_formula', None),
            molecular_weight=getattr(compound, 'molecular_weight', None),
            smiles=smiles,
            inchi=getattr(compound, 'inchi', None),
            inchi_key=getattr(compound, 'inchikey', None),
            synonyms=synonyms,
            image_url=image_url,
            image_hash=image_hash,
            image_base64=image_base64,
            properties={
                'heavy_atom_count': getattr(compound, 'heavy_atom_count', None),
                'atom_stereo_count': getattr(compound, 'atom_stereo_count', None),
                'bond_stereo_count': getattr(compound, 'bond_stereo_count', None),
                'rotatable_bond_count': getattr(compound, 'rotatable_bond_count', None),
                'h_bond_acceptor_count': getattr(compound, 'h_bond_acceptor_count', None),
                'h_bond_donor_count': getattr(compound, 'h_bond_donor_count', None),
                'topological_polar_surface_area': getattr(compound, 'tpsa', None),
                'xlogp': getattr(compound, 'xlogp', None),
                'complexity': getattr(compound, 'complexity', None),
                'charge': getattr(compound, 'charge', None),
                'covalent_unit_count': getattr(compound, 'covalent_unit_count', None),
                'isotope_atom_count': getattr(compound, 'isotope_atom_count', None),
                'defined_atom_stereo_count': getattr(compound, 'defined_atom_stereo_count', None),
                'undefined_atom_stereo_count': getattr(compound, 'undefined_atom_stereo_count', None),
                'defined_bond_stereo_count': getattr(compound, 'defined_bond_stereo_count', None),
                'undefined_bond_stereo_count': getattr(compound, 'undefined_bond_stereo_count', None)
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
        props = await extract_compound_properties(compound)
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
        smiles = prop.get("CanonicalSMILES")
        
        # Generate molecular image
        image_base64 = None
        image_url = None
        image_hash = None
        
        if smiles and RDKIT_AVAILABLE:
            # Use SMILES to generate image via RDKit
            try:
                image_base64 = await generate_molecule_image(smiles)
                if image_base64:
                    # Upload image to remote server
                    filename = f"molecule_{cid}.png"
                    upload_result = await upload_image_to_server(image_base64, filename)
                    
                    if upload_result:
                        image_url = upload_result.get('image_url')
                        image_hash = upload_result.get('hash')
                        logger.info(f"Successfully uploaded molecular image for CID {cid}")
                    else:
                        logger.warning(f"Failed to upload molecular image for CID {cid}")
            except Exception as img_error:
                logger.error(f"Error processing molecular image for CID {cid}: {str(img_error)}")
        elif cid:
            # If no SMILES but have CID, use PubChem image service
            try:
                image_url = f"https://pubchem.ncbi.nlm.nih.gov/image/imgsrv.fcgi?cid={cid}&t=l"
                logger.info(f"Using PubChem image service for CID {cid}")
            except Exception as img_error:
                logger.error(f"Error generating PubChem image URL for CID {cid}: {str(img_error)}")
        
        results.append(ChemicalInfo(
            cid=cid,
            iupac_name=prop.get("IUPACName"),
            molecular_formula=prop.get("MolecularFormula"),
            molecular_weight=prop.get("MolecularWeight"),
            smiles=smiles,
            inchi=prop.get("InChI"),
            inchi_key=prop.get("InChIKey"),
            synonyms=synonyms,
            image_url=image_url,
            image_hash=image_hash,
            image_base64=image_base64
        ))
    
    return results

@mcp.tool(tags={"search", "chemistry"})
async def search_chemical(
    query: str,
    search_type: str = "formula",
    use_fallback: bool = False,
    ctx: Context = None
) -> dict:
    """
    Search for chemical compounds by name, molecular formula, or SMILES string.
    
    Args:
        query: Chemical name, molecular formula, or SMILES string to search for
        search_type: Type of search - 'name', 'formula', or 'smiles'
        use_fallback: Use direct PubChem API instead of pubchempy library
    
    Returns:
        JSON response with chemical information
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
        
        # Convert ChemicalInfo objects to dictionaries for JSON serialization
        results_dict = []
        for compound in response.results:
            compound_dict = {
                "cid": compound.cid,
                "iupac_name": compound.iupac_name,
                "molecular_formula": compound.molecular_formula,
                "molecular_weight": compound.molecular_weight,
                "smiles": compound.smiles,
                "inchi": compound.inchi,
                "inchi_key": compound.inchi_key,
                "synonyms": compound.synonyms,
                "properties": compound.properties,
                "image_url": compound.image_url,
                "image_hash": compound.image_hash,
                "image_base64": compound.image_base64
            }
            results_dict.append(compound_dict)
        
        # Return JSON response
        return {
            "success": response.success,
            "query": response.query,
            "search_type": response.search_type,
            "results": results_dict,
            "source": response.source,
            "error": response.error,
            "total_count": len(results_dict)
        }
            
    except Exception as e:
        error_msg = f"Search Error: {str(e)}"
        if ctx:
            await ctx.error(error_msg)
        logger.error(f"Tool execution failed: {str(e)}")
        return {
            "success": False,
            "query": query,
            "search_type": search_type,
            "results": [],
            "source": "unknown",
            "error": error_msg,
            "total_count": 0
        }



# Custom HTTP endpoints
@mcp.custom_route("/search", methods=["POST"])
async def search_chemical_api(request: Request) -> JSONResponse:
    """Direct API endpoint for chemical search - compatible with legacy pipeline"""
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
        
        # Get structured data instead of formatted text
        results = []
        source = "pubchempy"
        error = None
        
        if not use_fallback:
            try:
                results = await search_pubchempy(query, search_type)
            except Exception as e:
                error = f"PubChemPy search failed: {str(e)}"
                # Auto-fallback to direct API
                try:
                    results = await search_direct_api(query, search_type)
                    source = "direct_api"
                    error = None
                except Exception as e2:
                    error = f"Both PubChemPy and direct API failed. PubChemPy: {str(e)}, Direct API: {str(e2)}"
        else:
            # Use direct API
            try:
                results = await search_direct_api(query, search_type)
                source = "direct_api"
            except Exception as e:
                error = f"Direct API search failed: {str(e)}"
        
        # Convert ChemicalInfo objects to dictionaries for JSON serialization
        results_dict = []
        for compound in results:
            compound_dict = {
                "cid": compound.cid,
                "iupac_name": compound.iupac_name,
                "molecular_formula": compound.molecular_formula,
                "molecular_weight": compound.molecular_weight,
                "smiles": compound.smiles,
                "inchi": compound.inchi,
                "inchi_key": compound.inchi_key,
                "synonyms": compound.synonyms,
                "properties": compound.properties,
                "image_url": compound.image_url,
                "image_hash": compound.image_hash,
                "image_base64": compound.image_base64
            }
            results_dict.append(compound_dict)
        
        # Return format compatible with legacy pipeline
        return JSONResponse({
            "success": len(results_dict) > 0 and error is None,
            "query": query,
            "search_type": search_type,
            "results": results_dict,  # 关键：使用results而不是result
            "source": source,
            "error": error,
            "total_count": len(results_dict)
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
        port = int(os.getenv("PORT", "8988"))
        logger.info(f"Starting PubChemPy FastMCP Server with Molecular Image Generation on HTTP transport at port {port}...")
        mcp.run(transport="http", host="0.0.0.0", port=port)
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        exit(1) 