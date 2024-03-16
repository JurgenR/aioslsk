import struct
from typing import List


DEFAULT_EXCLUDED_SEARCH_PHRASES: List[str] = ['banned phrase']
HEADER_SIZE: int = struct.calcsize('I')
MAX_ITEM_RECOMMENDATIONS: int = 100
"""Max items returned by GetItemRecommendations per list (value is known)"""
MAX_RECOMMENDATIONS: int = 100
"""Max items returned by GetRecommendations per list (value is known)"""
MAX_GLOBAL_RECOMMENDATIONS: int = 200
"""Max items returned by GetGlobalRecommendations per list (value is known)"""
MAX_SIMILAR_USERS: int = 500
"""Max length of the list of GetSimilarUsers (value is UNKNOWN)"""
MAX_ITEM_SIMILAR_USERS: int = 500
"""Max length of the list of GetItemSimilarUsers (value is UNKNOWN)"""
