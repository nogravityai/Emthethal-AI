from typing import List, Any
from app.models.schemas import BoundingBox

def normalize_token_fragments(tokens: List[Any], x_tol: float = 8.0, y_tol: float = 4.0) -> List[Any]:
    """
    Visually merges broken OCR fragments (e.g. [م], [رض], [السكري]) into cohesive visual blocks
    BEFORE spatial assignment. Strictly visual proximity without semantic manipulation.
    """
    if not tokens:
        return []
        
    # Sort tokens in reading order (top-to-bottom, right-to-left for Arabic)
    # Assuming page_pixels, y increases downwards, x increases rightwards.
    # We sort by Y (line grouping) then by X descending (RTL).
    sorted_tokens = sorted(tokens, key=lambda t: (t.bbox.y1 // y_tol, -t.bbox.x2))
    
    merged = []
    current_chain = [sorted_tokens[0]]
    
    for token in sorted_tokens[1:]:
        prev_token = current_chain[-1]
        
        # Check if same line and close horizontally
        same_line = abs(token.bbox.y1 - prev_token.bbox.y1) <= y_tol
        # RTL: prev_token is to the right of token. Distance = prev_token.x1 - token.x2
        x_dist = prev_token.bbox.x1 - token.bbox.x2
        
        # Also handle LTR cases where token is to the right of prev_token
        x_dist_ltr = token.bbox.x1 - prev_token.bbox.x2
        
        if same_line and (0 <= x_dist <= x_tol or 0 <= x_dist_ltr <= x_tol):
            current_chain.append(token)
        else:
            merged.append(_combine_fragments(current_chain))
            current_chain = [token]
            
    if current_chain:
        merged.append(_combine_fragments(current_chain))
        
    return merged

def _combine_fragments(chain: List[Any]) -> Any:
    if len(chain) == 1:
        return chain[0]
        
    # Create a new bounding box that encompasses all fragments
    x1 = min(t.bbox.x1 for t in chain)
    y1 = min(t.bbox.y1 for t in chain)
    x2 = max(t.bbox.x2 for t in chain)
    y2 = max(t.bbox.y2 for t in chain)
    page_width = chain[0].bbox.page_width
    page_height = chain[0].bbox.page_height
    
    # Sort left-to-right to concatenate text (even for RTL, strings are stored in logical order)
    # Actually, if the tokens are Arabic, their string representation is logical.
    # We sort chain by x1 to concatenate correctly.
    sorted_chain = sorted(chain, key=lambda t: t.bbox.x1)
    combined_text = "".join(t.text for t in sorted_chain)
    
    # In a real scenario, we'd return a new Token object.
    # Assuming Token has a model_copy or we just mutate/return a proxy for now.
    # For architecture purposes, we return a merged mock.
    merged_token = chain[0].model_copy(deep=True)
    merged_token.text = combined_text
    merged_token.bbox = BoundingBox(
        x1=x1, y1=y1, x2=x2, y2=y2,
        coordinate_space=chain[0].bbox.coordinate_space,
        page_width=page_width,
        page_height=page_height
    )
    return merged_token
