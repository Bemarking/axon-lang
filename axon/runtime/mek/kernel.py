import uuid
from typing import Dict, Any, Optional

from .latent_space import LatentState, DiffeomorphicTransformer

class ModelExecutionKernel:
    """
    El corazón (Hypervisor cognitivo) de Axon v0.20.0.
    Funciona como un planificador en un Proceso de Decisión de Markov (MDP),
    interceptando la comunicación abstracta generada por el IR Generator.
    Evita la decodificación logocéntrica (texto natural) siempre que es posible.
    """
    def __init__(self):
        self.kernel_id = str(uuid.uuid4())
        # Cache topológico (Context Manager VRAM persistente)
        self.tensor_registry: Dict[str, LatentState] = {}
        # Inicializa transformaciones entre colectores conocidos
        self.transformer = DiffeomorphicTransformer(transformation_matrices={})
        
    def intercept_latent_state(self, source_node_id: str, state_tensor: Any, origin_model_id: str) -> str:
        """
        En vez de emitir string, el nodo emite su cerebro en pausa.
        Registra el estado continuo y devuelve un identificador de memoria (Puntero Latente).
        """
        # (Asumiendo que 'state_tensor' es o puede convertirse a torch.Tensor)
        import torch
        if not isinstance(state_tensor, torch.Tensor):
            # Fallback for mock/simulation in Phase 1 setup
            state_tensor = torch.zeros((1, 1024))
            
        latent = LatentState(tensor=state_tensor, origin_model_id=origin_model_id)
        pointer = f"PTR_LATENT_{source_node_id}_{uuid.uuid4().hex[:8]}"
        self.tensor_registry[pointer] = latent
        
        # El IR del compilador de Axon maneja este string de puntero en sus flujos lógicos,
        # mientras la entropía matématica existe acá de fondo.
        return pointer
        
    def route_latent_state(self, source_pointer: str, target_model_id: str) -> Any:
        r"""
        Recupera el estado latente $ \mathcal{H}_A $ y lo proyecta
        hacia el dominio $ \mathcal{H}_B $. Telepatía Tensorial matemática pura.
        """
        if source_pointer not in self.tensor_registry:
            raise KeyError(f"Kernel Error: Puntero latente huérfano o recolectado {source_pointer}")
            
        state_a = self.tensor_registry[source_pointer]
        
        try:
            # Proyección topológica difeomórfica $\mathcal{H}_A \to \mathcal{H}_B$
            projected_h_b = self.transformer.project(state_a, target_model_id)
            return projected_h_b
        except Exception as e:
            # En caso que de no existan adaptadores puros, Axon delega al Transductor Lógico
            # Esta lógica se manejará en `mek_adapters.py` para Cajas Negras.
            raise e

    def flush_memory(self):
        """Limpia el KV-Cache topológico (VRAM Cleanup)"""
        self.tensor_registry.clear()
