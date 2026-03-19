from __future__ import annotations

from langgraph.graph import START, END, StateGraph

from orchestration.state import GraphState
from orchestration.routing import (
    route_after_agent_review,
    route_after_build,
    route_after_escalation_review,
    route_after_human_approval,
    route_after_human_review,
    route_after_plan,
    route_after_prepare,
    route_after_rework_analysis,
    route_after_rework_implementation,
    route_from_dispatch,
)
from orchestration.nodes import (
    prepare,
    plan,
    human_approval,
    build,
    agent_review,
    human_review,
    rework_analysis,
    rework_implementation,
    ship,
    escalation_review,
)


def dispatch(state: GraphState) -> GraphState:
    return state


def build_graph(checkpointer):
    graph = StateGraph(GraphState)

    graph.add_node("dispatch", dispatch)
    graph.add_node("prepare", prepare.run)
    graph.add_node("plan", plan.run)
    graph.add_node("human_approval_gate", human_approval.run)
    graph.add_node("build", build.run)
    graph.add_node("agent_review", agent_review.run)
    graph.add_node("escalation_review", escalation_review.run)
    graph.add_node("human_review", human_review.run)
    graph.add_node("rework_analysis", rework_analysis.run)
    graph.add_node("rework_implementation", rework_implementation.run)
    graph.add_node("ship", ship.run)

    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        route_from_dispatch,
        {
            "prepare": "prepare",
            "plan": "plan",
            "human_approval_gate": "human_approval_gate",
            "build": "build",
            "agent_review": "agent_review",
            "human_review": "human_review",
            "rework_analysis": "rework_analysis",
            "rework_implementation": "rework_implementation",
            "ship": "ship",
        },
    )

    graph.add_conditional_edges("prepare", route_after_prepare, {"plan": "plan", "__end__": END})
    graph.add_conditional_edges("plan", route_after_plan, {"human_approval_gate": "human_approval_gate", "__end__": END})
    graph.add_conditional_edges("human_approval_gate", route_after_human_approval, {"build": "build", "__end__": END})
    graph.add_conditional_edges("build", route_after_build, {"agent_review": "agent_review", "__end__": END})
    graph.add_conditional_edges(
        "agent_review",
        route_after_agent_review,
        {
            "escalation_review": "escalation_review",
            "human_review": "human_review",
            "__end__": END,
        },
    )
    graph.add_conditional_edges(
        "escalation_review",
        route_after_escalation_review,
        {
            "human_review": "human_review",
            "__end__": END,
        },
    )
    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {"ship": "ship", "rework_analysis": "rework_analysis", "__end__": END},
    )
    graph.add_conditional_edges(
        "rework_analysis",
        route_after_rework_analysis,
        {"rework_implementation": "rework_implementation", "__end__": END},
    )
    graph.add_conditional_edges(
        "rework_implementation",
        route_after_rework_implementation,
        {"agent_review": "agent_review", "__end__": END},
    )
    graph.add_edge("ship", END)

    return graph.compile(checkpointer=checkpointer)