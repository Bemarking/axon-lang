import torch
import math
from typing import List, Dict, Tuple
from axon.runtime.mek.latent_space import LatentState
from axon.backends.mek_adapters import AbstractBackendProvider

class ModelCapabilityProfile:
    """
    Representa el perfil de capacidad de un modelo basado en la
    Matriz de Información de Fisher (FIM) o heurísticas equivalentes.
    """
    def __init__(self, provider: AbstractBackendProvider, max_entropy_capacity: float, cost_weight: float = 1.0):
        self.provider = provider
        # Máxima entropía que el modelo puede manejar sin decaer en una alucinación severa
        self.max_entropy_capacity = max_entropy_capacity  
        # Peso de coste (ej: Gemini 1.5 Pro cuesta más que Haiku)
        self.cost_weight = cost_weight
        
class BayesianRouter:
    """
    Enrutador a nivel de núcleo que usa Inferencia Bayesiana Activa para despachar
    la carga al modelo adecuado.
    
    Evalúa el estado latente entrante y decide si un modelo pequeño puede resolverlo
    o si requiere ruteo a un oráculo más pesado. Todo se calcula midiendo la 
    Divergencia de Kullback-Leibler (KL) y la entropía del tensor original.
    """
    
    @staticmethod
    def _compute_kl_divergence_proxy(state: LatentState, profile: ModelCapabilityProfile) -> float:
        """
        Calcula un proxy de la divergencia KL entre la distribución de información
        contenida en el estado latente y la capacidad estimada del modelo.
        
        Una divergencia alta significa que el modelo "no entiende" o "no abarca" la
        complejidad del tensor entrante (Information Bottleneck).
        """
        tensor_entropy = state.entropy
        
        # Si la entropía del problema excede la capacidad del modelo, la divergencia crece exponencialmente.
        if tensor_entropy > profile.max_entropy_capacity:
            divergence = math.exp(tensor_entropy - profile.max_entropy_capacity) - 1.0
        else:
            # Si el modelo sobra para la tarea, la divergencia es baja.
            divergence = 0.01 * (profile.max_entropy_capacity - tensor_entropy)
            
        return divergence

    @classmethod
    def select_optimal_provider(cls, state: LatentState, profiles: List[ModelCapabilityProfile]) -> AbstractBackendProvider:
        """
        Resuelve el POMDP (Partially Observable Markov Decision Process)
        eligiendo la ruta que minimice la Energía Libre (Free Energy Principle):
        Minimiza (Divergencia KL + Coste ponderado)
        """
        if not profiles:
            raise ValueError("No routing profiles provided.")
            
        best_provider = None
        min_free_energy = float('inf')
        
        print("\n[BayesianRouter] Evaluando Múltiples Oráculos vía Inferencia Activa...")
        for profile in profiles:
            # D_{KL}(Q || P)
            kl_div = cls._compute_kl_divergence_proxy(state, profile)
            
            # Ecuación de Energía Libre simplificada: F = D_KL + E[Costo] 
            free_energy = kl_div + (0.5 * profile.cost_weight)
            
            provider_name = getattr(profile.provider, 'model_name', profile.provider.__class__.__name__)
            print(f"  -> {provider_name:<25} | KL Div: {kl_div:.4f} | Free Energy: {free_energy:.4f}")
            
            if free_energy < min_free_energy:
                min_free_energy = free_energy
                best_provider = profile.provider
                
        winner_name = getattr(best_provider, 'model_name', best_provider.__class__.__name__)
        print(f"[BayesianRouter] -> Oráculo Óptimo Seleccionado: {winner_name}\n")
        
        return best_provider
