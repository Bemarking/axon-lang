import asyncio
import traceback
from axon.backends.base_backend import CompiledStep
from axon.runtime.executor import Executor
from tests.test_executor import make_program, make_unit
from tests.test_ots_runtime import OTSMockModelClient

async def run():
    dummy_code = '''
async def summarize_email(target: str) -> str:
    return "Dummy Summary: " + target
'''
    client = OTSMockModelClient(responses={'default': dummy_code})
    executor = Executor(client=client)
    ots_metadata = {
        'ots_apply': {
            'ots_name': 'EmailSummarizer',
            'target': 'Raw Email Text',
            'ots_definition': {
                'teleology': 'Summarize briefly',
                'linear_constraints': [('length', 'stricly_once')],
                'homotopy_search': 'deep',
                'loss_function': 'L2',
                'output_type': 'string'
            }
        }
    }
    step = CompiledStep(step_name='summarize_email', system_prompt='', user_prompt='', metadata=ots_metadata)
    program = make_program([make_unit('main_flow', [step])])
    
    try:
        result = await executor.execute(program)
        print('SUCCESS:', result.success)
        if not result.success:
            print('ERROR:', result.unit_results[0].error)
    except Exception as e:
        traceback.print_exc()

asyncio.run(run())
