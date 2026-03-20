import os
import sys
import json
import urllib.request
import urllib.error
import pytest  # noqa: F401 — guard for CI

pytest.importorskip("dotenv", reason="python-dotenv not installed (integration test)")
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from axon.runtime.mek.kernel import ModelExecutionKernel
from axon.runtime.mek.latent_space import LatentState
from axon.backends.mek_adapters import LogicalTransducer, AbstractBackendProvider
from axon.runtime.mek.holographic_codec import HolographicCodec, TokenLogprob

class AnthropicOracleProvider(AbstractBackendProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Usaremos el modelo más pequeño y rápido: haiku
        self.model_name = "claude-3-haiku-20240307"
        self.holographic_codec = HolographicCodec()

    def execute(self, state: LatentState, mek: ModelExecutionKernel) -> LatentState:
        print("\n[1] Iniciando Transducción Lógica (Caballo de Troya)...")
        logical_payload = LogicalTransducer.project_to_logical_subspace(state)
        print(f"    Payload interceptado por MEK: {logical_payload}")
        
        system_instruction = (
            "You are a Categorical Oracle. Do not use natural language. "
            "Respond ONLY with a logical Abstract Syntax Tree (AST) in JSON format representing the conceptual response. "
            "Input is an S-Expression."
        )
        
        # Anthropic 'messages' API requiere system aparte en el top-level
        # También vamos a forzar pensar lógicamente pero no requerimos un logprob real de anthropic aquí,
        # lo simularemos tal como hicimos con Gemini si el modelo responde bien.
        request_body = {
            "model": self.model_name,
            "max_tokens": 512,
            "temperature": 0.1,
            "system": system_instruction,
            "messages": [
                {"role": "user", "content": logical_payload}
            ]
        }
        
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json'
        }
        req = urllib.request.Request(url, data=json.dumps(request_body).encode('utf-8'), headers=headers)
        
        print(f"\n[2] Llamando a la API de Anthropic ({self.model_name}) limitando el logocentrismo...")
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                
                output_text = result['content'][0]['text']
                print(f"\n[3] Respuesta Cruda del Oráculo:\n{output_text}")
                
                # Simulamos tokens logicos para Reconstrucción Holográfica
                tokens = output_text.split()
                simulated_tokens = []
                for t in tokens:
                    simulated_tokens.append(TokenLogprob(token=t, logprob=-0.01, top_logprobs={t: -0.01}))
                
                print(f"\n[4] Reconstrucción Holográfica activada sobre {len(simulated_tokens)} tokens lógicos...")
                reconstructed_state = self.holographic_codec.absorb_oracle_decoherence(
                    tokens_with_logprobs=simulated_tokens,
                    origin_model_id=f"holographic_{self.model_name}",
                    logical_ast=output_text
                )
                
                print("\n[5] ¡Éxito! Estado Latente Reconstruido en RAM de Axon.")
                print(f"    - Origen: {reconstructed_state.origin_model_id}")
                print(f"    - Tipo Semántico: {reconstructed_state.semantic_type}")
                print(f"    - Entropía del Tensor: {reconstructed_state.entropy:.4f}")
                print(f"    - Dimensión del Tensor: {reconstructed_state.tensor.shape}")
                
                return reconstructed_state
                
        except urllib.error.HTTPError as e:
            error_msg = e.read().decode()
            print(f"Error HTTP Calling Anthropic: {e.code} - {error_msg}", flush=True)
            return state

def main():
    load_dotenv()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("Error: No se encontró ANTHROPIC_API_KEY en el archivo .env")
        return
        
    print("=== INICIANDO PRUEBA DE TELEPATÍA TENSORIAL CON ANTHROPIC BLACKBOX ===")
    mek = ModelExecutionKernel()
    
    import torch
    fake_hidden_state_a = torch.randn((1, 1024))
    state_a = LatentState(tensor=fake_hidden_state_a, origin_model_id="axon_agent_A")
    
    oracle = AnthropicOracleProvider(api_key=anthropic_key)
    oracle.execute(state_a, mek)
    print("\n=== PRUEBA FINALIZADA ===")

if __name__ == "__main__":
    main()
