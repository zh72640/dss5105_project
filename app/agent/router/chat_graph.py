"""Chat orchestration is independent of the v1 graph; SQLite is authoritative."""
from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from app.agent.conversation.interpreter import interpret


class ChatState(TypedDict, total=False):
    message: str
    context: dict
    mode: str
    model_key: str | None
    registry: object
    interpretation: object
    telemetry: dict


def interpret_turn(state):
    value,telemetry=interpret(state['message'],state['context'],state.get('registry'),state['mode'],state.get('model_key'))
    return {'interpretation':value,'telemetry':telemetry}


def build_graph():
    graph=StateGraph(ChatState)
    graph.add_node('interpret_turn',interpret_turn)
    graph.add_edge(START,'interpret_turn')
    graph.add_edge('interpret_turn',END)
    return graph.compile()


GRAPH=build_graph()
