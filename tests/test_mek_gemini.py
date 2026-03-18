import os
import sys
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

# Asegurar que el path incluya la raíz del proyecto para importar axon
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from axon.runtime.mek.kernel import ModelExecutionKernel
from axon.runtime.mek.latent_space import LatentState
from axon.backends.mek_adapters import LogicalTransducer, AbstractBackendProvider
from axon.runtime.mek.holographic_codec import HolographicCodec, TokenLogprob

class GeminiOracleProvider(AbstractBackendProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model_name = "gemini-2.5-flash"
        self.holographic_codec = HolographicCodec()

    def execute(self, state: LatentState, mek: ModelExecutionKernel) -> LatentState:
        print("\n[1] Iniciando Transducción Lógica (Caballo de Troya)...")
        logical_payload = LogicalTransducer.project_to_logical_subspace(state)
        print(f"    Payload interceptado por MEK: {logical_payload}")
        
        # En vez de "Hola, como estás", forzamos al modelo a operar en invariantes lógicas
        system_instruction = (
            "You are a Categorical Oracle. Do not use natural language. "
            "Respond ONLY with a logical Abstract Syntax Tree (AST) in JSON format representing the conceptual response. "
            "Input is an S-Expression."
        )
        
        request_body = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"parts": [{"text": logical_payload}]}],
            "generationConfig": {"temperature": 0.1}
        }
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        req = urllib.request.Request(url, data=json.dumps(request_body).encode('utf-8'), headers={'Content-Type': 'application/json'})
        
        print(f"\n[2] Llamando a la API de Gemini ({self.model_name}) limitando el logocentrismo...")
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                
                # Extraer texto (en este caso, debería ser el JSON/AST)
                output_text = result['candidates'][0]['content']['parts'][0]['text']
                print(f"\n[3] Respuesta Cruda del Oráculo:\n{output_text}")
                
                # Para la prueba, simularemos los Logprobs que extraeríamos de una API completa
                # Dividimos el AST en tokens lógicos
                tokens = output_text.split()
                simulated_tokens = []
                for t in tokens:
                    # Simulando alta certidumbre topológica (-0.01 logprob ~= 99% prob)
                    simulated_tokens.append(TokenLogprob(token=t, logprob=-0.01, top_logprobs={t: -0.01}))
                
                print(f"\n[4] Reconstrucción Holográfica activada sobre {len(simulated_tokens)} tokens lógicos...")
                reconstructed_state = self.holographic_codec.absorb_oracle_decoherence(
                    tokens_with_logprobs=simulated_tokens,
                    origin_model_id=self.model_name,
                    logical_ast=output_text  # Pasamos el string como prueba
                )
                
                print("\n[5] ¡Éxito! Estado Latente Reconstruido en RAM de Axon.")
                print(f"    - Origen: {reconstructed_state.origin_model_id}")
                print(f"    - Tipo Semántico: {reconstructed_state.semantic_type}")
                print(f"    - Entropía del Tensor: {reconstructed_state.entropy:.4f}")
                print(f"    - Dimensión del Tensor: {reconstructed_state.tensor.shape}")
                
                return reconstructed_state
                
        except urllib.error.HTTPError as e:
            error_msg = e.read().decode()
            print(f"Error HTTP Calling Gemini: {e.code} - {error_msg}", flush=True)
            return state

def main():
    load_dotenv()
    gemini_key = os.getenv("API_KEY_GEMINI")
    if not gemini_key:
        print("Error: No se encontró API_KEY_GEMINI en el archivo .env")
        return
        
    print("=== INICIANDO PRUEBA DE TELEPATÍA TENSORIAL CON GEMINI BLACKBOX ===")
    mek = ModelExecutionKernel()
    
    import torch
    # Simulamos el estado latente de un Agente A (ej. un tensor de 1024 dims)
    fake_hidden_state_a = torch.randn((1, 1024))
    state_a = LatentState(tensor=fake_hidden_state_a, origin_model_id="axon_agent_A")
    
    # Proveedor de Gemini
    oracle = GeminiOracleProvider(api_key=gemini_key)
    
    # Ejecución
    oracle.execute(state_a, mek)
    print("\n=== PRUEBA FINALIZADA ===")

if __name__ == "__main__":
    main()
