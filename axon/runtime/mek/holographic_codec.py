import torch
from typing import List, Dict, Tuple
from .latent_space import LatentState

class TokenLogprob:
    def __init__(self, token: str, logprob: float, top_logprobs: Dict[str, float] = None):
        self.token = token
        self.logprob = logprob
        self.top_logprobs = top_logprobs or {}

class HolographicCodec:
    """
    Geometría de la Información y Reconstrucción Holográfica.
    Este códec de frontera toma respuestas discretas (tokens) de cajas negras
    (OpenAI/Anthropic) y sus `logprobs` para instanciar un tensor continuo topológico
    que emule el estado diferencial.
    """
    
    def __init__(self, vocab_size: int = 100000, embedding_dim: int = 1024):
        self.vocab_size = vocab_size
        self.embedding_dim = embedding_dim
        # Matriz de proyección pseudo-latente (usualmente los embeddings del tokenizer de Axon)
        self.E = torch.randn((self.vocab_size, self.embedding_dim)) / (self.embedding_dim ** 0.5)

    def absorb_oracle_decoherence(
        self, 
        tokens_with_logprobs: List[TokenLogprob], 
        origin_model_id: str,
        logical_ast: Dict = None
    ) -> LatentState:
        """
        Reconstrucción Holográfica por Decoherencia Controlada:
        1. La caja negra escupe un token T_i y su distribución P(T_i).
        2. El Códec reconstruye la incerteza latente usando el gradiente de certidumbre.
        3. Instancia la estructura ontológica superior de Axon (LatentState).
        """
        seq_len = len(tokens_with_logprobs)
        holographic_tensor = torch.zeros((seq_len, self.embedding_dim))
        
        for i, t_info in enumerate(tokens_with_logprobs):
            # Transform logprob to probability P(T_i) = exp(logprob)
            p_ti = torch.exp(torch.tensor(t_info.logprob))
            
            # Simulated pseudo-index hashing for demonstration of topological projection
            token_idx = hash(t_info.token) % self.vocab_size
            
            # The holographic projection weights the base embedding by its mathematical certainty
            # In a real scenario, this involves a weighted sum over the top_logprobs distribution.
            base_vector = self.E[token_idx]
            
            # Incorporate entropy from alternatives
            entropy_factor = 1.0
            if t_info.top_logprobs:
                entropy_sum = sum(torch.exp(torch.tensor(lp)).item() * lp for lp in t_info.top_logprobs.values())
                entropy_factor = -entropy_sum
            
            holographic_tensor[i] = base_vector * p_ti * (1.0 + entropy_factor)

        # Average pooling across sequence locally to get a single conceptual state
        # Or alternatively return the full sequence tensor if maintaining attention matrix.
        final_state = torch.mean(holographic_tensor, dim=0).unsqueeze(0)
        
        return LatentState(
            tensor=final_state,
            origin_model_id=f"holographic_{origin_model_id}",
            semantic_type="AST_LOGICAL_RECONSTRUCT" if logical_ast else "UNKNOWN"
        )
