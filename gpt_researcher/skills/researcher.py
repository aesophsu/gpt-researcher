"""Research conductor skill for GPT Researcher.

This module provides the ResearchConductor class that manages and
coordinates the research process including query planning, web searching,
and context gathering.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from ..actions.agent_creator import choose_agent
from ..actions.query_processing import get_search_results, plan_research_outline
from ..actions.utils import stream_output
from ..document import DocumentLoader, LangChainDocumentLoader, OnlineDocumentLoader
from ..utils.enum import ReportSource, ReportType
from ..utils.logging_config import get_json_handler


EvidenceType = Literal[
    "guideline",
    "systematic_review",
    "meta_analysis",
    "rct",
    "cohort",
    "case_control",
    "case_report",
    "review",
    "unknown",
]


@dataclass
class NormalizedResult:
    url: str
    title: str
    snippet: str
    source: Literal["pubmed", "semantic", "tavily", "other"]
    source_rank_weight: float
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    evidence_type: EvidenceType = "unknown"
    open_access: bool | None = None
    domain: str = ""
    raw_score: float = 0.0
    final_score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    explain: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class ResearchConductor:
    """Manages and coordinates the research process.

    This class handles the main research workflow including planning
    research queries, conducting web searches, managing MCP retrievers,
    and gathering context from various sources.

    Attributes:
        researcher: The parent GPTResearcher instance.
        logger: Logger for research events.
        json_handler: Handler for JSON logging.
    """

    def __init__(self, researcher):
        """Initialize the ResearchConductor.

        Args:
            researcher: The GPTResearcher instance that owns this conductor.
        """
        self.researcher = researcher
        self.logger = logging.getLogger('research')
        self.json_handler = get_json_handler()
        # Add cache for MCP results to avoid redundant calls
        self._mcp_results_cache = None
        # Track MCP query count for balanced mode
        self._mcp_query_count = 0

    async def plan_research(self, query, query_domains=None):
        """Gets the sub-queries from the query
        Args:
            query: original query
        Returns:
            List of queries
        """
        await stream_output(
            "logs",
            "planning_research",
            f"🌐 Browsing the web to learn more about the task: {query}...",
            self.researcher.websocket,
        )

        search_results = await get_search_results(query, self.researcher.retrievers[0], query_domains, researcher=self.researcher)
        self.logger.info(f"Initial search results obtained: {len(search_results)} results")

        await stream_output(
            "logs",
            "planning_research",
            f"🤔 Planning the research strategy and subtasks...",
            self.researcher.websocket,
        )

        retriever_names = [r.__name__ for r in self.researcher.retrievers]
        # Remove duplicate logging - this will be logged once in conduct_research instead

        outline = await plan_research_outline(
            query=query,
            search_results=search_results,
            agent_role_prompt=self.researcher.role,
            cfg=self.researcher.cfg,
            parent_query=self.researcher.parent_query,
            report_type=self.researcher.report_type,
            cost_callback=self.researcher.add_costs,
            retriever_names=retriever_names,  # Pass retriever names for MCP optimization
            **self.researcher.kwargs
        )
        self.logger.info(f"Research outline planned: {outline}")
        return outline

    async def conduct_research(self):
        """Runs the GPT Researcher to conduct research"""
        if self.json_handler:
            self.json_handler.update_content("query", self.researcher.query)
        
        self.logger.info(f"Starting research for query: {self.researcher.query}")
        
        # Log active retrievers once at the start of research
        retriever_names = [r.__name__ for r in self.researcher.retrievers]
        self.logger.info(f"Active retrievers: {retriever_names}")
        
        # Reset visited_urls and source_urls at the start of each research task
        self.researcher.visited_urls.clear()
        research_data = []

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "starting_research",
                f"🔍 Starting the research task for '{self.researcher.query}'...",
                self.researcher.websocket,
            )
            await stream_output(
                "logs",
                "agent_generated",
                self.researcher.agent,
                self.researcher.websocket
            )

        # Choose agent and role if not already defined
        if not (self.researcher.agent and self.researcher.role):
            self.researcher.agent, self.researcher.role = await choose_agent(
                query=self.researcher.query,
                cfg=self.researcher.cfg,
                parent_query=self.researcher.parent_query,
                cost_callback=self.researcher.add_costs,
                headers=self.researcher.headers,
                prompt_family=self.researcher.prompt_family
            )
                
        # Check if MCP retrievers are configured
        has_mcp_retriever = any("mcpretriever" in r.__name__.lower() for r in self.researcher.retrievers)
        if has_mcp_retriever:
            self.logger.info("MCP retrievers configured and will be used with standard research flow")

        # Conduct research based on the source type
        if self.researcher.source_urls:
            self.logger.info("Using provided source URLs")
            research_data = await self._get_context_by_urls(self.researcher.source_urls)
            if research_data and len(research_data) == 0 and self.researcher.verbose:
                await stream_output(
                    "logs",
                    "answering_from_memory",
                    f"🧐 I was unable to find relevant context in the provided sources...",
                    self.researcher.websocket,
                )
            if self.researcher.complement_source_urls:
                self.logger.info("Complementing with web search")
                additional_research = await self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains)
                research_data += ' '.join(additional_research)
        elif self.researcher.report_source == ReportSource.Web.value:
            self.logger.info("Using web search with all configured retrievers")
            research_data = await self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains)
        elif self.researcher.report_source == ReportSource.Local.value:
            self.logger.info("Using local search")
            document_data = await DocumentLoader(self.researcher.cfg.doc_path).load()
            self.logger.info(f"Loaded {len(document_data)} documents")
            if self.researcher.vector_store:
                self.researcher.vector_store.load(document_data)

            research_data = await self._get_context_by_web_search(self.researcher.query, document_data, self.researcher.query_domains)
        # Hybrid search including both local documents and web sources
        elif self.researcher.report_source == ReportSource.Hybrid.value:
            if self.researcher.document_urls:
                document_data = await OnlineDocumentLoader(self.researcher.document_urls).load()
            else:
                document_data = await DocumentLoader(self.researcher.cfg.doc_path).load()
            if self.researcher.vector_store:
                self.researcher.vector_store.load(document_data)
            docs_context = await self._get_context_by_web_search(self.researcher.query, document_data, self.researcher.query_domains)
            web_context = await self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains)
            research_data = self.researcher.prompt_family.join_local_web_documents(docs_context, web_context)
        elif self.researcher.report_source == ReportSource.Azure.value:
            from ..document.azure_document_loader import AzureDocumentLoader
            azure_loader = AzureDocumentLoader(
                container_name=os.getenv("AZURE_CONTAINER_NAME"),
                connection_string=os.getenv("AZURE_CONNECTION_STRING")
            )
            azure_files = await azure_loader.load()
            document_data = await DocumentLoader(azure_files).load()  # Reuse existing loader
            research_data = await self._get_context_by_web_search(self.researcher.query, document_data)
            
        elif self.researcher.report_source == ReportSource.LangChainDocuments.value:
            langchain_documents_data = await LangChainDocumentLoader(
                self.researcher.documents
            ).load()
            if self.researcher.vector_store:
                self.researcher.vector_store.load(langchain_documents_data)
            research_data = await self._get_context_by_web_search(
                self.researcher.query, langchain_documents_data, self.researcher.query_domains
            )
        elif self.researcher.report_source == ReportSource.LangChainVectorStore.value:
            research_data = await self._get_context_by_vectorstore(self.researcher.query, self.researcher.vector_store_filter)

        # Rank and curate the sources
        self.researcher.context = research_data
        if self.researcher.cfg.curate_sources:
            self.logger.info("Curating sources")
            self.researcher.context = await self.researcher.source_curator.curate_sources(research_data)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "research_step_finalized",
                f"Finalized research step.\n💸 Total Research Costs: ${self.researcher.get_costs()}",
                self.researcher.websocket,
            )
            if self.json_handler:
                self.json_handler.update_content("costs", self.researcher.get_costs())
                self.json_handler.update_content("context", self.researcher.context)

        self.logger.info(f"Research completed. Context size: {len(str(self.researcher.context))}")
        return self.researcher.context

    async def _get_context_by_urls(self, urls):
        """Scrapes and compresses the context from the given urls"""
        self.logger.info(f"Getting context from URLs: {urls}")
        
        new_search_urls = await self._get_new_urls(urls)
        self.logger.info(f"New URLs to process: {new_search_urls}")

        scraped_content = await self.researcher.scraper_manager.browse_urls(new_search_urls)
        self.logger.info(f"Scraped content from {len(scraped_content)} URLs")

        if self.researcher.vector_store:
            self.researcher.vector_store.load(scraped_content)

        context = await self.researcher.context_manager.get_similar_content_by_query(
            self.researcher.query, scraped_content
        )
        return context

    # Add logging to other methods similarly...

    async def _get_context_by_vectorstore(self, query, filter: dict | None = None):
        """
        Generates the context for the research task by searching the vectorstore
        Returns:
            context: List of context
        """
        self.logger.info(f"Starting vectorstore search for query: {query}")
        context = []
        # Generate Sub-Queries including original query
        sub_queries = await self.plan_research(query)
        # If this is not part of a sub researcher, add original query to research for better results
        if self.researcher.report_type != "subtopic_report":
            sub_queries.append(query)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "subqueries",
                f"🗂️  I will conduct my research based on the following queries: {sub_queries}...",
                self.researcher.websocket,
                True,
                sub_queries,
            )

        # Using asyncio.gather to process the sub_queries asynchronously
        context = await asyncio.gather(
            *[
                self._process_sub_query_with_vectorstore(sub_query, filter)
                for sub_query in sub_queries
            ]
        )
        return context

    async def _get_context_by_web_search(self, query, scraped_data: list | None = None, query_domains: list | None = None):
        """
        Generates the context for the research task by searching the query and scraping the results
        Returns:
            context: List of context
        """
        self.logger.info(f"Starting web search for query: {query}")
        
        if scraped_data is None:
            scraped_data = []
        if query_domains is None:
            query_domains = []

        # **CONFIGURABLE MCP OPTIMIZATION: Control MCP strategy**
        mcp_retrievers = [r for r in self.researcher.retrievers if "mcpretriever" in r.__name__.lower()]
        
        # Get MCP strategy configuration
        mcp_strategy = self._get_mcp_strategy()
        
        if mcp_retrievers and self._mcp_results_cache is None:
            if mcp_strategy == "disabled":
                # MCP disabled - skip MCP research entirely
                self.logger.info("MCP disabled by strategy, skipping MCP research")
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "mcp_disabled",
                        f"⚡ MCP research disabled by configuration",
                        self.researcher.websocket,
                    )
            elif mcp_strategy == "fast":
                # Fast: Run MCP once with original query
                self.logger.info("MCP fast strategy: Running once with original query")
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "mcp_optimization",
                        f"🚀 MCP Fast: Running once for main query (performance mode)",
                        self.researcher.websocket,
                    )
                
                # Execute MCP research once with the original query
                mcp_context = await self._execute_mcp_research_for_queries([query], mcp_retrievers)
                self._mcp_results_cache = mcp_context
                self.logger.info(f"MCP results cached: {len(mcp_context)} total context entries")
            elif mcp_strategy == "deep":
                # Deep: Will run MCP for all queries (original behavior) - defer to per-query execution
                self.logger.info("MCP deep strategy: Will run for all queries")
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "mcp_comprehensive",
                        f"🔍 MCP Deep: Will run for each sub-query (thorough mode)",
                        self.researcher.websocket,
                    )
                # Don't cache - let each sub-query run MCP individually
            else:
                # Unknown strategy - default to fast
                self.logger.warning(f"Unknown MCP strategy '{mcp_strategy}', defaulting to fast")
                mcp_context = await self._execute_mcp_research_for_queries([query], mcp_retrievers)
                self._mcp_results_cache = mcp_context
                self.logger.info(f"MCP results cached: {len(mcp_context)} total context entries")

        # Generate Sub-Queries including original query
        sub_queries = await self.plan_research(query, query_domains)
        self.logger.info(f"Generated sub-queries: {sub_queries}")
        
        # If this is not part of a sub researcher, add original query to research for better results
        if self.researcher.report_type != "subtopic_report":
            sub_queries.append(query)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "subqueries",
                f"🗂️ I will conduct my research based on the following queries: {sub_queries}...",
                self.researcher.websocket,
                True,
                sub_queries,
            )

        # Using asyncio.gather to process the sub_queries asynchronously
        try:
            context = await asyncio.gather(
                *[
                    self._process_sub_query(sub_query, scraped_data, query_domains)
                    for sub_query in sub_queries
                ]
            )
            self.logger.info(f"Gathered context from {len(context)} sub-queries")
            # Filter out empty results and join the context
            context = [c for c in context if c]
            if context:
                combined_context = " ".join(context)
                self.logger.info(f"Combined context size: {len(combined_context)}")
                return combined_context
            return []
        except Exception as e:
            self.logger.error(f"Error during web search: {e}", exc_info=True)
            return []

    def _get_mcp_strategy(self) -> str:
        """
        Get the MCP strategy configuration.
        
        Priority:
        1. Instance-level setting (self.researcher.mcp_strategy)
        2. Config file setting (self.researcher.cfg.mcp_strategy) 
        3. Default value ("fast")
        
        Returns:
            str: MCP strategy
                "disabled" = Skip MCP entirely
                "fast" = Run MCP once with original query (default)
                "deep" = Run MCP for all sub-queries
        """
        # Check instance-level setting first
        if hasattr(self.researcher, 'mcp_strategy') and self.researcher.mcp_strategy is not None:
            return self.researcher.mcp_strategy
        
        # Check config setting
        if hasattr(self.researcher.cfg, 'mcp_strategy'):
            return self.researcher.cfg.mcp_strategy
        
        # Default to fast mode
        return "fast"

    async def _execute_mcp_research_for_queries(self, queries: list, mcp_retrievers: list) -> list:
        """
        Execute MCP research for a list of queries.
        
        Args:
            queries: List of queries to research
            mcp_retrievers: List of MCP retriever classes
            
        Returns:
            list: Combined MCP context entries from all queries
        """
        all_mcp_context = []
        
        for i, query in enumerate(queries, 1):
            self.logger.info(f"Executing MCP research for query {i}/{len(queries)}: {query}")
            
            for retriever in mcp_retrievers:
                try:
                    mcp_results = await self._execute_mcp_research(retriever, query)
                    if mcp_results:
                        for result in mcp_results:
                            content = result.get("body", "")
                            url = result.get("href", "")
                            title = result.get("title", "")
                            
                            if content:
                                context_entry = {
                                    "content": content,
                                    "url": url,
                                    "title": title,
                                    "query": query,
                                    "source_type": "mcp"
                                }
                                all_mcp_context.append(context_entry)
                        
                        self.logger.info(f"Added {len(mcp_results)} MCP results for query: {query}")
                        
                        if self.researcher.verbose:
                            await stream_output(
                                "logs",
                                "mcp_results_cached",
                                f"✅ Cached {len(mcp_results)} MCP results from query {i}/{len(queries)}",
                                self.researcher.websocket,
                            )
                except Exception as e:
                    self.logger.error(f"Error in MCP research for query '{query}': {e}")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_cache_error",
                            f"⚠️ MCP research error for query {i}, continuing with other sources",
                            self.researcher.websocket,
                        )
        
        return all_mcp_context

    async def _process_sub_query(self, sub_query: str, scraped_data: list = [], query_domains: list = []):
        """Takes in a sub query and scrapes urls based on it and gathers context."""
        if self.json_handler:
            self.json_handler.log_event("sub_query", {
                "query": sub_query,
                "scraped_data_size": len(scraped_data)
            })
        
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "running_subquery_research",
                f"\n🔍 Running research for '{sub_query}'...",
                self.researcher.websocket,
            )

        try:
            # Identify MCP retrievers
            mcp_retrievers = [r for r in self.researcher.retrievers if "mcpretriever" in r.__name__.lower()]
            non_mcp_retrievers = [r for r in self.researcher.retrievers if "mcpretriever" not in r.__name__.lower()]
            
            # Initialize context components
            mcp_context = []
            web_context = ""
            
            # Get MCP strategy configuration
            mcp_strategy = self._get_mcp_strategy()
            
            # **CONFIGURABLE MCP PROCESSING**
            if mcp_retrievers:
                if mcp_strategy == "disabled":
                    # MCP disabled - skip entirely
                    self.logger.info(f"MCP disabled for sub-query: {sub_query}")
                elif mcp_strategy == "fast" and self._mcp_results_cache is not None:
                    # Fast: Use cached results
                    mcp_context = self._mcp_results_cache.copy()
                    
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_cache_reuse",
                            f"♻️ Reusing cached MCP results ({len(mcp_context)} sources) for: {sub_query}",
                            self.researcher.websocket,
                        )
                    
                    self.logger.info(f"Reused {len(mcp_context)} cached MCP results for sub-query: {sub_query}")
                elif mcp_strategy == "deep":
                    # Deep: Run MCP for every sub-query
                    self.logger.info(f"Running deep MCP research for: {sub_query}")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_comprehensive_run",
                            f"🔍 Running deep MCP research for: {sub_query}",
                            self.researcher.websocket,
                        )
                    
                    mcp_context = await self._execute_mcp_research_for_queries([sub_query], mcp_retrievers)
                else:
                    # Fallback: if no cache and not deep mode, run MCP for this query
                    self.logger.warning("MCP cache not available, falling back to per-sub-query execution")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_fallback",
                            f"🔌 MCP cache unavailable, running MCP research for: {sub_query}",
                            self.researcher.websocket,
                        )
                    
                    mcp_context = await self._execute_mcp_research_for_queries([sub_query], mcp_retrievers)
            
            # Get web search context using non-MCP retrievers (if no scraped data provided)
            if not scraped_data:
                scraped_data = await self._scrape_data_by_urls(sub_query, query_domains)
                self.logger.info(f"Scraped data size: {len(scraped_data)}")

            # Get similar content based on scraped data
            if scraped_data:
                web_context = await self.researcher.context_manager.get_similar_content_by_query(sub_query, scraped_data)
                self.logger.info(f"Web content found for sub-query: {len(str(web_context)) if web_context else 0} chars")

            # Combine MCP context with web context intelligently
            combined_context = self._combine_mcp_and_web_context(mcp_context, web_context, sub_query)
            
            # Log context combination results
            if combined_context:
                context_length = len(str(combined_context))
                self.logger.info(f"Combined context for '{sub_query}': {context_length} chars")
                
                if self.researcher.verbose:
                    mcp_count = len(mcp_context)
                    web_available = bool(web_context)
                    cache_used = self._mcp_results_cache is not None and mcp_retrievers and mcp_strategy != "deep"
                    cache_status = " (cached)" if cache_used else ""
                    await stream_output(
                        "logs",
                        "context_combined",
                        f"📚 Combined research context: {mcp_count} MCP sources{cache_status}, {'web content' if web_available else 'no web content'}",
                        self.researcher.websocket,
                    )
            else:
                self.logger.warning(f"No combined context found for sub-query: {sub_query}")
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "subquery_context_not_found",
                        f"🤷 No content found for '{sub_query}'...",
                        self.researcher.websocket,
                    )
            
            if combined_context and self.json_handler:
                self.json_handler.log_event("content_found", {
                    "sub_query": sub_query,
                    "content_size": len(str(combined_context)),
                    "mcp_sources": len(mcp_context),
                    "web_content": bool(web_context)
                })
                
            return combined_context
            
        except Exception as e:
            self.logger.error(f"Error processing sub-query {sub_query}: {e}", exc_info=True)
            if self.researcher.verbose:
                await stream_output(
                    "logs",
                    "subquery_error",
                    f"❌ Error processing '{sub_query}': {str(e)}",
                    self.researcher.websocket,
                )
            return ""

    async def _execute_mcp_research(self, retriever, query):
        """
        Execute MCP research using the new two-stage approach.
        
        Args:
            retriever: The MCP retriever class
            query: The search query
            
        Returns:
            list: MCP research results
        """
        retriever_name = retriever.__name__
        
        self.logger.info(f"Executing MCP research with {retriever_name} for query: {query}")
        
        try:
            # Instantiate the MCP retriever with proper parameters
            # Pass the researcher instance (self.researcher) which contains both cfg and mcp_configs
            retriever_instance = retriever(
                query=query, 
                headers=self.researcher.headers,
                query_domains=self.researcher.query_domains,
                websocket=self.researcher.websocket,
                researcher=self.researcher  # Pass the entire researcher instance
            )
            
            if self.researcher.verbose:
                await stream_output(
                    "logs",
                    "mcp_retrieval_stage1",
                    f"🧠 Stage 1: Selecting optimal MCP tools for: {query}",
                    self.researcher.websocket,
                )
            
            # Execute the two-stage MCP search
            results = retriever_instance.search(
                max_results=self.researcher.cfg.max_search_results_per_query
            )
            
            if results:
                result_count = len(results)
                self.logger.info(f"MCP research completed: {result_count} results from {retriever_name}")
                
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "mcp_research_complete",
                        f"🎯 MCP research completed: {result_count} intelligent results obtained",
                        self.researcher.websocket,
                    )
                
                return results
            else:
                self.logger.info(f"No results returned from MCP research with {retriever_name}")
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "mcp_no_results",
                        f"ℹ️ No relevant information found via MCP for: {query}",
                        self.researcher.websocket,
                    )
                return []
                
        except Exception as e:
            self.logger.error(f"Error in MCP research with {retriever_name}: {str(e)}")
            if self.researcher.verbose:
                await stream_output(
                    "logs",
                    "mcp_research_error",
                    f"⚠️ MCP research error: {str(e)} - continuing with other sources",
                    self.researcher.websocket,
                )
            return []

    def _combine_mcp_and_web_context(self, mcp_context: list, web_context: str, sub_query: str) -> str:
        """
        Intelligently combine MCP and web research context.
        
        Args:
            mcp_context: List of MCP context entries
            web_context: Web research context string  
            sub_query: The sub-query being processed
            
        Returns:
            str: Combined context string
        """
        combined_parts = []
        
        # Add web context first if available
        if web_context and web_context.strip():
            combined_parts.append(web_context.strip())
            self.logger.debug(f"Added web context: {len(web_context)} chars")
        
        # Add MCP context with proper formatting
        if mcp_context:
            mcp_formatted = []
            
            for i, item in enumerate(mcp_context):
                content = item.get("content", "")
                url = item.get("url", "")
                title = item.get("title", f"MCP Result {i+1}")
                
                if content and content.strip():
                    # Create a well-formatted context entry
                    if url and url != f"mcp://llm_analysis":
                        citation = f"\n\n*Source: {title} ({url})*"
                    else:
                        citation = f"\n\n*Source: {title}*"
                    
                    formatted_content = f"{content.strip()}{citation}"
                    mcp_formatted.append(formatted_content)
            
            if mcp_formatted:
                # Join MCP results with clear separation
                mcp_section = "\n\n---\n\n".join(mcp_formatted)
                combined_parts.append(mcp_section)
                self.logger.debug(f"Added {len(mcp_context)} MCP context entries")
        
        # Combine all parts
        if combined_parts:
            final_context = "\n\n".join(combined_parts)
            self.logger.info(f"Combined context for '{sub_query}': {len(final_context)} total chars")
            return final_context
        else:
            self.logger.warning(f"No context to combine for sub-query: {sub_query}")
            return ""

    async def _process_sub_query_with_vectorstore(self, sub_query: str, filter: dict | None = None):
        """Takes in a sub query and gathers context from the user provided vector store

        Args:
            sub_query (str): The sub-query generated from the original query

        Returns:
            str: The context gathered from search
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "running_subquery_with_vectorstore_research",
                f"\n🔍 Running research for '{sub_query}'...",
                self.researcher.websocket,
            )

        context = await self.researcher.context_manager.get_similar_content_by_query_with_vectorstore(sub_query, filter)

        return context

    async def _get_new_urls(self, url_set_input):
        """Gets the new urls from the given url set.
        Args: url_set_input (set[str]): The url set to get the new urls from
        Returns: list[str]: The new urls from the given url set
        """

        new_urls = []
        for url in url_set_input:
            if url not in self.researcher.visited_urls:
                self.researcher.visited_urls.add(url)
                new_urls.append(url)
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "added_source_url",
                        f"✅ Added source url to research: {url}\n",
                        self.researcher.websocket,
                        True,
                        url,
                    )

        return new_urls

    async def _search_relevant_source_urls(self, query, query_domains: list | None = None):
        if query_domains is None:
            query_domains = []

        non_mcp_retrievers = [
            retriever_class
            for retriever_class in self.researcher.retrievers
            if "mcpretriever" not in retriever_class.__name__.lower()
        ]
        if not non_mcp_retrievers:
            return []

        priority_mode = getattr(self.researcher.cfg, "retriever_priority_mode", "parallel")
        if priority_mode != "staged":
            ranked_urls = await self._run_parallel_retrieval(query, query_domains, non_mcp_retrievers)
            return await self._get_new_urls(ranked_urls)

        ranked_urls = await self._run_staged_retrieval(query, query_domains, non_mcp_retrievers)
        return await self._get_new_urls(ranked_urls)

    async def _run_parallel_retrieval(self, query: str, query_domains: list[str], retrievers: list[type]) -> list[str]:
        max_results = max(1, int(self.researcher.cfg.max_search_results_per_query))
        aggregated: list[NormalizedResult] = []

        for retriever_class in retrievers:
            results = await self._search_with_retriever(
                retriever_class=retriever_class,
                query=query,
                query_domains=query_domains,
                max_results=max_results,
            )
            aggregated.extend(results)

        return self._rank_and_extract_urls(query, aggregated)

    async def _run_staged_retrieval(self, query: str, query_domains: list[str], retrievers: list[type]) -> list[str]:
        retriever_map = {self._retriever_key(r): r for r in retrievers}
        pubmed = retriever_map.get("pubmed")
        semantic = retriever_map.get("semantic")
        tavily = retriever_map.get("tavily")
        others = [r for key, r in retriever_map.items() if key not in {"pubmed", "semantic", "tavily"}]

        effective_query = self._augment_query_for_time_window(query)
        aggregated: list[NormalizedResult] = []

        # Stage A: academic-first retrieval
        if pubmed:
            aggregated.extend(
                await self._search_with_retriever(
                    retriever_class=pubmed,
                    query=effective_query,
                    query_domains=query_domains,
                    max_results=4,
                )
            )
        if semantic:
            aggregated.extend(
                await self._search_with_retriever(
                    retriever_class=semantic,
                    query=effective_query,
                    query_domains=query_domains,
                    max_results=3,
                )
            )

        for retriever_class in others:
            aggregated.extend(
                await self._search_with_retriever(
                    retriever_class=retriever_class,
                    query=effective_query,
                    query_domains=query_domains,
                    max_results=max(1, int(self.researcher.cfg.max_search_results_per_query)),
                )
            )

        unique_count = len(self._dedupe_results(aggregated))
        min_unique_sources = max(1, int(getattr(self.researcher.cfg, "min_unique_sources", 8)))
        deficit = max(0, min_unique_sources - unique_count)

        # Stage B: Tavily top-up only if needed
        if tavily and deficit > 0:
            for include_domains in self._build_tavily_domain_tiers(query_domains):
                tavily_results = await self._search_with_retriever(
                    retriever_class=tavily,
                    query=effective_query,
                    query_domains=include_domains,
                    max_results=self._tavily_dynamic_max_results(deficit),
                )
                aggregated.extend(tavily_results)
                unique_count = len(self._dedupe_results(aggregated))
                deficit = max(0, min_unique_sources - unique_count)
                if deficit <= 0:
                    break

        ranked_urls = self._rank_and_extract_urls(query, aggregated)
        self.logger.info(
            "Retriever staged mode complete: query='%s' unique_sources=%s target=%s tavily_needed=%s",
            query,
            len(ranked_urls),
            min_unique_sources,
            "yes" if unique_count < min_unique_sources else "no",
        )
        return ranked_urls

    async def _search_with_retriever(
        self,
        retriever_class,
        query: str,
        query_domains: list[str],
        max_results: int,
    ) -> list[NormalizedResult]:
        retriever_name = retriever_class.__name__
        try:
            retriever = retriever_class(query, query_domains=query_domains)
            search_results = await asyncio.to_thread(retriever.search, max_results=max_results)
            if not search_results:
                return []
            normalized = self._normalize_batch(search_results, self._retriever_key(retriever_class), query)
            self.logger.info(
                "Retriever %s returned %s results (max_results=%s, domains=%s)",
                retriever_name,
                len(normalized),
                max_results,
                query_domains if query_domains else "all",
            )
            return normalized
        except Exception as e:
            self.logger.error("Error searching with %s: %s", retriever_name, e)
            return []

    def _retriever_key(self, retriever_class) -> str:
        name = retriever_class.__name__.lower()
        if "pubmed" in name:
            return "pubmed"
        if "semantic" in name:
            return "semantic"
        if "tavily" in name:
            return "tavily"
        return name

    def _augment_query_for_time_window(self, query: str) -> str:
        years = max(0, int(getattr(self.researcher.cfg, "medical_time_window_years", 0)))
        if years <= 0:
            return query
        current_year = datetime.now().year
        earliest = current_year - years
        return f"{query} (prioritize evidence published since {earliest})"

    def _normalize_batch(self, items: list[dict], source: str, query: str) -> list[NormalizedResult]:
        normalized: list[NormalizedResult] = []
        for item in items:
            normalized_item = self._normalize_result(item, source, query)
            if normalized_item is not None:
                normalized.append(normalized_item)
        return normalized

    def _normalize_result(self, item: dict, retriever_key: str, query: str) -> NormalizedResult | None:
        url = (item.get("href") or item.get("url") or "").strip()
        if not url:
            return None

        source = retriever_key if retriever_key in {"pubmed", "semantic", "tavily"} else "other"
        title = (item.get("title") or "").strip()
        snippet = (item.get("body") or item.get("content") or item.get("raw_content") or "").strip()
        snippet = re.sub(r"\s+", " ", snippet)[:1200]

        text = f"{title} {snippet}".strip()
        domain = urlparse(url).netloc.lower().strip()
        year = self._infer_year(text, item)
        doi = self._extract_doi(text)
        journal = self._infer_journal(text, domain, item)
        evidence_type = self._infer_evidence_type(text, title)
        open_access = self._is_open_access(item, source, url)
        source_rank_weight = {"pubmed": 1.0, "semantic": 0.85, "tavily": 0.65, "other": 0.55}[source]

        return NormalizedResult(
            url=url,
            title=title,
            snippet=snippet,
            source=source,
            source_rank_weight=source_rank_weight,
            year=year,
            doi=doi,
            journal=journal,
            evidence_type=evidence_type,
            open_access=open_access,
            domain=domain,
            raw_score=source_rank_weight,
            raw=dict(item),
        )

    def _infer_year(self, text: str, item: dict) -> int | None:
        year_value = item.get("year")
        current_year = datetime.now().year
        if isinstance(year_value, int) and 1900 <= year_value <= current_year + 1:
            return year_value

        years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", text or "")]
        valid_years = [y for y in years if 1900 <= y <= current_year + 1]
        return max(valid_years) if valid_years else None

    def _extract_doi(self, text: str) -> str | None:
        if not text:
            return None
        match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", text)
        if not match:
            return None
        doi = match.group(0)
        return doi if len(doi) <= 128 else None

    def _infer_journal(self, text: str, domain: str, item: dict) -> str | None:
        for key in ("journal", "venue", "publication", "publicationTitle"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:160]

        known = {
            "nejm.org": "New England Journal of Medicine",
            "thelancet.com": "The Lancet",
            "jamanetwork.com": "JAMA Network",
            "bmj.com": "BMJ",
            "nature.com": "Nature",
            "sciencedirect.com": "ScienceDirect",
        }
        for d, journal in known.items():
            if domain.endswith(d):
                return journal

        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if lines and "journal" in lines[0].lower():
            return lines[0][:160]
        return None

    def _infer_evidence_type(self, text: str, title: str) -> EvidenceType:
        content = f"{title} {text}".lower()
        rules: list[tuple[EvidenceType, tuple[str, ...]]] = [
            ("guideline", ("guideline", "consensus statement", "practice recommendation")),
            ("meta_analysis", ("meta-analysis", "meta analysis")),
            ("systematic_review", ("systematic review",)),
            ("rct", ("randomized", "randomised", "controlled trial", "rct")),
            ("cohort", ("cohort",)),
            ("case_control", ("case-control", "case control")),
            ("case_report", ("case report",)),
            ("review", ("review",)),
        ]
        for evidence_type, keywords in rules:
            if any(keyword in content for keyword in keywords):
                return evidence_type
        return "unknown"

    def _is_open_access(self, item: dict, source: str, url: str) -> bool | None:
        if isinstance(item.get("isOpenAccess"), bool):
            return item["isOpenAccess"]
        if isinstance(item.get("open_access"), bool):
            return item["open_access"]
        if source == "pubmed" and "/pmc/articles/" in url:
            return True
        return None

    def _parse_domain_list(self, value: str | None) -> list[str]:
        if not value:
            return []
        return [domain.strip() for domain in value.split(",") if domain.strip()]

    def _build_tavily_domain_tiers(self, query_domains: list[str]) -> list[list[str]]:
        # Respect explicit user domain filters first.
        if query_domains:
            return [query_domains]

        tier0 = self._parse_domain_list(getattr(self.researcher.cfg, "domain_tier0", ""))
        tiers = [tier0] if tier0 else [[]]

        soft_fallback = bool(getattr(self.researcher.cfg, "tavily_soft_fallback", True))
        if not soft_fallback:
            return tiers

        tier1 = self._parse_domain_list(getattr(self.researcher.cfg, "domain_tier1", ""))
        tier2 = self._parse_domain_list(getattr(self.researcher.cfg, "domain_tier2", ""))
        if tier1:
            tiers.append(tier1)
        if tier2:
            tiers.append(tier2)
        return tiers

    def _tavily_dynamic_max_results(self, deficit: int) -> int:
        efficiency_mode = bool(getattr(self.researcher.cfg, "tavily_efficiency_mode", True))
        base_cap = max(1, int(self.researcher.cfg.max_search_results_per_query))
        if not efficiency_mode:
            return base_cap
        # Fetch only the missing window plus a small buffer for dedupe.
        return max(1, min(base_cap, deficit + 2))

    def _source_priority(self, source: str) -> int:
        return {"pubmed": 3, "semantic": 2, "tavily": 1, "other": 0}.get(source, 0)

    def _pick_better_duplicate(self, existing: NormalizedResult, candidate: NormalizedResult) -> NormalizedResult:
        existing_score = existing.final_score if existing.final_score else existing.raw_score
        candidate_score = candidate.final_score if candidate.final_score else candidate.raw_score
        if candidate_score > existing_score + 0.03:
            return candidate
        if abs(candidate_score - existing_score) < 0.03:
            if self._source_priority(candidate.source) > self._source_priority(existing.source):
                return candidate
        return existing

    def _dedupe_results(self, results: list[NormalizedResult]) -> list[NormalizedResult]:
        by_doi: dict[str, NormalizedResult] = {}
        by_url: dict[str, NormalizedResult] = {}

        for item in results:
            if not item.url:
                continue
            normalized_url = item.url.strip().lower().rstrip("/")
            if not normalized_url:
                continue

            if item.doi:
                doi_key = item.doi.lower().strip()
                existing = by_doi.get(doi_key)
                if existing is None:
                    by_doi[doi_key] = item
                else:
                    by_doi[doi_key] = self._pick_better_duplicate(existing, item)
                continue

            existing_url = by_url.get(normalized_url)
            if existing_url is None:
                by_url[normalized_url] = item
            else:
                by_url[normalized_url] = self._pick_better_duplicate(existing_url, item)

        final_items = list(by_doi.values()) + list(by_url.values())
        final_items = list({id(v): v for v in final_items}.values())
        # keep deterministic ordering by final_score/raw_score then url
        final_items.sort(key=lambda x: (x.final_score if x.final_score else x.raw_score, x.url), reverse=True)
        return final_items

    def _compute_score_breakdown(self, query: str, item: NormalizedResult) -> dict[str, float]:
        query_tokens = {token for token in re.findall(r"[a-z0-9]{3,}", query.lower())}
        text_tokens = {token for token in re.findall(r"[a-z0-9]{3,}", f"{item.title} {item.snippet}".lower())}
        overlap = len(query_tokens.intersection(text_tokens))

        breakdown = {
            "source_weight": item.source_rank_weight,
            "query_overlap": min(0.3, overlap * 0.02),
            "doi_bonus": 0.2 if item.doi else 0.0,
            "evidence_type_bonus": {
                "guideline": 0.16,
                "meta_analysis": 0.14,
                "systematic_review": 0.12,
                "rct": 0.1,
                "cohort": 0.06,
                "case_control": 0.04,
                "case_report": 0.02,
                "review": 0.03,
                "unknown": 0.0,
            }.get(item.evidence_type, 0.0),
            "recency_bonus": 0.0,
            "domain_trust_bonus": 0.0,
            "low_quality_penalty": 0.0,
        }

        window = max(0, int(getattr(self.researcher.cfg, "medical_time_window_years", 0)))
        if item.year is not None and window > 0:
            if item.year >= datetime.now().year - window:
                breakdown["recency_bonus"] = 0.08

        tier0 = set(self._parse_domain_list(getattr(self.researcher.cfg, "domain_tier0", "")))
        tier1 = set(self._parse_domain_list(getattr(self.researcher.cfg, "domain_tier1", "")))
        if item.domain in tier0:
            breakdown["domain_trust_bonus"] = 0.05
        elif item.domain in tier1:
            breakdown["domain_trust_bonus"] = 0.03

        if any(low_q in item.domain for low_q in ("medium.com", "blogspot.", "wordpress.", "reddit.com")):
            breakdown["low_quality_penalty"] = -0.15

        return breakdown

    def _make_explain_line(self, item: NormalizedResult) -> str:
        bd = item.score_breakdown
        return (
            f"source={item.source}({bd.get('source_weight', 0):.2f}) "
            f"overlap={bd.get('query_overlap', 0):.2f} "
            f"doi={bd.get('doi_bonus', 0):.2f} "
            f"evidence={item.evidence_type}({bd.get('evidence_type_bonus', 0):.2f}) "
            f"recency={bd.get('recency_bonus', 0):.2f} "
            f"domain={bd.get('domain_trust_bonus', 0):.2f} "
            f"penalty={bd.get('low_quality_penalty', 0):.2f}"
        )

    def _apply_rerank(self, query: str, results: list[NormalizedResult]) -> list[NormalizedResult]:
        for item in results:
            breakdown = self._compute_score_breakdown(query, item)
            final_score = sum(breakdown.values())
            item.score_breakdown = breakdown
            item.final_score = round(final_score, 4)
            item.explain = self._make_explain_line(item)

        return sorted(results, key=lambda r: r.final_score, reverse=True)

    def _emit_rerank_logs(
        self,
        query: str,
        mode: str,
        candidates_total: int,
        deduped_total: int,
        ranked: list[NormalizedResult],
    ) -> None:
        log_mode = str(getattr(self.researcher.cfg, "rerank_explain_log_mode", "dual")).lower()
        explain_scope = max(1, int(getattr(self.researcher.cfg, "rerank_explain_scope", 10)))
        top_items = ranked[:explain_scope]

        if log_mode in {"dual", "console"}:
            self.logger.info(
                "Rerank explain summary | mode=%s candidates=%s deduped=%s top_n=%s",
                mode,
                candidates_total,
                deduped_total,
                len(top_items),
            )
            for idx, item in enumerate(top_items, start=1):
                doi_flag = "yes" if item.doi else "no"
                self.logger.info(
                    "RERANK #%s | %s | score=%.4f | year=%s | doi=%s | evidence=%s | domain=%s | title=%s",
                    idx,
                    item.source,
                    item.final_score,
                    item.year,
                    doi_flag,
                    item.evidence_type,
                    item.domain,
                    item.title[:120],
                )

        if log_mode in {"dual", "json"} and self.json_handler:
            self.json_handler.log_event(
                "retrieval_rerank_explain",
                {
                    "query": query,
                    "mode": mode,
                    "candidates_total": candidates_total,
                    "deduped_total": deduped_total,
                    "top_n": len(top_items),
                    "results": [
                        {
                            "rank": idx,
                            "url": item.url,
                            "source": item.source,
                            "final_score": item.final_score,
                            "score_breakdown": item.score_breakdown,
                            "explain": item.explain,
                            "year": item.year,
                            "doi": item.doi,
                            "journal": item.journal,
                            "evidence_type": item.evidence_type,
                        }
                        for idx, item in enumerate(top_items, start=1)
                    ],
                },
            )

    def _rank_and_extract_urls(self, query: str, results: list[NormalizedResult]) -> list[str]:
        deduped = self._dedupe_results(results)
        ranked = self._apply_rerank(query, deduped)
        mode = str(getattr(self.researcher.cfg, "retriever_priority_mode", "parallel"))
        self._emit_rerank_logs(
            query=query,
            mode=mode,
            candidates_total=len(results),
            deduped_total=len(deduped),
            ranked=ranked,
        )
        return [item.url for item in ranked if item.url]

    async def _scrape_data_by_urls(self, sub_query, query_domains: list | None = None):
        """
        Runs a sub-query across multiple retrievers and scrapes the resulting URLs.

        Args:
            sub_query (str): The sub-query to search for.

        Returns:
            list: A list of scraped content results.
        """
        if query_domains is None:
            query_domains = []

        new_search_urls = await self._search_relevant_source_urls(sub_query, query_domains)

        # Log the research process if verbose mode is on
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "researching",
                f"🤔 Researching for relevant information across multiple sources...\n",
                self.researcher.websocket,
            )

        # Scrape the new URLs
        scraped_content = await self.researcher.scraper_manager.browse_urls(new_search_urls)

        if self.researcher.vector_store:
            self.researcher.vector_store.load(scraped_content)

        return scraped_content

    async def _search(self, retriever, query):
        """
        Perform a search using the specified retriever.
        
        Args:
            retriever: The retriever class to use
            query: The search query
            
        Returns:
            list: Search results
        """
        retriever_name = retriever.__name__
        is_mcp_retriever = "mcpretriever" in retriever_name.lower()
        
        self.logger.info(f"Searching with {retriever_name} for query: {query}")
        
        try:
            # Instantiate the retriever
            retriever_instance = retriever(
                query=query, 
                headers=self.researcher.headers,
                query_domains=self.researcher.query_domains,
                websocket=self.researcher.websocket if is_mcp_retriever else None,
                researcher=self.researcher if is_mcp_retriever else None
            )
            
            # Log MCP server configurations if using MCP retriever
            if is_mcp_retriever and self.researcher.verbose:
                await stream_output(
                    "logs",
                    "mcp_retrieval",
                    f"🔌 Consulting MCP server(s) for information on: {query}",
                    self.researcher.websocket,
                )
            
            # Perform the search
            if hasattr(retriever_instance, 'search'):
                results = retriever_instance.search(
                    max_results=self.researcher.cfg.max_search_results_per_query
                )
                
                # Log result information
                if results:
                    result_count = len(results)
                    self.logger.info(f"Received {result_count} results from {retriever_name}")
                    
                    # Special logging for MCP retriever
                    if is_mcp_retriever:
                        if self.researcher.verbose:
                            await stream_output(
                                "logs",
                                "mcp_results",
                                f"✓ Retrieved {result_count} results from MCP server",
                                self.researcher.websocket,
                            )
                        
                        # Log result details
                        for i, result in enumerate(results[:3]):  # Log first 3 results
                            title = result.get("title", "No title")
                            url = result.get("href", "No URL")
                            content_length = len(result.get("body", "")) if result.get("body") else 0
                            self.logger.info(f"MCP result {i+1}: '{title}' from {url} ({content_length} chars)")
                            
                        if result_count > 3:
                            self.logger.info(f"... and {result_count - 3} more MCP results")
                else:
                    self.logger.info(f"No results returned from {retriever_name}")
                    if is_mcp_retriever and self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_no_results",
                            f"ℹ️ No relevant information found from MCP server for: {query}",
                            self.researcher.websocket,
                        )
                
                return results
            else:
                self.logger.error(f"Retriever {retriever_name} does not have a search method")
                return []
        except Exception as e:
            self.logger.error(f"Error searching with {retriever_name}: {str(e)}")
            if is_mcp_retriever and self.researcher.verbose:
                await stream_output(
                    "logs",
                    "mcp_error",
                    f"❌ Error retrieving information from MCP server: {str(e)}",
                    self.researcher.websocket,
                )
            return []
            
    async def _extract_content(self, results):
        """
        Extract content from search results using the browser manager.
        
        Args:
            results: Search results
            
        Returns:
            list: Extracted content
        """
        self.logger.info(f"Extracting content from {len(results)} search results")
        
        # Get the URLs from the search results
        urls = []
        for result in results:
            if isinstance(result, dict) and "href" in result:
                urls.append(result["href"])
        
        # Skip if no URLs found
        if not urls:
            return []
            
        # Make sure we don't visit URLs we've already visited
        new_urls = [url for url in urls if url not in self.researcher.visited_urls]
        
        # Return empty if no new URLs
        if not new_urls:
            return []
            
        # Scrape the content from the URLs
        scraped_content = await self.researcher.scraper_manager.browse_urls(new_urls)
        
        # Add the URLs to visited_urls
        self.researcher.visited_urls.update(new_urls)
        
        return scraped_content
        
    async def _summarize_content(self, query, content):
        """
        Summarize the extracted content.
        
        Args:
            query: The search query
            content: The extracted content
            
        Returns:
            str: Summarized content
        """
        self.logger.info(f"Summarizing content for query: {query}")
        
        # Skip if no content
        if not content:
            return ""
            
        # Summarize the content using the context manager
        summary = await self.researcher.context_manager.get_similar_content_by_query(
            query, content
        )
        
        return summary
        
    async def _update_search_progress(self, current, total):
        """
        Update the search progress.
        
        Args:
            current: Current number of sub-queries processed
            total: Total number of sub-queries
        """
        if self.researcher.verbose and self.researcher.websocket:
            progress = int((current / total) * 100)
            await stream_output(
                "logs",
                "research_progress",
                f"📊 Research Progress: {progress}%",
                self.researcher.websocket,
                True,
                {
                    "current": current,
                    "total": total,
                    "progress": progress
                }
            )
