#!/usr/bin/env python3
"""
PubChemPy MCP Server

A Model Context Protocol server that provides chemical compound search capabilities
using PubChem database via pubchempy library.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Sequence
import sys

import pubchempy as pcp
import httpx
from pydantic import BaseModel

# MCP imports
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)

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

# Create MCP server instance
server = Server("pubchempy-mcp-server")

class PubChemSearcher:
    """Chemical compound search functionality"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self._is_closed = False
        
    async def cleanup(self):
        """Cleanup resources"""
        if not self._is_closed:
            try:
                await self.client.aclose()
                self._is_closed = True
                logger.info("HTTP client closed successfully")
            except Exception as e:
                logger.error(f"Error closing HTTP client: {e}")
                self._is_closed = True  # Mark as closed even if error occurred
    
    async def search_compound_pubchempy(
        self, 
        query: str, 
        search_type: str = "formula"
    ) -> List[ChemicalInfo]:
        """Search using pubchempy library"""
        try:
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
                    lambda c=compound: self._get_compound_properties(c)
                )
                results.append(props)
                
            return results
            
        except Exception as e:
            logger.error(f"PubChemPy search failed: {str(e)}")
            raise
    
    def _get_compound_properties(self, compound) -> ChemicalInfo:
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
    
    async def search_compound_direct_api(
        self, 
        query: str, 
        search_type: str = "formula"
    ) -> List[ChemicalInfo]:
        """Search using direct PubChem REST API"""
        if self._is_closed:
            raise RuntimeError("HTTP client has been closed")
        
        try:
            input_map = {
                "name": "name",
                "formula": "formula",
                "smiles": "smiles"
            }
            
            input_type = input_map.get(search_type, "formula")
            
            # Get CIDs first
            search_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/{input_type}/{query}/cids/JSON"
            
            response = await self.client.get(search_url)
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
            
            props_response = await self.client.get(props_url)
            props_response.raise_for_status()
            
            props_data = props_response.json()
            properties = props_data.get("PropertyTable", {}).get("Properties", [])
            
            results = []
            for prop in properties:
                cid = prop.get("CID")
                synonyms = await self._get_synonyms_direct(cid)
                
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
            
        except Exception as e:
            logger.error(f"Direct API search failed: {str(e)}")
            raise
    
    async def _get_synonyms_direct(self, cid: int) -> List[str]:
        """Get synonyms using direct API"""
        if self._is_closed:
            return []
        
        try:
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
            response = await self.client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                synonyms = data.get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
                return synonyms[:10]  # Limit to first 10
            return []
        except:
            return []
    
    async def search_chemical(
        self,
        query: str,
        search_type: str = "formula",
        use_fallback: bool = False
    ) -> ChemicalSearchResponse:
        """Main search method with fallback support"""
        try:
            results = []
            source = "pubchempy"
            error = None
            
            if not use_fallback:
                try:
                    results = await self.search_compound_pubchempy(query, search_type)
                except Exception as e:
                    logger.warning(f"PubChemPy failed: {str(e)}")
                    error = f"PubChemPy search failed: {str(e)}"
                    
                    # Auto-fallback to direct API
                    try:
                        results = await self.search_compound_direct_api(query, search_type)
                        source = "direct_api"
                        error = None
                    except Exception as e2:
                        error = f"Both PubChemPy and direct API failed. PubChemPy: {str(e)}, Direct API: {str(e2)}"
            else:
                # Use direct API
                try:
                    results = await self.search_compound_direct_api(query, search_type)
                    source = "direct_api"
                except Exception as e:
                    error = f"Direct API search failed: {str(e)}"
            
            return ChemicalSearchResponse(
                success=len(results) > 0 and error is None,
                query=query,
                search_type=search_type,
                results=results,
                error=error,
                source=source
            )
            
        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
            return ChemicalSearchResponse(
                success=False,
                query=query,
                search_type=search_type,
                error=str(e),
                source="unknown"
            )

# Global searcher instance
searcher = PubChemSearcher()

@server.list_tools()
async def handle_list_tools() -> ListToolsResult:
    """List available tools"""
    return ListToolsResult(
        tools=[
            Tool(
                name="search_chemical",
                description="Search for chemical compounds by name, molecular formula, or SMILES string",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Chemical name, molecular formula, or SMILES string to search for"
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["name", "formula", "smiles"],
                            "default": "formula",
                            "description": "Type of search - 'name' for chemical names, 'formula' for molecular formulas, 'smiles' for SMILES strings"
                        },
                        "use_fallback": {
                            "type": "boolean",
                            "default": False,
                            "description": "Use direct PubChem API instead of pubchempy library (fallback option)"
                        }
                    },
                    "required": ["query"]
                }
            )
        ]
    )

@server.call_tool()
async def handle_call_tool(request: CallToolRequest) -> CallToolResult:
    """Handle tool calls"""
    
    if request.name != "search_chemical":
        raise ValueError(f"Unknown tool: {request.name}")
    
    # Extract arguments
    args = request.arguments or {}
    query = args.get("query", "")
    search_type = args.get("search_type", "formula")
    use_fallback = args.get("use_fallback", False)
    
    if not query:
        raise ValueError("Query parameter is required")
    
    if search_type not in ["name", "formula", "smiles"]:
        raise ValueError("search_type must be one of: name, formula, smiles")
    
    try:
        # Perform the search
        result = await searcher.search_chemical(query, search_type, use_fallback)
        
        # Format the response for MCP
        if result.success and result.results:
            # Create formatted text response
            response_text = f"🧪 Chemical Search Results\n"
            response_text += f"Query: {result.query}\n"
            response_text += f"Search Type: {result.search_type}\n"
            response_text += f"Source: {result.source}\n"
            response_text += f"Found {len(result.results)} compound(s)\n\n"
            
            for i, compound in enumerate(result.results, 1):
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
            
            # Also include JSON data for programmatic use
            json_data = result.model_dump()
            
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=response_text
                    ),
                    TextContent(
                        type="text", 
                        text=f"Raw JSON Data:\n```json\n{json.dumps(json_data, indent=2)}\n```"
                    )
                ]
            )
        
        else:
            # No results or error
            error_text = f"❌ Chemical Search Failed\n"
            error_text += f"Query: {result.query}\n"
            error_text += f"Search Type: {result.search_type}\n"
            
            if result.error:
                error_text += f"Error: {result.error}\n"
            else:
                error_text += "No compounds found matching the query.\n"
            
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=error_text
                    )
                ]
            )
            
    except Exception as e:
        logger.error(f"Tool execution failed: {str(e)}")
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"❌ Error: {str(e)}"
                )
            ]
        )

async def main():
    """Main function to run the MCP server"""
    searcher_instance = None
    try:
        logger.info("Starting PubChemPy MCP Server...")
        
        # Create searcher instance after logging start
        searcher_instance = searcher
        
        # Run the server with stdio transport
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="pubchempy-mcp-server",
                    server_version="1.0.0",
                    capabilities=server.get_capabilities(
                        notification_options=None,
                        experimental_capabilities=None,
                    ),
                ),
            )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)
    finally:
        # Safely cleanup resources
        if searcher_instance:
            try:
                await searcher_instance.cleanup()
                logger.info("Cleanup completed successfully")
            except Exception as cleanup_error:
                logger.error(f"Cleanup failed: {cleanup_error}")
                # Don't re-raise cleanup errors to avoid masking original error

if __name__ == "__main__":
    asyncio.run(main()) 