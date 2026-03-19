import pytest
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.ast_nodes import CorpusDefinition, ShieldDefinition

def test_emcp_corpus_syntax():
    source = """
    corpus MyCorpus from mcp("my_server", "my_resource_uri")
    """
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    
    # Normally we might call a module parser, but we can call _parse_corpus_definition explicitly
    # if it's the first token. Just scanning until CORPUS token or parsing directly.
    parser.current = 0 # reset if needed
    ast_node = parser._parse_corpus_definition()
    
    assert isinstance(ast_node, CorpusDefinition)
    assert ast_node.name == "MyCorpus"
    assert ast_node.mcp_server == "my_server"
    assert ast_node.mcp_resource_uri == "my_resource_uri"

def test_emcp_shield_syntax():
    source = """
    shield MyShield {
        taint: untrusted
        scan: [prompt_injection]
    }
    """
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    
    ast_node = parser._parse_shield()
    
    assert isinstance(ast_node, ShieldDefinition)
    assert ast_node.name == "MyShield"
    assert ast_node.taint == "untrusted"
    assert ast_node.scan == ["prompt_injection"]
