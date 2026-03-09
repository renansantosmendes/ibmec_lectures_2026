# -*- coding: utf-8 -*-
"""
YouTube Transcript Collector

This module provides a unified class for collecting and processing YouTube video transcripts.
It handles video searching, ID extraction, and transcript retrieval in a single workflow.
"""

import os
import re
import ast
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass, field
from datetime import datetime

from youtube_transcript_api import YouTubeTranscriptApi
from langchain_community.tools import YouTubeSearchTool


@dataclass
class VideoTranscript:
    """Data class representing a video and its transcript."""
    video_id: str
    query: str
    transcript_text: str
    transcript_segments: List[Dict[str, Any]] = field(default_factory=list)
    language: str = "unknown"
    collected_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def __repr__(self) -> str:
        return (
            f"VideoTranscript(id={self.video_id}, "
            f"language={self.language}, "
            f"length={len(self.transcript_text)} chars)"
        )


class YouTubeTranscriptCollector:
    """
    Unified class for collecting YouTube video transcripts.
    
    Handles the complete workflow:
    1. Search for videos based on a query
    2. Extract video IDs from URLs
    3. Retrieve transcripts for each video
    
    Example:
        collector = YouTubeTranscriptCollector(max_videos=5, languages=["pt", "pt-BR", "en"])
        results = collector.collect("python tutorial")
    """
    
    def __init__(
        self,
        max_videos: int = 5,
        languages: Optional[List[str]] = None,
        verbose: bool = True
    ) -> None:
        """
        Initialize the YouTube Transcript Collector.
        
        Args:
            max_videos: Maximum number of videos to collect transcripts for
            languages: List of language codes to try in order (e.g., ["pt", "pt-BR", "en"])
            verbose: Whether to print status messages
        """
        self.max_videos = max_videos
        self.languages = languages or ["pt", "pt-BR", "en"]
        self.verbose = verbose
        self.results: List[VideoTranscript] = []
    
    def _log(self, message: str) -> None:
        """Print a message if verbose mode is enabled."""
        if self.verbose:
            print(message)
    
    def _extract_video_ids(self, urls: List[str]) -> List[str]:
        """
        Extract video IDs from a list of YouTube URLs.
        
        Args:
            urls: List of YouTube URLs
            
        Returns:
            List of video IDs
        """
        video_ids = []
        
        for url in urls:
            if not isinstance(url, str):
                continue
                
            parsed = urlparse(url)
            
            # Handle youtube.com and www.youtube.com
            if parsed.hostname in ("www.youtube.com", "youtube.com"):
                qs = parse_qs(parsed.query)
                if "v" in qs:
                    video_ids.append(qs["v"][0])
                    continue
                match = re.match(r"^/embed/([a-zA-Z0-9_-]{11})", parsed.path)
                if match:
                    video_ids.append(match.group(1))
                    continue
            
            # Handle youtu.be short URLs
            if parsed.hostname in ("youtu.be",):
                match = re.match(r"^/([a-zA-Z0-9_-]{11})", parsed.path)
                if match:
                    video_ids.append(match.group(1))
                    continue
            
            # Generic pattern matching
            match = re.search(r"(?:v=|/)([a-zA-Z0-9_-]{11})", url)
            if match:
                video_ids.append(match.group(1))
        
        return list(set(video_ids))  # Remove duplicates
    
    def _search_youtube_urls(
        self,
        query: str,
        number_of_videos: int
    ) -> List[str]:
        """
        Search for YouTube videos based on a query.
        
        Args:
            query: Search query string
            number_of_videos: Number of videos to retrieve
            
        Returns:
            List of YouTube URLs
        """
        try:
            self._log(f"🔍 Searching for '{query}' (max {number_of_videos} videos)...")
            
            search_query = f"{query},{number_of_videos}"
            results = ast.literal_eval(YouTubeSearchTool().run(search_query))
            
            self._log(f"✅ Found {len(results)} URLs")
            return results
        except Exception as e:
            self._log(f"❌ Search error: {e}")
            return []
    
    def _get_transcript(self, video_id: str) -> Optional[VideoTranscript]:
        """
        Retrieve transcript for a single video.
        
        Args:
            video_id: YouTube video ID
            
        Returns:
            VideoTranscript object or None if transcript cannot be retrieved
        """
        try:
            self._log(f"  📥 Fetching transcript for {video_id}...")
            
            transcript = YouTubeTranscriptApi().fetch(
                video_id=video_id,
                languages=self.languages
            )
            
            # Combine all transcript segments into a single text
            full_text = " ".join([seg.text for seg in transcript.snippets])
            
            # Get the language of the transcript
            language = getattr(transcript, "language", "unknown")
            
            self._log(f"  ✅ Transcript retrieved ({len(full_text)} characters)")
            
            return VideoTranscript(
                video_id=video_id,
                query=self.current_query,
                transcript_text=full_text,
                transcript_segments=transcript,
                language=language
            )
        except Exception as e:
            self._log(f"  ❌ Failed to get transcript: {e}")
            return None
    
    def collect(self, query: str) -> List[VideoTranscript]:
        """
        Collect transcripts for videos matching the query.
        
        This is the main method that orchestrates the entire workflow:
        1. Search for videos
        2. Extract video IDs
        3. Retrieve transcripts
        
        Args:
            query: Search query for videos
            
        Returns:
            List of VideoTranscript objects
        """
        self.current_query = query
        self.results = []
        
        self._log(f"\n{'='*60}")
        self._log(f"YouTube Transcript Collection Started")
        self._log(f"{'='*60}")
        
        # Step 1: Search for videos
        urls = self._search_youtube_urls(query, self.max_videos)
        
        if not urls:
            self._log("⚠️ No videos found")
            return []
        
        # Step 2: Extract video IDs
        self._log(f"\n📺 Extracting video IDs...")
        video_ids = self._extract_video_ids(urls)
        self._log(f"✅ Extracted {len(video_ids)} video IDs")
        
        # Step 3: Get transcripts
        self._log(f"\n📝 Retrieving transcripts...")
        for idx, video_id in enumerate(video_ids, 1):
            self._log(f"\n[{idx}/{len(video_ids)}] Processing video...")
            transcript = self._get_transcript(video_id)
            if transcript:
                self.results.append(transcript)
        
        self._log(f"\n{'='*60}")
        self._log(f"Collection Complete: {len(self.results)} transcripts retrieved")
        self._log(f"{'='*60}\n")
        
        return self.results
    
    def get_results_summary(self) -> Dict[str, Any]:
        """
        Get a summary of collected transcripts.
        
        Returns:
            Dictionary with summary information
        """
        if not self.results:
            return {"total_transcripts": 0, "transcripts": []}
        
        return {
            "total_transcripts": len(self.results),
            "transcripts": [
                {
                    "video_id": t.video_id,
                    "language": t.language,
                    "text_length": len(t.transcript_text),
                    "segments_count": len(t.transcript_segments),
                    "collected_at": t.collected_at
                }
                for t in self.results
            ]
        }
    
    def get_combined_text(self) -> str:
        """
        Get all transcripts combined into a single text.
        
        Returns:
            Combined transcript text
        """
        return " ".join([t.transcript_text for t in self.results])
