"""
AXON Daemon Primitive — Compiler & Runtime Tests
===================================================
Verifies the daemon/listen primitives (AxonServer — π-calculus
reactive architecture) through all compiler stages: Lexer, Parser,
IR Generator, Backend, and Runtime infrastructure (EventBus, Supervisor).

Based on paper_daemon.md — the daemon primitive implements
co-inductive (νX) perpetual reactive servers grounded in:
  - π-Calculus: P ::= !c(x).Q (replicated listener)
  - Co-algebraic Semantics: δ : S → S × E (greatest fixpoint)
  - Linear Logic: Budget(n) ⊗ Event ⊸ Output ⊗ Budget(n-c)
  - CPS: auto-hibernate between event cycles
  - OTP: supervisor restart tree for crash recovery
"""

import asyncio

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.ir_generator import IRGenerator
from axon.compiler import ast_nodes as ast
from axon.compiler.ir_nodes import IRDaemon, IRListen, IRProgram
from axon.compiler.tokens import TokenType


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════


def _lex(source: str):
    """Helper: tokenize."""
    return Lexer(source).tokenize()


def _parse(source: str) -> ast.ProgramNode:
    """Helper: tokenize + parse in one step."""
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def _generate(source: str) -> IRProgram:
    """Helper: lex → parse → IR generate. Returns IRProgram."""
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    return IRGenerator().generate(tree)


# ═══════════════════════════════════════════════════════════════════
#  LEXER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestDaemonLexer:
    """Verify that the lexer produces DAEMON, LISTEN, BUDGET_PER_EVENT tokens."""

    def test_daemon_keyword_token(self):
        tokens = _lex("daemon")
        assert tokens[0].type == TokenType.DAEMON
        assert tokens[0].value == "daemon"

    def test_listen_keyword_token(self):
        tokens = _lex("listen")
        assert tokens[0].type == TokenType.LISTEN
        assert tokens[0].value == "listen"

    def test_budget_per_event_keyword_token(self):
        tokens = _lex("budget_per_event")
        assert tokens[0].type == TokenType.BUDGET_PER_EVENT
        assert tokens[0].value == "budget_per_event"

    def test_daemon_definition_tokens(self):
        """Verify token stream for a daemon declaration header."""
        source = 'daemon OrderDaemon(config: Config) -> Result {'
        tokens = _lex(source)
        assert tokens[0].type == TokenType.DAEMON
        assert tokens[1].type == TokenType.IDENTIFIER
        assert tokens[1].value == "OrderDaemon"
        assert tokens[2].type == TokenType.LPAREN
        assert tokens[3].type == TokenType.IDENTIFIER  # config
        assert tokens[4].type == TokenType.COLON
        assert tokens[5].type == TokenType.IDENTIFIER  # Config
        assert tokens[6].type == TokenType.RPAREN
        assert tokens[7].type == TokenType.ARROW
        assert tokens[8].type == TokenType.IDENTIFIER  # Result
        assert tokens[9].type == TokenType.LBRACE

    def test_listen_block_tokens(self):
        """Verify token stream for a listen block header."""
        source = 'listen "orders" as order_event {'
        tokens = _lex(source)
        assert tokens[0].type == TokenType.LISTEN
        assert tokens[1].type == TokenType.STRING
        assert tokens[1].value == "orders"
        assert tokens[2].type == TokenType.AS
        assert tokens[3].type == TokenType.IDENTIFIER
        assert tokens[3].value == "order_event"
        assert tokens[4].type == TokenType.LBRACE


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — DAEMON DEFINITION
# ═══════════════════════════════════════════════════════════════════


class TestDaemonParser:
    """Verify parsing of top-level daemon definitions."""

    def test_minimal_daemon(self):
        """Minimal daemon with one listen block."""
        source = '''daemon Echo(input: String) -> String {
    goal: "Echo events back"
    listen "events" as evt {
        step Process {
            ask: "Echo: {{evt}}"
            output: String
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert isinstance(decl, ast.DaemonDefinition)
        assert decl.name == "Echo"
        assert len(decl.parameters) == 1
        assert decl.parameters[0].name == "input"
        assert decl.goal == "Echo events back"
        assert len(decl.listeners) == 1

        listener = decl.listeners[0]
        assert isinstance(listener, ast.ListenBlock)
        assert listener.channel_expr == "events"
        assert listener.event_alias == "evt"
        assert len(listener.body) == 1

    def test_daemon_full_configuration(self):
        """Daemon with all configuration clauses."""
        source = '''daemon OrderProcessor(config: ServerConfig) -> OrderResult {
    goal: "Process incoming orders in real time"
    tools: [DBQuery, EmailSender]
    budget_per_event: {
        max_tokens: 5000
        max_time: 30s
        max_cost: 0.10
    }
    memory: OrderMemory
    strategy: react
    on_stuck: hibernate
    shield: InputGuard

    listen "orders" as order_event {
        step Validate {
            ask: "Validate order"
            output: String
        }
        step Process {
            ask: "Process order"
            output: OrderResult
        }
    }
    listen "cancellations" as cancel_event {
        step HandleCancel {
            ask: "Handle cancellation"
            output: String
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert isinstance(decl, ast.DaemonDefinition)
        assert decl.name == "OrderProcessor"
        assert decl.goal == "Process incoming orders in real time"
        assert decl.tools == ["DBQuery", "EmailSender"]
        assert decl.memory_ref == "OrderMemory"
        assert decl.strategy == "react"
        assert decl.on_stuck == "hibernate"
        assert decl.shield_ref == "InputGuard"

        # Budget per event (linear logic)
        budget = decl.budget_per_event
        assert budget is not None
        assert budget.max_tokens == 5000
        assert budget.max_time == "30s"
        assert budget.max_cost == 0.10

        # Listeners (π-calculus channels)
        assert len(decl.listeners) == 2
        assert decl.listeners[0].channel_expr == "orders"
        assert decl.listeners[0].event_alias == "order_event"
        assert len(decl.listeners[0].body) == 2
        assert decl.listeners[1].channel_expr == "cancellations"
        assert decl.listeners[1].event_alias == "cancel_event"
        assert len(decl.listeners[1].body) == 1

    def test_daemon_return_type(self):
        """Daemon with return type annotation."""
        source = '''daemon Worker(input: String) -> WorkResult {
    goal: "Process work items"
    listen "work" as item {
        step Do {
            ask: "Do work"
            output: WorkResult
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert isinstance(decl, ast.DaemonDefinition)
        assert decl.return_type is not None
        assert decl.return_type.name == "WorkResult"

    def test_daemon_empty_tools(self):
        """Daemon with empty tools list."""
        source = '''daemon NoTools(input: String) -> String {
    goal: "Stateless processing"
    tools: []
    listen "events" as evt {
        step Process {
            ask: "Process"
            output: String
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert decl.tools == []

    def test_daemon_default_strategy_and_on_stuck(self):
        """Verify default strategy and on_stuck values."""
        source = '''daemon Defaults(input: String) -> String {
    goal: "Test defaults"
    listen "events" as evt {
        step Process {
            ask: "Process"
            output: String
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert decl.strategy == "react"       # default
        assert decl.on_stuck == "hibernate"   # default (unlike agent's "escalate")

    def test_daemon_budget_without_colon(self):
        """budget_per_event with no colon separator (syntactic sugar)."""
        source = '''daemon Sugar(input: String) -> String {
    goal: "Test sugar"
    budget_per_event {
        max_tokens: 3000
    }
    listen "events" as evt {
        step Process {
            ask: "Process"
            output: String
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert decl.budget_per_event is not None
        assert decl.budget_per_event.max_tokens == 3000


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — LISTEN BLOCK
# ═══════════════════════════════════════════════════════════════════


class TestListenBlockParser:
    """Verify parsing of listen blocks within daemons."""

    def test_listen_without_alias(self):
        """Listen block without 'as' alias."""
        source = '''daemon Simple(input: String) -> String {
    goal: "Test"
    listen "events" {
        step Process {
            ask: "Process"
            output: String
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        listener = decl.listeners[0]
        assert listener.channel_expr == "events"
        assert listener.event_alias == ""

    def test_listen_multiple_steps(self):
        """Listen block with multiple steps."""
        source = '''daemon Multi(input: String) -> String {
    goal: "Test"
    listen "events" as evt {
        step First {
            ask: "First step"
            output: String
        }
        step Second {
            ask: "Second step"
            output: String
        }
        step Third {
            ask: "Third step"
            output: String
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        listener = decl.listeners[0]
        assert len(listener.body) == 3


# ═══════════════════════════════════════════════════════════════════
#  IR GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestDaemonIRGenerator:
    """Verify IR generation for daemon definitions."""

    def test_daemon_ir_generation(self):
        """Full daemon → IRDaemon with listeners → IRListen."""
        source = '''daemon OrderProcessor(config: ServerConfig) -> OrderResult {
    goal: "Process incoming orders"
    tools: [DBQuery, EmailSender]
    budget_per_event: {
        max_tokens: 5000
        max_time: 30s
        max_cost: 0.10
    }
    memory: OrderMemory
    strategy: react
    on_stuck: hibernate

    listen "orders" as order_event {
        step Validate {
            ask: "Validate order"
            output: String
        }
    }
    listen "cancellations" as cancel_event {
        step HandleCancel {
            ask: "Handle cancellation"
            output: String
        }
    }
}'''
        ir = _generate(source)
        assert len(ir.daemons) == 1

        daemon = ir.daemons[0]
        assert isinstance(daemon, IRDaemon)
        assert daemon.name == "OrderProcessor"
        assert daemon.goal == "Process incoming orders"
        assert daemon.tools == ("DBQuery", "EmailSender")
        assert daemon.max_tokens == 5000
        assert daemon.max_time == "30s"
        assert daemon.max_cost == 0.10
        assert daemon.memory_ref == "OrderMemory"
        assert daemon.strategy == "react"
        assert daemon.on_stuck == "hibernate"
        assert daemon.return_type == "OrderResult"
        assert daemon.continuation_id != ""  # SHA-256 generated

        # Listeners
        assert len(daemon.listeners) == 2
        listener0 = daemon.listeners[0]
        assert isinstance(listener0, IRListen)
        assert listener0.channel_topic == "orders"
        assert listener0.event_alias == "order_event"
        assert listener0.channel_type == "topic"
        assert len(listener0.children) == 1

        listener1 = daemon.listeners[1]
        assert listener1.channel_topic == "cancellations"
        assert listener1.event_alias == "cancel_event"
        assert len(listener1.children) == 1

    def test_daemon_continuation_id_deterministic(self):
        """continuation_id is deterministic for same source position."""
        source = '''daemon Test(input: String) -> String {
    goal: "Test"
    listen "events" as evt {
        step Process {
            ask: "Process"
            output: String
        }
    }
}'''
        ir1 = _generate(source)
        ir2 = _generate(source)
        assert ir1.daemons[0].continuation_id == ir2.daemons[0].continuation_id

    def test_daemon_default_budget(self):
        """Daemon without budget_per_event gets zero defaults."""
        source = '''daemon NoBudget(input: String) -> String {
    goal: "Test"
    listen "events" as evt {
        step Process {
            ask: "Process"
            output: String
        }
    }
}'''
        ir = _generate(source)
        daemon = ir.daemons[0]
        assert daemon.max_tokens == 0
        assert daemon.max_time == ""
        assert daemon.max_cost == 0.0

    def test_daemon_ir_immutability(self):
        """IRDaemon and IRListen are frozen dataclasses."""
        source = '''daemon Frozen(input: String) -> String {
    goal: "Test"
    listen "events" as evt {
        step Process {
            ask: "Process"
            output: String
        }
    }
}'''
        ir = _generate(source)
        daemon = ir.daemons[0]
        with pytest.raises(AttributeError):
            daemon.name = "Modified"


# ═══════════════════════════════════════════════════════════════════
#  BACKEND TESTS
# ═══════════════════════════════════════════════════════════════════


class TestDaemonBackend:
    """Verify backend compilation of daemon IR nodes."""

    def test_daemon_backend_compilation(self):
        """Daemon IR compiles to CompiledStep with daemon metadata."""
        from axon.backends.anthropic_backend import AnthropicBackend
        from axon.compiler.ir_nodes import (
            IRDaemon, IRListen, IRStep, IRFlow, IRPersona, IRContext,
            IRProgram, IRRun,
        )

        listener = IRListen(
            channel_topic="events",
            event_alias="evt",
            children=(
                IRStep(
                    name="Process",
                    ask="Process event",
                    output_type="String",
                ),
            ),
        )
        daemon = IRDaemon(
            name="TestDaemon",
            goal="Test daemon",
            tools=("WebSearch",),
            max_tokens=3000,
            max_time="10s",
            max_cost="",
            memory_ref="",
            strategy="react",
            on_stuck="hibernate",
            return_type="String",
            shield_ref="",
            continuation_id="test_cont_id_123",
            listeners=(listener,),
        )
        flow = IRFlow(
            name="TestFlow",
            return_type_name="String",
            parameters=(),
            steps=(daemon,),
        )
        persona = IRPersona(
            name="TestPersona",
            domain=("testing",),
            tone="neutral",
        )
        ctx = IRContext(
            name="TestContext",
        )
        run_node = IRRun(
            flow_name="TestFlow",
            persona_name="TestPersona",
            context_name="TestContext",
            effort="medium",
            resolved_flow=flow,
            resolved_persona=persona,
            resolved_context=ctx,
        )
        ir = IRProgram(
            personas=(persona,),
            contexts=(ctx,),
            flows=(flow,),
            runs=(run_node,),
            daemons=(daemon,),
        )

        backend = AnthropicBackend()
        compiled = backend.compile_program(ir)
        # Find the daemon step
        daemon_steps = [
            s for unit in compiled.execution_units
            for s in unit.steps
            if s.metadata.get("daemon")
        ]
        assert len(daemon_steps) == 1
        daemon_meta = daemon_steps[0].metadata["daemon"]
        assert daemon_meta["name"] == "TestDaemon"
        assert daemon_meta["goal"] == "Test daemon"
        assert daemon_meta["tools"] == ["WebSearch"]
        assert daemon_meta["max_tokens"] == 3000
        assert daemon_meta["max_time"] == "10s"
        assert daemon_meta["continuation_id"] != ""
        assert len(daemon_meta["listeners"]) == 1
        assert daemon_meta["listeners"][0]["channel_topic"] == "events"
        assert daemon_meta["listeners"][0]["event_alias"] == "evt"


# ═══════════════════════════════════════════════════════════════════
#  STATE BACKEND TESTS
# ═══════════════════════════════════════════════════════════════════


class TestDaemonStateBackend:
    """Verify daemon CPS fields in ExecutionState."""

    def test_execution_state_daemon_fields(self):
        """ExecutionState includes daemon-specific fields."""
        from axon.runtime.state_backend import ExecutionState

        state = ExecutionState(
            continuation_id="daemon_test_123",
            daemon_name="OrderDaemon",
            channel_topic="orders",
            event_index=42,
            daemon_state="processing",
        )
        assert state.daemon_name == "OrderDaemon"
        assert state.channel_topic == "orders"
        assert state.event_index == 42
        assert state.daemon_state == "processing"

    def test_execution_state_daemon_serialization(self):
        """Daemon fields survive serialization/deserialization cycle."""
        from axon.runtime.state_backend import ExecutionState

        state = ExecutionState(
            continuation_id="daemon_test_456",
            daemon_name="TestDaemon",
            channel_topic="events",
            event_index=7,
            daemon_state="hibernating",
        )
        serialized = state.serialize()
        restored = ExecutionState.deserialize(serialized)
        assert restored.daemon_name == "TestDaemon"
        assert restored.channel_topic == "events"
        assert restored.event_index == 7
        assert restored.daemon_state == "hibernating"

    def test_execution_state_daemon_defaults(self):
        """Default daemon fields for non-daemon execution states."""
        from axon.runtime.state_backend import ExecutionState

        state = ExecutionState(continuation_id="flow_test")
        assert state.daemon_name == ""
        assert state.channel_topic == ""
        assert state.event_index == 0
        assert state.daemon_state == "idle"


# ═══════════════════════════════════════════════════════════════════
#  EVENT BUS TESTS
# ═══════════════════════════════════════════════════════════════════


class TestEventBus:
    """Verify EventBus, InMemoryChannel, and Event primitives."""

    async def test_event_creation(self):
        """Event is an immutable data object."""
        from axon.runtime.event_bus import Event

        event = Event(
            topic="orders",
            payload={"item": "widget", "quantity": 5},
            event_id="evt-001",
            timestamp=1234567890.0,
        )
        assert event.topic == "orders"
        assert event.payload["item"] == "widget"
        assert event.event_id == "evt-001"

    async def test_in_memory_channel_publish_receive(self):
        """Basic publish → receive cycle on InMemoryChannel."""
        from axon.runtime.event_bus import Event, InMemoryChannel

        channel = InMemoryChannel(topic="test")
        event = Event(topic="test", payload="hello", event_id="1")
        await channel.publish(event)
        received = await channel.receive()
        assert received.payload == "hello"
        assert received.topic == "test"

    async def test_in_memory_channel_fifo(self):
        """Channel preserves FIFO order — linear logic semantics."""
        from axon.runtime.event_bus import Event, InMemoryChannel

        channel = InMemoryChannel(topic="fifo")
        for i in range(5):
            await channel.publish(Event(topic="fifo", payload=i, event_id=str(i)))

        for i in range(5):
            event = await channel.receive()
            assert event.payload == i

    async def test_in_memory_channel_close(self):
        """Closed channel rejects new publishes."""
        from axon.runtime.event_bus import InMemoryChannel, Event

        channel = InMemoryChannel(topic="close_test")
        assert not channel.is_closed
        channel.close()
        assert channel.is_closed
        with pytest.raises(RuntimeError, match="closed"):
            await channel.publish(Event(topic="close_test", payload="fail"))

    async def test_event_bus_get_or_create(self):
        """EventBus creates channels on demand."""
        from axon.runtime.event_bus import EventBus

        bus = EventBus()
        ch1 = bus.get_or_create("orders")
        ch2 = bus.get_or_create("orders")
        assert ch1 is ch2  # same channel for same topic
        assert bus.channel_count == 1

        bus.get_or_create("cancellations")
        assert bus.channel_count == 2

    async def test_event_bus_publish_receive(self):
        """EventBus routes events to correct channel."""
        from axon.runtime.event_bus import Event, EventBus

        bus = EventBus()
        channel = bus.get_or_create("orders")
        await bus.publish("orders", Event(topic="orders", payload="order-1"))
        received = await channel.receive()
        assert received.payload == "order-1"

    async def test_event_bus_topics(self):
        """EventBus lists all registered topics."""
        from axon.runtime.event_bus import EventBus

        bus = EventBus()
        bus.get_or_create("a")
        bus.get_or_create("b")
        bus.get_or_create("c")
        assert sorted(bus.topics()) == ["a", "b", "c"]

    async def test_event_bus_close_all(self):
        """EventBus close_all closes every channel."""
        from axon.runtime.event_bus import EventBus

        bus = EventBus()
        ch1 = bus.get_or_create("x")
        ch2 = bus.get_or_create("y")
        bus.close_all()
        assert ch1.is_closed
        assert ch2.is_closed

    async def test_channel_pending_count(self):
        """Channel tracks pending event count."""
        from axon.runtime.event_bus import Event, InMemoryChannel

        channel = InMemoryChannel(topic="pending")
        assert channel.pending == 0
        await channel.publish(Event(topic="pending", payload=1))
        await channel.publish(Event(topic="pending", payload=2))
        assert channel.pending == 2
        await channel.receive()
        assert channel.pending == 1


# ═══════════════════════════════════════════════════════════════════
#  SUPERVISOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestDaemonSupervisor:
    """Verify DaemonSupervisor OTP-style restart behavior."""

    async def test_supervisor_register(self):
        """Supervisor registers daemon specs."""
        from axon.runtime.supervisor import DaemonSupervisor

        supervisor = DaemonSupervisor()
        async def noop(): pass
        supervisor.register("test", noop)
        assert supervisor.daemon_count == 1

    async def test_supervisor_start_and_stop(self):
        """Supervisor starts and stops daemons cleanly."""
        from axon.runtime.supervisor import DaemonSupervisor

        completed = asyncio.Event()

        async def daemon_fn():
            completed.set()
            await asyncio.sleep(10)  # long running

        supervisor = DaemonSupervisor()
        supervisor.register("test_daemon", daemon_fn)
        await supervisor.start_all()
        await asyncio.wait_for(completed.wait(), timeout=2.0)
        assert supervisor.active_count >= 1
        await supervisor.stop_all()
        assert supervisor.active_count == 0

    async def test_supervisor_restart_on_crash(self):
        """Supervisor restarts a crashed daemon automatically."""
        from axon.runtime.supervisor import DaemonSupervisor, SupervisorConfig

        call_count = 0

        async def crashing_daemon():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Simulated crash")
            # Third call succeeds and runs
            await asyncio.sleep(10)

        config = SupervisorConfig(max_restarts=5, max_seconds=60.0)
        supervisor = DaemonSupervisor(config=config)
        supervisor.register("crasher", crashing_daemon)
        await supervisor.start_all()
        # Wait for restarts to happen
        await asyncio.sleep(0.5)
        assert call_count >= 3
        await supervisor.stop_all()

    async def test_supervisor_restart_intensity_limit(self):
        """Supervisor stops restarting after exceeding intensity limit."""
        from axon.runtime.supervisor import DaemonSupervisor, SupervisorConfig

        call_count = 0

        async def always_crash():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Always fails")

        config = SupervisorConfig(max_restarts=3, max_seconds=60.0)
        supervisor = DaemonSupervisor(config=config)
        supervisor.register("doomed", always_crash)
        await supervisor.start_all()
        await asyncio.sleep(1.0)
        # Should stop after exceeding max_restarts
        assert call_count <= 6  # some restarts, then stops
        await supervisor.stop_all()

    def test_supervisor_config_defaults(self):
        """SupervisorConfig has sensible defaults."""
        from axon.runtime.supervisor import SupervisorConfig, SupervisionStrategy

        config = SupervisorConfig()
        assert config.max_restarts == 5
        assert config.max_seconds == 60.0
        assert config.strategy == SupervisionStrategy.ONE_FOR_ONE


# ═══════════════════════════════════════════════════════════════════
#  FASE 16.a — HOOK PROTOCOL SURFACE
# ═══════════════════════════════════════════════════════════════════


class TestSupervisorHooks:
    """Verify SupervisorHooks integration (Fase 16.a).

    The OSS regression gate is hard: with `hooks=None`, the supervisor
    must behave byte-for-byte equivalent to pre-Fase-16. The tests
    above already verify that — these tests verify the new optional
    surface is wired correctly when hooks ARE registered.
    """

    async def test_hooks_default_no_op(self):
        """`DaemonSupervisor()` with no hooks behaves identically to today.

        Sanity check that the pre-Fase-16 lifecycle still works when
        no hooks are registered. The other 5 supervisor tests above
        already exercise the no-hooks path; this test is a marker.
        """
        from axon.runtime.supervisor import DaemonSupervisor

        supervisor = DaemonSupervisor()
        assert supervisor._hooks is None
        # Smoke: register + start + stop without hooks.
        async def noop():
            await asyncio.sleep(0.01)
        supervisor.register("test", noop)
        await supervisor.start_all()
        await supervisor.stop_all()
        assert supervisor.active_count == 0

    async def test_hooks_lifecycle_callbacks_fire(self):
        """Register a recording hook; verify start/crash/restart/intensity-exceeded fire in order."""
        from axon.runtime.supervisor import (
            DaemonSupervisor,
            SupervisorConfig,
        )

        events: list[tuple[str, str, int]] = []

        class RecordingHooks:
            async def on_daemon_start(self, name, attempt):
                events.append(("start", name, attempt))

            async def on_daemon_crash(self, name, exc, attempt):
                events.append(("crash", name, attempt))

            async def on_daemon_restart(self, name, attempt, delay_s):
                events.append(("restart", name, attempt))

            async def on_intensity_exceeded(self, name, restart_count):
                events.append(("intensity_exceeded", name, restart_count))

            async def snapshot_state(self, name):
                return None

            async def restore_state(self, name, snapshot):
                pass

            async def liveness_check(self, name):
                return True

            async def resolve_on_stuck(self, name, exc):
                return "restart"

        async def always_crash():
            raise RuntimeError("boom")

        config = SupervisorConfig(max_restarts=2, max_seconds=60.0)
        supervisor = DaemonSupervisor(config=config, hooks=RecordingHooks())
        supervisor.register("crasher", always_crash)
        await supervisor.start_all()
        await asyncio.sleep(0.5)
        await supervisor.stop_all()

        # At minimum: start + crash + restart events must fire, plus
        # intensity_exceeded once we exceed max_restarts.
        kinds = [e[0] for e in events]
        assert kinds.count("start") >= 1
        assert kinds.count("crash") >= 1
        assert kinds.count("restart") >= 1
        assert "intensity_exceeded" in kinds

    async def test_hooks_snapshot_restore_round_trip(self):
        """Snapshot → restore round-trip across a crash boundary."""
        from axon.runtime.supervisor import (
            DaemonSupervisor,
            SupervisorConfig,
        )

        snapshots_taken: list[str] = []
        snapshots_restored: list[str] = []
        call_count = 0

        class StateHooks:
            async def on_daemon_start(self, name, attempt): pass
            async def on_daemon_crash(self, name, exc, attempt): pass
            async def on_daemon_restart(self, name, attempt, delay_s): pass
            async def on_intensity_exceeded(self, name, restart_count): pass
            async def liveness_check(self, name): return True
            async def resolve_on_stuck(self, name, exc): return "restart"

            async def snapshot_state(self, name):
                snap = f"snap-{name}-{len(snapshots_taken)}"
                snapshots_taken.append(snap)
                return snap

            async def restore_state(self, name, snapshot):
                snapshots_restored.append(snapshot)

        async def crash_once_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("crash on first call")
            await asyncio.sleep(10)

        config = SupervisorConfig(max_restarts=5, max_seconds=60.0)
        supervisor = DaemonSupervisor(config=config, hooks=StateHooks())
        supervisor.register("stateful", crash_once_then_succeed)
        await supervisor.start_all()
        await asyncio.sleep(0.5)
        await supervisor.stop_all()

        # snapshot fired once (on the crash); restore fired once (on
        # the next start with the snapshot from the previous crash).
        assert len(snapshots_taken) >= 1
        assert len(snapshots_restored) >= 1
        # Round-trip integrity: the restored snapshot is the one taken.
        assert snapshots_restored[0] == snapshots_taken[0]

    async def test_on_stuck_policy_string_passthrough(self):
        """`DaemonSpec.on_stuck_policy` is plumbed and accessible via hooks."""
        from axon.runtime.supervisor import DaemonSupervisor

        seen_policies: list[str] = []

        class PolicyHooks:
            async def on_daemon_start(self, name, attempt): pass
            async def on_daemon_crash(self, name, exc, attempt): pass
            async def on_daemon_restart(self, name, attempt, delay_s): pass
            async def on_intensity_exceeded(self, name, restart_count): pass
            async def snapshot_state(self, name): return None
            async def restore_state(self, name, snapshot): pass
            async def liveness_check(self, name): return True

            async def resolve_on_stuck(self, name, exc):
                # Read the policy string from the supervisor's spec
                spec = supervisor._daemons[name]
                seen_policies.append(spec.on_stuck_policy)
                return "noop"  # terminate after one crash

        async def crasher():
            raise RuntimeError("die")

        supervisor = DaemonSupervisor(hooks=PolicyHooks())
        supervisor.register("a", crasher, on_stuck_policy="hibernate")
        supervisor.register("b", crasher, on_stuck_policy="escalate")
        await supervisor.start_all()
        await asyncio.sleep(0.5)
        await supervisor.stop_all()

        # Each daemon's policy string was observable from the hook.
        assert "hibernate" in seen_policies
        assert "escalate" in seen_policies

    async def test_on_stuck_policy_noop_terminates(self):
        """OSS supervisor honors `noop` policy (terminate without restart)."""
        from axon.runtime.supervisor import DaemonSupervisor

        call_count = 0

        class NoopHooks:
            async def on_daemon_start(self, name, attempt): pass
            async def on_daemon_crash(self, name, exc, attempt): pass
            async def on_daemon_restart(self, name, attempt, delay_s): pass
            async def on_intensity_exceeded(self, name, restart_count): pass
            async def snapshot_state(self, name): return None
            async def restore_state(self, name, snapshot): pass
            async def liveness_check(self, name): return True
            async def resolve_on_stuck(self, name, exc): return "noop"

        async def crasher():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("die")

        supervisor = DaemonSupervisor(hooks=NoopHooks())
        supervisor.register("terminal", crasher)
        await supervisor.start_all()
        await asyncio.sleep(0.3)
        await supervisor.stop_all()

        # `noop` means: crash once, no restart.
        assert call_count == 1

    async def test_hook_exceptions_are_swallowed(self):
        """Buggy hook can't crash the supervisor itself."""
        from axon.runtime.supervisor import DaemonSupervisor

        class BuggyHooks:
            async def on_daemon_start(self, name, attempt):
                raise RuntimeError("hook is broken")
            async def on_daemon_crash(self, name, exc, attempt):
                raise RuntimeError("hook is broken")
            async def on_daemon_restart(self, name, attempt, delay_s):
                raise RuntimeError("hook is broken")
            async def on_intensity_exceeded(self, name, restart_count):
                raise RuntimeError("hook is broken")
            async def snapshot_state(self, name):
                raise RuntimeError("hook is broken")
            async def restore_state(self, name, snapshot):
                raise RuntimeError("hook is broken")
            async def liveness_check(self, name):
                raise RuntimeError("hook is broken")
            async def resolve_on_stuck(self, name, exc):
                raise RuntimeError("hook is broken")

        async def short_lived():
            await asyncio.sleep(0.05)

        supervisor = DaemonSupervisor(hooks=BuggyHooks())
        supervisor.register("test", short_lived)
        # Should not raise despite every hook raising.
        await supervisor.start_all()
        await asyncio.sleep(0.2)
        await supervisor.stop_all()
        assert supervisor.active_count == 0


# ═══════════════════════════════════════════════════════════════════
#  FASE 16.b — RESTART-LOG EVICTION
# ═══════════════════════════════════════════════════════════════════


class TestRestartLogEviction:
    """Verify the per-daemon restart log stays bounded (Fase 16.b)."""

    def test_restart_log_evicts_old_entries(self):
        """Entries older than `max_seconds` are popped from the deque."""
        from axon.runtime.supervisor import (
            DaemonSupervisor,
            SupervisorConfig,
        )

        config = SupervisorConfig(max_restarts=3, max_seconds=1.0)
        supervisor = DaemonSupervisor(config=config)

        # Synthesize 100 restart events — half before the window cutoff,
        # half inside. After the last record, the deque must contain
        # only the in-window entries.
        now_anchor = 100.0
        for i in range(50):
            # 50 entries between now-2.0 and now-1.5 (outside window of 1.0s)
            supervisor._record_restart("d", now_anchor - 2.0 + 0.01 * i)
        for i in range(50):
            # 50 entries between now-0.5 and now (inside window)
            supervisor._record_restart("d", now_anchor - 0.5 + 0.01 * i)

        log = supervisor._restart_log["d"]
        # Deque maxlen = max_restarts + 1 = 4 — only the most recent
        # 4 entries survive the ringbuffer regardless of timestamp.
        assert len(log) <= config.max_restarts + 1
        # All surviving entries are inside the window.
        cutoff = now_anchor - config.max_seconds
        assert all(ts >= cutoff for ts in log)

    def test_restart_log_unbounded_pre_fase16_would_grow(self):
        """Before 16.b the log was an unbounded list — confirm we now use a deque."""
        from axon.runtime.supervisor import DaemonSupervisor
        from collections import deque

        supervisor = DaemonSupervisor()
        for i in range(10):
            supervisor._record_restart("d", float(i))
        log = supervisor._restart_log["d"]
        assert isinstance(log, deque)
        assert log.maxlen is not None  # bounded


# ═══════════════════════════════════════════════════════════════════
#  FASE 16.c — RACE-CONDITION FIX (asyncio.Lock around dict mutations)
# ═══════════════════════════════════════════════════════════════════


class TestRestartRaceCondition:
    """Verify concurrent crashes under one_for_all don't corrupt _tasks."""

    async def test_concurrent_crashes_no_dict_corruption(self):
        """5 daemons crash simultaneously under ONE_FOR_ALL — verify dict
        integrity (no duplicate keys, no missing keys, no leaked tasks)
        after the cascade settles. The cascade serialization flag
        ensures only the first crashing daemon's restart cascade runs;
        the others short-circuit and get cancelled-then-recreated by
        the in-flight cascade.
        """
        from axon.runtime.supervisor import (
            DaemonSupervisor,
            SupervisorConfig,
            SupervisionStrategy,
        )

        crash_event = asyncio.Event()
        per_daemon_calls: dict[str, int] = {}

        async def make_daemon(name: str):
            per_daemon_calls[name] = per_daemon_calls.get(name, 0) + 1
            if per_daemon_calls[name] == 1:
                await crash_event.wait()
                raise RuntimeError(f"{name} crashed")
            await asyncio.sleep(0.3)

        config = SupervisorConfig(
            max_restarts=10,
            max_seconds=60.0,
            strategy=SupervisionStrategy.ONE_FOR_ALL,
        )
        supervisor = DaemonSupervisor(config=config)
        N = 5
        for i in range(N):
            name = f"d{i}"
            supervisor.register(name, make_daemon, name)
        await supervisor.start_all()

        await asyncio.sleep(0.05)
        crash_event.set()
        # Give the cascade enough time to drain and recreate.
        await asyncio.sleep(0.4)

        # Dict-integrity invariants (the meat of the race-fix gate):
        #   1. exactly N keys (no duplicates, no missing)
        #   2. all expected names present
        #   3. supervisor reports the right active count
        assert len(supervisor._tasks) == N
        assert set(supervisor._tasks.keys()) == {f"d{i}" for i in range(N)}
        # Cascade flag must be cleared after settling.
        assert supervisor._cascade_in_progress is False

        await supervisor.stop_all()
        # Post-shutdown: no leaked entries.
        assert supervisor.active_count == 0


# ═══════════════════════════════════════════════════════════════════
#  DAEMON RESULT TESTS
# ═══════════════════════════════════════════════════════════════════


class TestDaemonResult:
    """Verify DaemonResult data structure."""

    def test_daemon_result_creation(self):
        """DaemonResult stores daemon execution metadata."""
        from axon.runtime.executor import DaemonResult

        result = DaemonResult(
            daemon_name="OrderDaemon",
            goal="Process orders",
            strategy="react",
            events_processed=5,
            channel_topic="orders",
            event_alias="order_event",
            on_stuck_fired=False,
            on_stuck_policy="hibernate",
            continuation_id="abc123",
        )
        assert result.daemon_name == "OrderDaemon"
        assert result.events_processed == 5
        assert result.continuation_id == "abc123"

    def test_daemon_result_to_dict(self):
        """DaemonResult serializes to dict."""
        from axon.runtime.executor import DaemonResult

        result = DaemonResult(
            daemon_name="TestDaemon",
            goal="Test",
            events_processed=1,
        )
        d = result.to_dict()
        assert d["daemon_name"] == "TestDaemon"
        assert d["goal"] == "Test"
        assert d["events_processed"] == 1

    def test_daemon_result_immutable(self):
        """DaemonResult is frozen."""
        from axon.runtime.executor import DaemonResult

        result = DaemonResult(daemon_name="Test")
        with pytest.raises(AttributeError):
            result.daemon_name = "Modified"


# ═══════════════════════════════════════════════════════════════════
#  INTEGRATION TESTS — Full Pipeline
# ═══════════════════════════════════════════════════════════════════


class TestDaemonIntegration:
    """End-to-end integration tests for daemon primitive."""

    def test_full_pipeline_lexer_to_ir(self):
        """Complete pipeline: source → lex → parse → IR for a daemon."""
        source = '''daemon AlertMonitor(config: MonitorConfig) -> Alert {
    goal: "Monitor system alerts and escalate critical issues"
    tools: [MetricsQuery, PagerDuty, SlackNotifier]
    budget_per_event: {
        max_tokens: 8000
        max_time: 60s
        max_cost: 0.25
    }
    memory: AlertHistory
    strategy: reflexion
    on_stuck: escalate

    listen "critical_alerts" as alert {
        step Triage {
            ask: "Triage this critical alert: {{alert}}"
            output: String
        }
        step Escalate {
            ask: "Escalate to on-call engineer"
            output: Alert
        }
    }

    listen "warnings" as warning {
        step Assess {
            ask: "Assess warning severity: {{warning}}"
            output: String
        }
    }
}'''
        ir = _generate(source)
        daemon = ir.daemons[0]

        # Verify complete IR structure
        assert daemon.name == "AlertMonitor"
        assert daemon.strategy == "reflexion"
        assert daemon.on_stuck == "escalate"
        assert daemon.max_tokens == 8000
        assert daemon.max_cost == 0.25
        assert daemon.memory_ref == "AlertHistory"
        assert len(daemon.listeners) == 2
        assert daemon.listeners[0].channel_topic == "critical_alerts"
        assert len(daemon.listeners[0].children) == 2
        assert daemon.listeners[1].channel_topic == "warnings"
        assert len(daemon.listeners[1].children) == 1

    def test_daemon_alongside_flow_and_agent(self):
        """Daemon co-exists with flows and agents in same program."""
        source = '''
flow SimpleFlow() -> String {
    step Hello {
        ask: "Hello world"
        output: String
    }
}

agent SimpleAgent(input: String) -> String {
    goal: "Simple agent"
    tools: []
    budget: { max_iterations: 5 }
    step Work {
        ask: "Do work"
        output: String
    }
}

daemon SimpleDaemon(input: String) -> String {
    goal: "Simple daemon"
    listen "events" as evt {
        step Process {
            ask: "Process event"
            output: String
        }
    }
}
'''
        ir = _generate(source)
        assert len(ir.flows) == 1
        assert len(ir.agents) == 1
        assert len(ir.daemons) == 1
        assert ir.flows[0].name == "SimpleFlow"
        assert ir.agents[0].name == "SimpleAgent"
        assert ir.daemons[0].name == "SimpleDaemon"

    def test_daemon_with_hibernate_in_listener(self):
        """Daemon listener can contain hibernate nodes (CPS integration)."""
        source = '''daemon WithHibernate(input: String) -> String {
    goal: "Test hibernate integration"
    listen "events" as evt {
        step Process {
            ask: "Process"
            output: String
        }
        hibernate until "manual_resume"
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        listener = decl.listeners[0]
        assert len(listener.body) == 2
        assert isinstance(listener.body[1], ast.HibernateNode)
        assert listener.body[1].event_name == "manual_resume"

    def test_daemon_with_par_in_listener(self):
        """Daemon listener can contain parallel blocks."""
        source = '''daemon WithPar(input: String) -> String {
    goal: "Test parallel integration"
    listen "events" as evt {
        par {
            step A {
                ask: "Do A"
                output: String
            }
            step B {
                ask: "Do B"
                output: String
            }
        }
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        listener = decl.listeners[0]
        assert len(listener.body) == 1
        assert isinstance(listener.body[0], ast.ParallelBlock)
        assert len(listener.body[0].branches) == 2

    def test_multiple_daemons_in_program(self):
        """Program can contain multiple daemon definitions."""
        source = '''
daemon DaemonA(input: String) -> String {
    goal: "Daemon A"
    listen "ch_a" as ea {
        step Process {
            ask: "A"
            output: String
        }
    }
}

daemon DaemonB(input: String) -> String {
    goal: "Daemon B"
    listen "ch_b" as eb {
        step Process {
            ask: "B"
            output: String
        }
    }
}
'''
        ir = _generate(source)
        assert len(ir.daemons) == 2
        names = {d.name for d in ir.daemons}
        assert names == {"DaemonA", "DaemonB"}
