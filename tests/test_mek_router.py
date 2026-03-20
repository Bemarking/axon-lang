import os
import sys
import pytest  # noqa: F401 — guard for CI

pytest.importorskip("torch", reason="torch not installed (integration test)")
pytest.importorskip("dotenv", reason="python-dotenv not installed (integration test)")
import torch
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from axon.runtime.mek.latent_space import LatentState
from axon.runtime.routers.bayesian_selector import BayesianRouter, ModelCapabilityProfile

# Dummy Providers for testing routing logic without actual API calls
class DummyProvider:
    def __init__(self, name: str):
        self.model_name = name

def main():
    print("=== INICIANDO PRUEBA DE ENRUTAMIENTO BAYESIANO (MEK) ===")
    
    # Perfiles de Capacidad (Simulando Inferencia de Capacidades / FIM)
    # Haiku: Rápido, barato, pero solo maneja baja entropía sin alucinar.
    haiku_provider = DummyProvider("claude-3-haiku-20240307")
    profile_haiku = ModelCapabilityProfile(provider=haiku_provider, max_entropy_capacity=5.0, cost_weight=0.2)
    
    # Gemini 1.5 Pro: Lento, caro, pero maneja alta entropía topológica.
    gemini_provider = DummyProvider("gemini-1.5-pro")
    profile_gemini = ModelCapabilityProfile(provider=gemini_provider, max_entropy_capacity=15.0, cost_weight=2.0)
    
    profiles = [profile_haiku, profile_gemini]
    
    # Prueba 1: Tarea Simple (Baja Entropía)
    print("\n[Ronda 1] Llegada de Tensor de Baja Entropía (Ej. Saludo o Tarea Trivial)")
    # Simulamos baja entropía inicializando un tensor con poca varianza
    low_variance_tensor = torch.zeros((1, 512)) + 0.1
    state_simple = LatentState(tensor=low_variance_tensor, origin_model_id="kivi_agent")
    state_simple.entropy = 3.5  # Forzamos valor para prueba
    
    winner_simple = BayesianRouter.select_optimal_provider(state_simple, profiles)
    assert winner_simple.model_name == "claude-3-haiku-20240307", "Debería haber ganado Haiku"
    
    # Prueba 2: Tarea Compleja (Alta Entropía)
    print("\n[Ronda 2] Llegada de Tensor de Alta Entropía (Ej. Análisis Recursivo Complejo)")
    # Simulamos alta entropía con puro ruido
    high_variance_tensor = torch.randn((1, 1024)) * 10 
    state_complex = LatentState(tensor=high_variance_tensor, origin_model_id="kivi_agent")
    state_complex.entropy = 12.0 # Forzamos valor para prueba
    
    winner_complex = BayesianRouter.select_optimal_provider(state_complex, profiles)
    assert winner_complex.model_name == "gemini-1.5-pro", "Debería haber ganado Gemini Pro"

    print("\n=== PRUEBA DE ROUTING FINALIZADA CON ÉXITO ===")

if __name__ == "__main__":
    main()
